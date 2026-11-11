"""下载调度服务。

队列语义（works.state）：inQueue（或 NULL，兼容旧数据）→ downloading →
done / failed；stopped 可随时由 API 置入：调度时被跳过，且不会被完成回调
覆盖。认领即置为 downloading；轮末等待池内任务全部收尾，并把进程中断残留
的 downloading 重新入队。站点暂无可用下载脚本时任务不标 failed，而是置
noDownloader 挂起——下载脚本上传/重载或服务启动后，站点已有脚本的挂起
作品自动刷回 inQueue（见 requeue_no_downloader）。

站点模型：守护线程周期性发现有待下载作品的站点，为每个站点启动独立的
调度线程——各自独立的线程池、轮间隔、数量限制、缓存/路径，互不干扰。
站点级配置统一写在 download.yaml 的 `site` 结构下（键为 website，解析顺序
site.<website> > site.default > 代码内置兜底）；根键 do_download 是总开关，
站点级 do_download 可单独关闭某站点。开关关闭时站点调度线程退出，恢复后由
守护线程自动拉起。

下载路径包装（脚本拿站点级下载根，作品子目录由脚本自建）：
    传给脚本的 download_path 是站点级下载根 <根>/<website>/：use_cache 开 →
    cache_path/<website>，关 → download_path/<website>。脚本在其下自建作品
    子目录，download_it 返回产物路径（相对该根或绝对路径均可）。
    交付：cache_path 与 download_path 不一致时，框架按相对层级把产物搬到
    download_path/<website>/ 下并清理该作品在缓存侧的残留；两层一致（未配
    独立缓存层）时无需搬运，产物原地保留。
"""

import calendar
import json
import os
import shutil
from datetime import datetime, time as dtime
from threading import Event, Thread

from sqlalchemy import or_

from src.config.config import ConfigManager, GetUnknownKey, _UNSET, config_manager
from src.config.paths import (
    download_cache_path as _default_cache_path,
    download_path as _default_download_path,
    download_script_sources,
)
from src.service.dispatcher import ScriptDispatcher, ScriptRouteError
from src.service.script_tools import ScriptTools
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Works
from src.utils.cookie_manager import CookieManager

# 站点暂无可用下载脚本时任务的挂起状态：不参与认领，等脚本就位后统一刷回 inQueue
NO_DOWNLOADER_STATE = 'noDownloader'


