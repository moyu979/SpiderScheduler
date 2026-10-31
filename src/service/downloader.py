import json
import os
import random
import re
import shutil
from datetime import datetime
from threading import Event, Thread

from sqlalchemy import or_

from src.config.config import ConfigManager, config_manager
from src.config.paths import download_script_path
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

    # 站点巡检周期（秒）
    SUPERVISOR_TICK = 5

    def __init__(self):
        self.dispatcher = None
        self._stop_event = Event()
        self._runners = {}   # website -> 调度线程
        self._pools = {}     # website -> ThreadPool

    # ---------------- 站点级配置 ----------------

    @staticmethod
    def site_setting(website, key):
        """站点级下载配置：download_sites.<website>.<key> 覆盖 download_setting.<key>"""
        site_conf = (ConfigManager.config_dict.get('download_sites') or {}).get(website) or {}
        value = site_conf[key] if key in site_conf else ConfigManager.get('download_setting', key)
        if isinstance(value, str) and '${BASE_PATH}' in value:
            value = value.replace('${BASE_PATH}', str(ConfigManager.base_path))
        return value

    # ---------------- 生命周期 ----------------

    def init(self):
        logger.info("Downloader初始化")

        # 按 website 分发下载脚本，未声明 website 的传统单类作为兜底
        self.dispatcher = ScriptDispatcher(download_script_path(), fallback_class_name="DownloadWork")

        supervisor = Thread(target=lambda: self._supervisor_loop(),
                            daemon=True, name="DownloadSupervisor")
        supervisor.start()
        logger.info("下载站点巡检守护线程已启动")

    def stop(self):
        """请求停止全部站点调度，并等待各线程池任务收尾"""
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
            self._stop_event.wait(timeout=self.SUPERVISOR_TICK)

    def _pending_sites(self):
        """当前有待下载作品（inQueue/NULL）的站点集合"""
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
        """单个站点的下载调度循环：配置全部按站点解析，可热更新"""
        while not self._stop_event.is_set():
            # 站点级/全局开关关闭 → 退出本站调度线程，恢复后由守护线程重新拉起
            if not ConfigManager.get('download_setting', 'do_download') \
                    or not self.site_setting(website, 'do_download'):
                logger.info(f"站点 {website} 下载已关闭，调度线程退出")
                return

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
                        self._stop_event.wait(timeout=remain)
                    else:
                        logger.info(f"[{website}] 本轮下载耗时: {elapsed:.2f}秒，已超过间隔时间，立即开始下一轮")

            except Exception as e:
                logger.error(f"[{website}] 下载轮次异常: {e}")
                self._stop_event.wait(timeout=5)

    # ---------------- 队列操作（按站点） ----------------

    def _claim_next_work(self, website):
        """认领该站点按优先级排最前的待下载作品，认领即置为 downloading；无任务返回 None"""
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
        """任务收尾：成功置 done 并记录 downloadDate，失败置 failed；不覆盖 stopped"""
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
        """把该站点上次进程中断残留的 downloading 重新入队（每轮开始时调用）"""
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
    def _work_dir_name(website, work_number):
        """每个作品的专属目录名（过滤文件系统不安全字符）"""
        return re.sub(r'[^A-Za-z0-9_\-.]', '_', f"{website}_{work_number}")

    @staticmethod
    def _parse_result(result):
        """download_it 的返回值：str = 产物路径；dict = {path, duration?}"""
        if isinstance(result, dict):
            return result.get('path'), result.get('duration')
        return result, None

    def _deliver_to_final(self, cache_dir, payload, final_root, website, work_dir):
        """cache 模式收尾：把脚本产出的数据拷贝到最终保存路径，然后清理该作品的缓存目录"""
        src = payload if os.path.isabs(payload) else os.path.join(cache_dir, payload)
        if not os.path.exists(src):
            raise RuntimeError(f"脚本返回的下载路径不存在: {src}")
        dest_dir = os.path.join(final_root, website, work_dir)
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
            work_dir = self._work_dir_name(website, work_number)
            if use_cache:
                # 缓存开启：脚本只看到缓存中的工作目录，产物由框架拷贝到最终路径
                cache_root = self.site_setting(website, 'cache_path')
                target_dir = os.path.join(cache_root, work_dir)
            else:
                # 缓存关闭：脚本直接写最终保存目录
                target_dir = os.path.join(final_root, website, work_dir)
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
                dest = self._deliver_to_final(target_dir, payload, final_root, website, work_dir)
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
