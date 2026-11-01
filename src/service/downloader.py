import calendar
import json
import os
import re
import shutil
from datetime import datetime, time as dtime
from threading import Event, Thread

from sqlalchemy import or_

from src.config.config import ConfigManager, GetUnknownKey, config_manager
from src.config.paths import download_script_sources
from src.service.dispatcher import ScriptDispatcher
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Works
from src.utils.cookie_manager import CookieManager


class Downloader:
    """
    下载管理器（每站点独立配置与调度）

    队列语义（works.state）：
        inQueue（或 NULL，兼容旧数据） -> downloading -> done / failed
        stopped 可随时由 API 置入：调度时被跳过，且不会被完成回调覆盖
    认领即置为 downloading；轮末等待池内任务全部收尾，并把进程中断残留的
    downloading 重新入队。

    站点模型：守护线程周期性发现有待下载作品的站点，为每个站点启动独立的
    调度线程——各自独立的线程池、轮间隔、数量限制、缓存/路径，互不干扰。
    站点级配置写在 download_sites.yaml（键为 website，未写出的键回落全局
    download_setting.yaml）；全局 do_download 是总开关，站点级 do_download
    可单独关闭某站点。开关关闭时站点调度线程退出，恢复后由守护线程自动拉起。

    下载路径包装（对脚本屏蔽缓存细节）：
        use_cache 开：脚本拿到缓存中的专属工作目录，产物返回后由框架拷贝到
                      最终保存路径 download_path/<website>/<work>/ 并清理缓存目录
        use_cache 关：脚本直接拿到最终保存目录，写完即结束
    """

    # 以下两个调度周期的默认值；实际生效值读 download_setting.yaml（可配置、热更新）
    SUPERVISOR_TICK = 5      # download_setting.site_scan_interval
    WINDOW_CHECK_TICK = 60   # download_setting.window_check_interval

    def __init__(self):
        self.dispatcher = None
        self._stop_event = Event()
        self._runners = {}   # website -> 调度线程
        self._pools = {}     # website -> ThreadPool

    # ---------------- 站点级配置 ----------------

    @staticmethod
    def site_setting(website, key):
        """站点级下载配置：download_sites.<website>.<key> 覆盖 download_setting.<key>"""
        return ConfigManager.site_setting('download_sites', 'download_setting', website, key)

    # ---------------- 可下载时间窗口 ----------------

    @classmethod
    def _tick(cls, key, default):
        """读取调度周期类配置（秒）；键缺失或非法时用内置默认值，最小 1 秒。"""
        try:
            return max(1, int(ConfigManager.get('download_setting', key)))
        except (GetUnknownKey, TypeError, ValueError):
            return default

    @staticmethod
    def _parse_hhmm(value):
        """解析 HH:MM 为 time 对象；非法返回 None（由调用方区分缺省与非法）"""
        try:
            hour, minute = str(value).split(':', 1)
            return dtime(int(hour), int(minute))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_ints(values):
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
        """
        try:
            window = cls.site_setting(website, 'download_window')
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
        logger.info("Downloader初始化")

        # 按 website 分发下载脚本（多文件来源，每次重载重新求值），未声明的传统单类兜底
        self.dispatcher = ScriptDispatcher(download_script_sources, fallback_class_name="DownloadWork")

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
        """周期性发现有待下载作品的站点，为每个站点启动独立调度线程"""
        while not self._stop_event.is_set():
            try:
                # 全局总开关关闭时不拉起任何站点
                if ConfigManager.get('download_setting', 'do_download'):
                    for website in self._pending_sites():
                        # 站点级开关关闭的站点不启动
                        if website not in self._runners and self.site_setting(website, 'do_download'):
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
        thread = Thread(target=lambda: self._site_runner(website),
                        daemon=True, name=f"DownloadSite-{website}")
        self._runners[website] = thread
        thread.start()
        logger.info(f"站点调度线程已启动: {website}")

    def _site_runner(self, website):
        pool = ThreadPool(
            max_workers=self.site_setting(website, 'download_thread'),
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
        """单个站点的下载调度循环：配置全部按站点解析，可热更新；受可下载时间窗口门控"""
        outside_logged = False
        inside_logged = False
        while not self._stop_event.is_set():
            # 站点级/全局开关关闭 → 退出本站调度线程，恢复后由守护线程重新拉起
            if not ConfigManager.get('download_setting', 'do_download') \
                    or not self.site_setting(website, 'do_download'):
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
                once_download_number = self.site_setting(website, 'once_download_number')

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
                target_interval = self.site_setting(website, 'download_interval')
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

    def _requeue_stale_downloading(self, website):
        """把该站点上次进程中断残留的 downloading 重新入队（每轮开始时调用）。"""
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
    def _work_subdir(work_number):
        """作品在站点目录下的子目录名（过滤文件系统不安全字符）。

        目录层级由调度器组装：<路径根>/<website>/<work>/，website 一层由
        调用方拼接（每站点一个目录），这里只负责作品层。
        """
        return re.sub(r'[^A-Za-z0-9_\-.]', '_', str(work_number))

    @staticmethod
    def _parse_result(result):
        """download_it 的返回值：str = 产物路径；dict = {path, duration?}"""
        if isinstance(result, dict):
            return result.get('path'), result.get('duration')
        return result, None

    def _deliver_to_final(self, cache_dir, payload, final_root, website, work_subdir):
        """cache 模式收尾：把脚本产出的数据拷贝到最终保存路径，然后清理该作品的缓存目录。

        目标层级：<final_root>/<website>/<work_subdir>/，与缓存侧层级对称。
        """
        src = payload if os.path.isabs(payload) else os.path.join(cache_dir, payload)
        if not os.path.exists(src):
            raise RuntimeError(f"脚本返回的下载路径不存在: {src}")
        dest_dir = os.path.join(final_root, website, work_subdir)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(os.path.normpath(src)))
        if os.path.isdir(src):
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)
        shutil.rmtree(cache_dir, ignore_errors=True)
        return dest

    def _run_download_task(self, work_data):
        work_number = work_data.get('workNumber')
        website = work_data.get('website')
        try:
            waiting_play = self.site_setting(website, 'waiting_play')
            sleep_second = self.site_setting(website, 'sleep_second')
            use_cache = bool(self.site_setting(website, 'use_cache'))
            final_root = self.site_setting(website, 'download_path')

            # downloadInfo 存的是该作品的统一下载参数（JSON 文本），反序列化后交给脚本
            download_info = None
            raw_info = work_data.get('downloadInfo')
            if raw_info:
                try:
                    download_info = json.loads(raw_info)
                except (TypeError, ValueError):
                    logger.warning(f"作品 {work_number}@{website} 的 downloadInfo 不是合法 JSON，已忽略")

            worker_class = self.dispatcher.get(website)
            # 目录层级：每站点一个目录（可经 download_sites.yaml 按站覆盖路径根），
            # 作品子目录由调度器组装——脚本拿到的永远是"本任务专属目录"
            work_subdir = self._work_subdir(work_number)
            if use_cache:
                # 缓存开启：脚本只看到缓存中的工作目录，产物由框架拷贝到最终路径
                cache_root = self.site_setting(website, 'cache_path')
                target_dir = os.path.join(cache_root, website, work_subdir)
            else:
                # 缓存关闭：脚本直接写最终保存目录
                target_dir = os.path.join(final_root, website, work_subdir)
            os.makedirs(target_dir, exist_ok=True)

            downloader_instance = worker_class(
                work_info=work_data,
                download_path=target_dir,
                download_info=download_info,
            )
            downloader_instance.logger = logger
            downloader_instance.config_manager = config_manager
            downloader_instance.cookie_manager = CookieManager

            result = downloader_instance.download_it()
            payload, duration = self._parse_result(result)

            if use_cache:
                if not payload:
                    raise RuntimeError("缓存模式下 download_it 必须返回下载产物路径")
                dest = self._deliver_to_final(target_dir, payload, final_root, website, work_subdir)
                logger.info(f"产物已拷贝到 {dest}")

            self._finish_work(work_number, website, success=True)
            logger.info(f"下载完成: {work_number}@{website}")

            # 任务间节奏：等待播放时优先用脚本返回的时长，否则按站点定长睡眠
            if waiting_play and isinstance(duration, (int, float)):
                self._stop_event.wait(timeout=duration)
            else:
                self._stop_event.wait(timeout=sleep_second)

        except Exception as e:
            logger.error(f"下载任务失败 {work_number}@{website}: {e}")
            try:
                self._finish_work(work_number, website, success=False)
            except Exception as finish_err:
                logger.error(f"标记下载失败状态时出错 {work_number}@{website}: {finish_err}")


downloader = Downloader()

def init():
    global downloader
    downloader.init()