class Downloader:
    """下载管理器（每站点独立配置与调度）。

    队列语义、站点模型与下载路径包装详见模块文档；本类持有全部站点调度
    线程与其线程池，stop() 统一收尾。

    Attributes:
        dispatcher: 按 website 路由到 DownloadWork 脚本类的分发器。
        _stop_event: 停止信号；所有等待均通过它实现，保证可被 stop() 立即唤醒。
        _runners: website → 站点调度线程的注册表。
        _pools: website → 站点线程池的注册表（与 _runners 同生命周期）。
    """

    # 以下两个调度周期的默认值；实际生效值读 download.yaml 根键（可配置、热更新）
    SUPERVISOR_TICK = 5      # download.site_scan_interval
    WINDOW_CHECK_TICK = 60   # download.window_check_interval

    def __init__(self):
        """初始化空的注册表与停止信号；实际装配由 init() 完成。"""
        self.dispatcher = None
        self._stop_event = Event()
        self._runners = {}   # website -> 调度线程
        self._pools = {}     # website -> ThreadPool

    # ---------------- 站点级配置 ----------------

    @staticmethod
    def site_setting(website, key, default=_UNSET):
        """站点级下载配置：download.yaml 的 site.<website> > site.default > 代码兜底。

        Args:
            website: 站点名。
            key: 配置键。
            default: 全链未配置时的代码级兜底值（缺省则抛 GetUnknownKey）。

        Returns:
            解析后的配置值。
        """
        return ConfigManager.site_setting('download', website, key, default)

    # ---------------- 可下载时间窗口 ----------------

    @classmethod
    def _tick(cls, key, default):
        """读取调度周期类配置（秒）。

        Args:
            key: download 配置键。
            default: 键缺失或非法时使用的内置默认值。

        Returns:
            int: 生效的周期秒数（最小 1 秒）。
        """
        try:
            return max(1, int(ConfigManager.get('download', key)))
        except (GetUnknownKey, TypeError, ValueError):
            return default

    @staticmethod
    def _parse_hhmm(value):
        """解析 HH:MM 为 time 对象。

        Args:
            value: 形如 ``HH:MM`` 的值（可为其他可 str() 的类型）。

        Returns:
            time | None: 解析结果；非法输入返回 None（由调用方区分缺省与非法）。
        """
        try:
            hour, minute = str(value).split(':', 1)
            return dtime(int(hour), int(minute))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_ints(values):
        """把可迭代元素容错地转为 int，转换失败的项跳过。

        Args:
            values: 待转换的可迭代对象（元素须可 int()）；None 视为空。

        Returns:
            list[int]: 转换成功的整数列表。
        """
        ints = []
        for v in values or []:
            try:
                ints.append(int(v))
            except (TypeError, ValueError):
                continue
        return ints

    @classmethod
    def _in_download_window(cls, website, now=None):
        """当前时间是否处于该站点的可下载时间窗口。

        未配置窗口（或配置非法）时始终放行（fail-open）。
        mode: daily 每天 / weekly 每周（weekdays: 1=周一..7=周日）/ monthly 每月
              （month_days 支持负数，-1=当月最后一天）；start/end 为 HH:MM，
              支持跨天（如 22:00-06:00），start==end 视为空窗口。

        Args:
            website: 站点名。
            now: 判定基准时间；None 取当前时间。

        Returns:
            bool: 是否处于窗口内。
        """
        try:
            window = cls.site_setting(website, 'download_window', None)
        except GetUnknownKey:
            return True
        if not isinstance(window, dict) or not window:
            return True
        mode = str(window.get('mode', 'always')).strip().lower()
        if mode in ('', 'always'):
            return True
        now = now or datetime.now()
        raw_start, raw_end = window.get('start'), window.get('end')
        start = cls._parse_hhmm(raw_start) if raw_start is not None else dtime(0, 0)
        end = cls._parse_hhmm(raw_end) if raw_end is not None else dtime(23, 59, 59)
        if (raw_start is not None and start is None) or (raw_end is not None and end is None):
            logger.warning(f"[{website}] download_window 的 start/end 格式非法，忽略时间窗口限制")
            return True

        if start <= end:
            in_time = start <= now.time() < end
        else:
            in_time = now.time() >= start or now.time() < end  # 跨天窗口

        if mode == 'daily':
            return in_time
        if mode == 'weekly':
            weekdays = cls._to_ints(window.get('weekdays'))
            if not weekdays:
                logger.warning(f"[{website}] download_window.mode=weekly 但未配置 weekdays，忽略时间窗口限制")
                return True
            return now.isoweekday() in weekdays and in_time
        if mode == 'monthly':
            month_days = cls._to_ints(window.get('month_days'))
            if not month_days:
                logger.warning(f"[{website}] download_window.mode=monthly 但未配置 month_days，忽略时间窗口限制")
                return True
            last_day = calendar.monthrange(now.year, now.month)[1]
            day = now.day
            matched = any(
                day == d or (d < 0 and day == last_day + d + 1)
                for d in month_days
            )
            return matched and in_time
        logger.warning(f"[{website}] download_window.mode 未识别: {mode}（支持 daily/weekly/monthly），忽略窗口限制")
        return True

    # ---------------- 生命周期 ----------------

    def init(self):
        """初始化分发器、恢复挂起作品并启动站点巡检守护线程。

        构建按 website 分发下载脚本的分发器，把站点脚本已就位的
        noDownloader 挂起作品刷回 inQueue，再拉起巡检守护线程。
        """
        logger.info("Downloader初始化")

        # 按 website 分发下载脚本（多文件来源，每次重载重新求值），未声明的传统单类兜底
        self.dispatcher = ScriptDispatcher(download_script_sources, fallback_class_name="DownloadWork")
        # 上次运行中挂起的作品，若其站点的脚本如今已就位则直接重新入队
        self.requeue_no_downloader()

        supervisor = Thread(target=lambda: self._supervisor_loop(),
                            daemon=True, name="DownloadSupervisor")
        supervisor.start()
        logger.info("下载站点巡检守护线程已启动")

    def stop(self):
        """请求停止全部站点调度，并等待各线程池任务收尾。

        置全局停止事件（所有 sleep 均基于它，可被立即唤醒）后逐池 shutdown；
        各站点调度线程随之退出。
        """
        self._stop_event.set()
        for pool in list(self._pools.values()):
            pool.shutdown(wait=True, cancel_futures=True)
        logger.info("Downloader 已停止")

    # ---------------- 站点巡检与站点调度线程 ----------------

    def _supervisor_loop(self):
        """周期性发现有待下载作品的站点，为每个站点启动独立调度线程。"""
        while not self._stop_event.is_set():
            try:
                # 全局总开关关闭时不拉起任何站点
                if ConfigManager.get('download', 'do_download'):
                    for website in self._pending_sites():
                        # 站点级开关关闭的站点不启动（未配置视为开启）
                        if website not in self._runners and self.site_setting(website, 'do_download', True):
                            self._start_site_runner(website)
            except Exception as e:
                logger.error(f"下载站点巡检异常: {e}")
            self._stop_event.wait(timeout=self._tick('site_scan_interval', self.SUPERVISOR_TICK))

    def _pending_sites(self):
        """查询当前有待下载作品（inQueue/NULL）的站点集合。

        Returns:
            set[str]: 存在待下载作品的 website 集合；守护线程据此拉起站点调度线程。
        """
        with DatabaseManager.get_db_session() as session:
            rows = (
                session.query(Works.website)
                .filter(or_(Works.state.is_(None), Works.state == 'inQueue'))
                .distinct()
                .all()
            )
        return {row[0] for row in rows}

    def _start_site_runner(self, website):
        """为站点启动调度线程并登记到 _runners。

        Args:
            website: 站点名。
        """
        thread = Thread(target=lambda: self._site_runner(website),
                        daemon=True, name=f"DownloadSite-{website}")
        self._runners[website] = thread
        thread.start()
        logger.info(f"站点调度线程已启动: {website}")

    def _site_runner(self, website):
        """站点调度线程入口：装配站点专属线程池，退出时清理注册表。

        Args:
            website: 站点名。
        """
        pool = ThreadPool(
            max_workers=self.site_setting(website, 'download_thread', 1),
            name=f"Download-{website}",
        )
        self._pools[website] = pool
        try:
            self._site_loop(website, pool)
        except Exception as e:
            logger.error(f"站点 {website} 调度线程异常退出: {e}")
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            self._pools.pop(website, None)
            self._runners.pop(website, None)
            logger.info(f"站点调度线程已退出: {website}")

    def _site_loop(self, website, pool):
        """单个站点的下载调度循环：配置全部按站点解析，可热更新。

        受可下载时间窗口门控，窗口外分段等待；站点级/全局开关关闭时退出本线程。

        Args:
            website: 站点名。
            pool: 本站点专属的下载线程池。
        """
        outside_logged = False
        inside_logged = False
        while not self._stop_event.is_set():
            # 站点级/全局开关关闭 → 退出本站调度线程，恢复后由守护线程重新拉起
            if not ConfigManager.get('download', 'do_download') \
                    or not self.site_setting(website, 'do_download', True):
                logger.info(f"站点 {website} 下载已关闭，调度线程退出")
                return

            # 可下载时间窗口门控：窗口外分段等待（60s 一查，配置热更新及时生效），
            # 仅在状态切换时打日志，避免刷屏
            if not self._in_download_window(website):
                if not outside_logged:
                    logger.info(f"[{website}] 当前不在可下载时间窗口，等待窗口开启…")
                    outside_logged = True
                    inside_logged = False
                self._stop_event.wait(timeout=self._tick('window_check_interval', self.WINDOW_CHECK_TICK))
                continue
            if not inside_logged:
                logger.info(f"[{website}] 进入可下载时间窗口，开始调度")
                inside_logged = True
            outside_logged = False

            try:
                start_time = datetime.now()
                logger.info(f"[{website}] 开始执行下载轮次，时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

                download_count = 0
                once_download_number = self.site_setting(website, 'once_download_number', -1)

                # 回收本站点上次中断残留的任务
                self._requeue_stale_downloading(website)

                # 本轮下载循环
                while not self._stop_event.is_set():
                    if once_download_number != -1 and download_count >= once_download_number:
                        logger.info(f"[{website}] 达到下载数量限制 {once_download_number}，本轮下载结束")
                        break

                    work_dict = self._claim_next_work(website)
                    if work_dict is None:
                        logger.info(f"[{website}] 没有待下载的作品，本轮下载结束")
                        break

                    pool.submit(self._run_download_task, work_dict)
                    download_count += 1
                    logger.info(f"[{website}] 提交下载任务 {download_count}: "
                                f"{work_dict.get('workNumber')}@{work_dict.get('website')}")

                # 等待本轮已认领的任务完成，再做善后与休眠
                pool.wait_for_completion()

                # 轮间隔（-1 表示持续下载）；每次轮末重读，配置热更新即时生效
                elapsed = (datetime.now() - start_time).total_seconds()
                target_interval = self.site_setting(website, 'download_interval', -1)
                if target_interval == -1:
                    logger.info(f"[{website}] 本轮下载耗时: {elapsed:.2f}秒，间隔为 -1，立即开始下一轮")
                else:
                    remain = target_interval - elapsed
                    if remain > 0:
                        logger.info(f"[{website}] 本轮下载耗时: {elapsed:.2f}秒，休眠 {remain:.2f}秒后开始下一轮")
                        # 分段休眠：期间每 WINDOW_CHECK_TICK 回到循环顶部重新评估窗口与配置
                        while remain > 0 and not self._stop_event.is_set():
                            chunk = min(remain, self._tick('window_check_interval', self.WINDOW_CHECK_TICK))
                            if self._stop_event.wait(timeout=chunk):
                                return
                            remain -= chunk
                    else:
                        logger.info(f"[{website}] 本轮下载耗时: {elapsed:.2f}秒，已超过间隔时间，立即开始下一轮")

            except Exception as e:
                logger.error(f"[{website}] 下载轮次异常: {e}")
                self._stop_event.wait(timeout=5)

    # ---------------- 队列操作（按站点） ----------------

    def _claim_next_work(self, website):
        """认领该站点按优先级排最前的待下载作品。

        认领即置为 downloading（单线程认领，免竞态）；无任务返回 None。
        注意：会话提交后 ORM 对象即过期，返回的字典必须在会话内构造。

        Args:
            website: 站点名（只认领该站点的作品）。

        Returns:
            dict | None: 作品快照（含 website/downloadInfo 等全部字段），无任务时 None。
        """
        with DatabaseManager.get_db_session() as session:
            work = (
                session.query(Works)
                .filter(Works.website == website)
                .filter(or_(Works.state.is_(None), Works.state == 'inQueue'))
                .order_by(Works.downloadPriority.desc(), Works.workNumber)
                .first()
            )
            if work is None:
                return None
            work.state = 'downloading'
            # 会话提交后 ORM 对象即过期，必须在会话内拷贝成字典
            return {
                'workNumber': work.workNumber,
                'website': work.website,
                'upTime': work.upTime,
                'title': work.title,
                'kind': work.kind,
                'state': work.state,
                'downloadDate': work.downloadDate,
                'downloadPriority': work.downloadPriority,
                'downloadInfo': work.downloadInfo,
            }

    def _finish_work(self, work_number, website, success):
        """任务收尾：回写作品状态。

        成功置 done 并记录 downloadDate；失败置 failed。仅当当前状态为
        downloading 时才更新——不覆盖下载期间被 API 置入的 stopped。

        Args:
            work_number: 作品编号。
            website: 站点名。
            success: 下载是否成功。
        """
        with DatabaseManager.get_db_session() as session:
            work = session.get(Works, (work_number, website))
            if work is None or work.state != 'downloading':
                return
            if success:
                work.state = 'done'
                work.downloadDate = datetime.now().isoformat(timespec='seconds')
            else:
                work.state = 'failed'

    def _mark_no_downloader(self, work_number, website):
        """任务因站点无可用下载脚本而挂起：置为 noDownloader。

        仅当当前状态为 downloading 时才更新——不覆盖下载期间被 API 置入的
        stopped。挂起后不参与认领，等脚本就位后由 requeue_no_downloader
        统一刷回 inQueue。

        Args:
            work_number: 作品编号。
            website: 站点名。
        """
        with DatabaseManager.get_db_session() as session:
            work = session.get(Works, (work_number, website))
            if work is None or work.state != 'downloading':
                return
            work.state = NO_DOWNLOADER_STATE

    def requeue_no_downloader(self):
        """把站点已就位下载脚本的挂起作品（noDownloader）刷回 inQueue。

        脚本上传/重载或服务启动后调用。只有站点已有可用脚本（路由表精确
        命中，或存在对任意站点生效的兜底类）的挂起作品才刷回；仍无脚本的
        站点保持挂起，避免反复认领-失败。刷回后由巡检线程按既有节奏拉起
        下载，无需额外唤醒。

        Returns:
            int: 刷回 inQueue 的作品数。
        """
        if self.dispatcher is None:
            return 0
        try:
            with DatabaseManager.get_db_session() as session:
                query = session.query(Works).filter(Works.state == NO_DOWNLOADER_STATE)
                if not self.dispatcher.has_fallback():
                    # 无兜底类时只有路由表已覆盖的站点可以恢复
                    query = query.filter(Works.website.in_(self.dispatcher.websites()))
                requeued = query.update({Works.state: 'inQueue'})
        except Exception as e:
            logger.error(f"刷新 noDownloader 挂起作品失败: {e}")
            return 0
        if requeued:
            logger.info(f"已把 {requeued} 个等待下载脚本的挂起作品重新入队")
        return requeued

    def _requeue_stale_downloading(self, website):
        """把该站点上次进程中断残留的 downloading 重新入队（每轮开始时调用）。

        Args:
            website: 站点名。
        """
        with DatabaseManager.get_db_session() as session:
            stale = (
                session.query(Works)
                .filter(Works.website == website)
                .filter(Works.state == 'downloading')
                .update({Works.state: 'inQueue'})
            )
        if stale:
            logger.warning(f"[{website}] 重置 {stale} 个中断残留的 downloading 作品为 inQueue")

    # ---------------- 任务执行 ----------------

    @staticmethod
    def _parse_result(result):
        """规范化 download_it 的返回值。

        Args:
            result: download_it 的返回值（str 产物路径，或 dict 形如
                ``{path, duration?}``）。

        Returns:
            tuple: (产物路径, 时长秒数)；缺失的项为 None。
        """
        if isinstance(result, dict):
            return result.get('path'), result.get('duration')
        return result, None

    def _deliver_to_final(self, cache_root, download_root, payload, website):
        """cache 模式收尾：把脚本产物从缓存根搬到最终保存根；两层一致则原地保留。

        约定（与脚本模板一致）：
        - 脚本拿到的是站点级下载根 <cache_root>/<website>/，作品子目录由脚本自建；
        - payload 为产物路径，相对站点根或绝对路径均可；
        - cache_root 与 download_root 一致（未配独立缓存层）时无需搬运，返回 None；
        - 否则按相对层级搬到 <download_root>/<website>/<rel>，并清理该作品在
          缓存侧的顶层残留（脚本可能产出 payload 之外的伴生文件，如弹幕 xml）。

        Args:
            cache_root: 缓存根目录。
            download_root: 最终保存根目录。
            payload: 脚本 download_it 返回的产物路径（str）。
            website: 站点名。

        Returns:
            str | None: 产物最终落到的路径；无需搬运时 None。

        Raises:
            RuntimeError: payload 指向站点根本身、不在缓存根之下或路径不存在。
        """
        if os.path.normpath(os.path.abspath(cache_root)) \
                == os.path.normpath(os.path.abspath(download_root)):
            return None  # 未配独立缓存层：脚本产物已在最终根下，原地保留
        cache_site = os.path.normpath(os.path.abspath(os.path.join(cache_root, website)))
        src = os.path.normpath(payload if os.path.isabs(payload)
                               else os.path.join(cache_site, payload))
        if not os.path.exists(src):
            raise RuntimeError(f"脚本返回的下载路径不存在: {payload}（解析为 {src}）")
        rel = os.path.relpath(os.path.normpath(os.path.abspath(src)), cache_site)
        if rel == os.curdir:
            raise RuntimeError("download_it 不能返回站点下载根目录本身，应返回其中的产物路径")
        if rel.split(os.sep)[0] == os.pardir:
            raise RuntimeError(f"产物路径 {payload} 不在缓存下载根 {cache_site} 之下，无法搬运")
        dest = os.path.normpath(os.path.join(download_root, website, rel))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.isdir(src) and os.path.exists(dest):
            shutil.rmtree(dest)  # 目的地已有旧产物（上次中断残留）：整体替换
        shutil.move(src, dest)
        # 清理本作品在缓存侧的顶层残留（payload 只指向目录内单个文件时尤其必要）
        top = os.path.join(cache_site, rel.split(os.sep)[0])
        if os.path.isdir(top):
            shutil.rmtree(top, ignore_errors=True)
        elif os.path.exists(top):
            os.remove(top)
        return dest

    def _run_download_task(self, work_data):
        """线程池任务：执行单个作品的下载并做成功/失败收尾。

        流程：读站点配置 → 解析 downloadInfo → 分发脚本类并把站点级下载根
        交给脚本（作品子目录由脚本自建）→ 调 download_it() → 缓存层与最终层
        不一致时搬运产物 → 回写状态 → 按站点节奏睡眠。站点无可用下载脚本
        （ScriptRouteError）时置 noDownloader 挂起而非 failed；其余任何异常
        都置为 failed 并记录日志。

        Args:
            work_data: _claim_next_work 返回的作品快照字典。
        """
        work_number = work_data.get('workNumber')
        website = work_data.get('website')
        try:
            waiting_play = self.site_setting(website, 'waiting_play', False)
            sleep_second = self.site_setting(website, 'sleep_second', 10)
            use_cache = bool(self.site_setting(website, 'use_cache', True))
            final_root = self.site_setting(website, 'download_path', _default_download_path())
            # 站点级下载根：use_cache 开指向缓存根，关则直接指向最终根（无需搬运）
            cache_root = self.site_setting(website, 'cache_path', _default_cache_path()) \
                if use_cache else final_root
            work_root = os.path.join(cache_root, website)
            os.makedirs(work_root, exist_ok=True)

            # downloadInfo 存的是该作品的统一下载参数（JSON 文本），反序列化后交给脚本
            download_info = None
            raw_info = work_data.get('downloadInfo')
            if raw_info:
                try:
                    download_info = json.loads(raw_info)
                except (TypeError, ValueError):
                    logger.warning(f"作品 {work_number}@{website} 的 downloadInfo 不是合法 JSON，已忽略")

            worker_class = self.dispatcher.get(website)
            downloader_instance = worker_class(
                work_info=work_data,
                download_path=work_root,
                download_info=download_info,
            )
            downloader_instance.logger = logger
            downloader_instance.config_manager = config_manager
            downloader_instance.cookie_manager = CookieManager
            # 运行时工具集：站点绑定的日志/登录态浏览器/扩展注册入口
            downloader_instance.tools = ScriptTools(website=website)

            result = downloader_instance.download_it()
            payload, duration = self._parse_result(result)

            if use_cache:
                if not payload:
                    raise RuntimeError("缓存模式下 download_it 必须返回下载产物路径")
                dest = self._deliver_to_final(cache_root, final_root, payload, website)
                if dest:
                    logger.info(f"产物已搬运到 {dest}")

            self._finish_work(work_number, website, success=True)
            logger.info(f"下载完成: {work_number}@{website}")

            # 任务间节奏：等待播放时优先用脚本返回的时长，否则按站点定长睡眠
            if waiting_play and isinstance(duration, (int, float)):
                self._stop_event.wait(timeout=duration)
            else:
                self._stop_event.wait(timeout=sleep_second)

        except ScriptRouteError as e:
            logger.warning(f"作品 {work_number}@{website} 暂无可用下载脚本，挂起等待上传: {e}")
            try:
                self._mark_no_downloader(work_number, website)
            except Exception as finish_err:
                logger.error(f"标记无下载脚本挂起状态时出错 {work_number}@{website}: {finish_err}")

        except Exception as e:
            logger.error(f"下载任务失败 {work_number}@{website}: {e}")
            try:
                self._finish_work(work_number, website, success=False)
            except Exception as finish_err:
                logger.error(f"标记下载失败状态时出错 {work_number}@{website}: {finish_err}")


downloader = Downloader()

def init():
    """模块级初始化入口：初始化全局 downloader 单例（分发器 + 调度线程）。"""
    global downloader
    downloader.init()
