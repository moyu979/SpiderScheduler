"""发布位点更新调度器（每站点独立调度）。

更新本质上是重新爬取目标站的页面，因此与下载一样**按站点独立限流**：每个站点
拥有独立的调度线程、线程池（update_thread）、轮间隔（update_interval）与位点间
错峰（commit_interval），互不干扰。站点级配置统一写在 update.yaml 的
`site` 结构下（键为 website，解析顺序 site.<website> > site.default > 代码
内置兜底）；根键 do_update 是全局总开关。

每轮：查询该站点全部未停止的位点，把每个位点交给按 website 分发的 UpdateUser
脚本；脚本逐条产出作品，这里负责入库（works）并建立作者↔作品关联（upload）。

增量同步语义：脚本按“从新到旧”的顺序产出作品；当某作品的 upload 关联已存在时，
视为该位点的作品流已同步到此处，立即停止本位点迭代。
"""

import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event, Lock, Thread

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from src.config.config import ConfigManager, GetUnknownKey, _UNSET
from src.config.paths import update_script_sources
from src.service.dispatcher import ScriptDispatcher
from src.service.script_tools import ScriptTools
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import PublishPos, Works, Upload
from src.utils.cookie_manager import CookieManager


class Updater:
    """发布位点更新器（每站点独立调度）。

    站点模型：守护线程周期性发现有未停止位点的站点，为每个站点启动独立的
    调度线程——各自的线程池（update_thread）、轮间隔（update_interval）、位点间
    错峰（commit_interval）与站点开关（do_update），互不干扰。站点级配置写在
    update.yaml 的 `site` 结构下（键为 website，解析顺序 site.<website> >
    site.default > 代码内置兜底）；根键 do_update 是全局总开关，站点级
    do_update 可单独关闭某站点。

    Attributes:
        dispatcher: 按 website 路由到 UpdateUser 脚本类的分发器。
        _stop_event: 停止信号；所有等待均通过它实现，保证可被 stop() 立即唤醒。
        _runners: website → 站点调度线程的注册表。
        _pools: website → 站点线程池的注册表（与 _runners 同生命周期）。
        _manual_executor: “立即更新”专用线程池（懒加载，与站点调度池解耦）。
        _manual_lock: 保护 _manual_running 的锁。
        _manual_running: 在途“立即更新”的 (website, authorId) 集合。
        _manual_status: “立即更新”结果状态表（键为 "website|authorId"）。

    状态约定：
        - publish_pos.state: inQueue / stopped，stopped 的位点不参与更新；
        - works.state 是下载管线状态：更新器写入的新作品统一为 inQueue，
          脚本抓到的源站状态保存在 otherInfo 的 siteState 键里。
    """

    # 站点巡检周期（秒）：发现有未停止位点的站点并拉起其调度线程的频率
    SUPERVISOR_TICK = 5
    # update_interval / commit_interval / page_interval 的内置默认值（配置缺失或非法时使用）
    UPDATE_INTERVAL_DEFAULT = 86400
    COMMIT_INTERVAL_DEFAULT = 5
    PAGE_INTERVAL_DEFAULT = 5

    def __init__(self):
        """初始化空的注册表、停止信号与“立即更新”登记结构。"""
        self.dispatcher = None
        self._stop_event = Event()
        self._runners = {}   # website -> 调度线程
        self._pools = {}     # website -> ThreadPool
        # “立即更新”专用：与轮次调度解耦的小执行器 + 防重复与状态登记
        self._manual_executor = None
        self._manual_lock = Lock()
        self._manual_running = set()   # {(website, authorId)}
        self._manual_status = {}       # {"website|authorId": {state, added, error, finishedAt}}

    @staticmethod
    def site_setting(website, key, default=_UNSET):
        """站点级更新配置：update.yaml 的 site.<website> > site.default > 代码兜底。

        Args:
            website: 站点名。
            key: 配置键。
            default: 全链未配置时的代码级兜底值（缺省则抛 GetUnknownKey）。

        Returns:
            解析后的配置值。
        """
        return ConfigManager.site_setting('update', website, key, default)

    @classmethod
    def _seconds(cls, website, key, default):
        """解析秒数型站点配置。

        -1 保留（表示不限/不等待），其余最小 1 秒；键缺失或非数值时用内置
        默认值，避免字符串配置在算术处抛 TypeError。

        Args:
            website: 站点名。
            key: 配置键。
            default: 配置缺失或非法时使用的内置默认值。

        Returns:
            int: 解析后的秒数（-1 或最小 1）。
        """
        try:
            value = int(cls.site_setting(website, key))
        except (GetUnknownKey, TypeError, ValueError):
            return default
        return value if value == -1 else max(1, value)

    def init(self):
        """初始化分发器（不启动调度线程，由 start() 负责）。"""
        logger.info("Updater初始化开始")

        # 按 website 分发更新脚本（多文件来源，每次重载重新求值），未声明的传统单类兜底
        self.dispatcher = ScriptDispatcher(update_script_sources, fallback_class_name="UpdateUser")

    def start(self):
        """启动站点巡检守护线程。"""
        supervisor = Thread(
            target=lambda: self._supervisor_loop(), daemon=True, name="UpdateSupervisor")
        supervisor.start()
        logger.info("更新站点巡检守护线程已启动")

    def stop(self):
        """请求停止全部站点调度，并等待各线程池任务收尾。"""
        self._stop_event.set()
        for pool in list(self._pools.values()):
            pool.shutdown(wait=True, cancel_futures=True)
        if self._manual_executor is not None:
            self._manual_executor.shutdown(wait=False, cancel_futures=True)
        logger.info("Updater 已停止")

    # ---------------- 站点巡检与站点调度线程 ----------------

    def _supervisor_loop(self):
        """周期性发现有未停止位点的站点，为每个站点启动独立调度线程。"""
        while not self._stop_event.is_set():
            try:
                # 全局总开关关闭时不拉起任何站点
                if ConfigManager.get('update', 'do_update'):
                    for website in self._update_sites():
                        # 站点级开关关闭的站点不启动（未配置视为开启）
                        if website not in self._runners and self.site_setting(website, 'do_update', True):
                            self._start_site_runner(website)
            except Exception as e:
                logger.error(f"更新站点巡检异常: {e}")
            self._stop_event.wait(timeout=self.SUPERVISOR_TICK)

    def _update_sites(self):
        """查询存在未停止位点的站点集合。

        Returns:
            set[str]: website 集合；守护线程据此拉起站点调度线程。
        """
        with DatabaseManager.get_db_session() as session:
            rows = (
                session.query(PublishPos.website)
                .filter(or_(PublishPos.state.is_(None), PublishPos.state != 'stopped'))
                .distinct()
                .all()
            )
        return {row[0] for row in rows}

    def _start_site_runner(self, website):
        """为站点启动调度线程（含站点专属线程池）。

        Args:
            website: 站点名。
        """
        thread = Thread(
            target=lambda: self._site_runner(website),
            daemon=True, name=f"UpdateSite-{website}")
        self._runners[website] = thread
        thread.start()
        logger.info(f"站点更新调度线程已启动: {website}")

    def _site_runner(self, website):
        """站点调度线程入口：装配站点专属线程池，退出时清理注册表。

        Args:
            website: 站点名。
        """
        pool = ThreadPool(
            max_workers=self.site_setting(website, 'update_thread', 1),
            name=f"Update-{website}",
        )
        self._pools[website] = pool
        try:
            self._site_loop(website, pool)
        except Exception as e:
            logger.error(f"站点 {website} 更新调度线程异常退出: {e}")
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            self._pools.pop(website, None)
            self._runners.pop(website, None)
            logger.info(f"站点更新调度线程已退出: {website}")

    def _site_loop(self, website, pool):
        """单个站点的更新调度循环：配置全部按站点解析，可热更新。

        每轮：查询该站点全部未停止的位点 → 逐位点提交线程池任务（位点间按
        commit_interval 错峰）→ 等待本轮收尾并汇总 → 按 update_interval（±10%
        抖动，-1 表示持续更新）休眠。站点级/全局开关关闭时退出本线程，
        恢复后由守护线程重新拉起。

        Args:
            website: 站点名。
            pool: 本站点专属的更新线程池。
        """
        while not self._stop_event.is_set():
            # 站点级/全局开关关闭 → 退出本站调度线程，恢复后由守护线程重新拉起
            if not ConfigManager.get('update', 'do_update') \
                    or not self.site_setting(website, 'do_update', True):
                logger.info(f"站点 {website} 更新已关闭，调度线程退出")
                return

            try:
                start_time = datetime.now()
                positions = self._pending_positions(website)
                logger.info(f"[{website}] 开始执行更新轮次: {len(positions)} 个位点")

                total_positions = 0
                total_works = 0
                counter_lock = Lock()
                commit_interval = self._seconds(website, 'commit_interval', self.COMMIT_INTERVAL_DEFAULT)

                for idx, pos in enumerate(positions, start=1):
                    if self._stop_event.is_set():
                        break

                    def task(pos_snapshot: dict):
                        """线程池任务包装：同步单个位点，并把结果计入本轮汇总。"""
                        nonlocal total_positions, total_works
                        processed = self._update_position(pos_snapshot)
                        with counter_lock:
                            total_positions += 1
                            total_works += processed

                    logger.info(f"[{website}] 提交位点更新任务 {idx}/{len(positions)}: "
                                f"{pos.get('authorId')}@{pos.get('website')}")
                    pool.submit(task, pos)
                    # 位点间错峰提交（±10% 抖动），期间可被 stop 唤醒
                    if self._stop_event.wait(timeout=commit_interval * random.uniform(0.9, 1.1)):
                        break

                # 循环结束后，等待所有任务完成并记录汇总
                pool.wait_for_completion()
                logger.info(f"[{website}] 本轮更新汇总: 处理位点数={total_positions}, "
                            f"累计作品数={total_works}")
            except Exception as e:
                logger.error(f"[{website}] 更新轮次异常: {e}")
                self._stop_event.wait(timeout=5)

            # 轮间隔（-1 表示持续更新）；每次轮末重读，配置热更新即时生效
            interval = self._seconds(website, 'update_interval', self.UPDATE_INTERVAL_DEFAULT)
            if interval == -1:
                logger.info(f"[{website}] 更新间隔为 -1，立即开始下一轮")
            else:
                jitter = interval * random.uniform(0.9, 1.1)
                logger.debug(f"[{website}] 更新轮次休眠 {jitter:.1f} 秒")
                if self._stop_event.wait(timeout=jitter):
                    return

    # ---------------- 位点查询与同步 ----------------

    def _pending_positions(self, website):
        """查询该站点全部未停止的发布位点并转为快照字典。

        Args:
            website: 站点名（只查询该站点的位点）。

        Returns:
            list[dict]: 位点快照列表，每项含 authorId / website / addTime 三个键。
        """
        with DatabaseManager.get_db_session() as session:
            positions = (
                session.query(PublishPos)
                .filter(PublishPos.website == website)
                .filter(or_(PublishPos.state.is_(None), PublishPos.state != 'stopped'))
                .all()
            )
            return [{
                "authorId": pos.authorId,
                "website": pos.website,
                "addTime": pos.addTime,
            } for pos in positions]

    def _update_position(self, pos_snapshot: dict) -> int:
        """同步单个发布位点。

        流程：按 website 分发到 UpdateUser 脚本 → 逐条产出作品 → 先查 upload 关联
        （已存在即停止本位点迭代，增量同步语义）→ 写 works（已存在则跳过）→
        建 upload 关联。脚本抛出的异常由线程池任务层捕获记录。

        Args:
            pos_snapshot: 位点快照，含 authorId / website / addTime。

        Returns:
            int: 本位点实际新增入库的作品数量。
        """
        update_user_class = self.dispatcher.get(pos_snapshot.get('website'))
        updater_instance = update_user_class(pos_snapshot, logger)
        updater_instance.cookie_manager = CookieManager
        # 运行时工具集：站点绑定的日志/登录态浏览器(自动应用代理)/扩展注册入口
        updater_instance.tools = ScriptTools(website=pos_snapshot.get('website'))
        # 翻页限速（秒）：update.yaml 的 site.<website>.page_interval（站点可覆盖，
        # 未配置回落 PAGE_INTERVAL_DEFAULT）。翻页由脚本控制，框架把解析好的值
        # 灌给脚本，脚本在两次取页之间自行等待；纯 API 站点可忽略。
        try:
            page_interval = max(0.0, float(
                self.site_setting(pos_snapshot.get('website'), 'page_interval',
                                  self.PAGE_INTERVAL_DEFAULT)))
        except (TypeError, ValueError):
            page_interval = float(self.PAGE_INTERVAL_DEFAULT)
        updater_instance.page_interval = page_interval

        author_id = pos_snapshot.get('authorId')
        website = pos_snapshot.get('website')
        processed = 0

        for item in updater_instance:
            if self._stop_event.is_set():
                break

            work_number = item.get('workid') or item.get('workNumber')
            if not work_number:
                logger.warning("遇到无效作品数据：缺少 workid/workNumber，已跳过")
                continue

            # 源站状态与下载管线状态分离：state 统一为 inQueue，源站状态进 otherInfo
            site_state = item.get('state')
            other_info = (
                json.dumps({'siteState': site_state}, ensure_ascii=False)
                if site_state is not None else None
            )

            works_data = {
                'workNumber': work_number,
                'website': website,
                # 缺省回落到与 add_work API / 模型默认一致（""/0），避免 NULL 与
                # 具体值混存导致排序、展示口径不一致
                'upTime': item.get('upTime') or '',
                'title': item.get('title'),
                'kind': item.get('kind'),
                'state': 'inQueue',
                'downloadDate': item.get('downloadDate'),
                'downloadPriority': item.get('downloadPriority') or 0,
                'otherInfo': other_info,
                # 统一下载参数：作者 + 作品号（对 bilibili 即作者 + BV 号），
                # 下载脚本经 download_info 按需取用（如按作者归档）。
                # 仅在新建作品时写入，不覆盖用户经 add_work 手工填写的参数。
                'downloadInfo': json.dumps(
                    {'authorId': author_id, 'workNumber': work_number},
                    ensure_ascii=False),
            }

            # 先查关联：已存在说明该位点已同步到这里，直接停止本位点迭代。
            # （预检代替撞 IntegrityError，避免把正常去重当成 ERROR 记日志）
            with DatabaseManager.get_db_session() as session:
                already = session.get(Upload, (website, author_id, work_number)) is not None
            if already:
                logger.info(f"位点 {author_id}@{website} 已同步到作品 {work_number}，停止本位点迭代")
                break

            # 写 works：已存在（同作品可能被其他位点先行入库）则跳过
            try:
                with DatabaseManager.get_db_session() as session_works:
                    if session_works.get(Works, (work_number, website)) is None:
                        session_works.add(Works(**works_data))
                        logger.debug(f"新作品入库: {work_number}@{website}")
                    else:
                        logger.debug(f"作品已存在，跳过入库: {work_number}@{website}")
            except IntegrityError:
                # 并发写入竞态的兜底
                logger.debug(f"并发写入已存在，跳过作品: {work_number}@{website}")

            # 建 upload 关联（正常流程此时不会重复；IntegrityError 仅为竞态兜底）
            try:
                with DatabaseManager.get_db_session() as session_upload:
                    session_upload.add(Upload(
                        website=website,
                        authorId=author_id,
                        workNumber=work_number,
                    ))
            except IntegrityError:
                logger.debug(f"并发写入已存在，跳过关联: {author_id}@{website} - {work_number}")

            processed += 1

        logger.info(f"位点 {author_id}@{website} 同步完成，新增作品数: {processed}")
        return processed

    # ---------------- 立即更新（单位点，绕过轮次调度） ----------------

    def _manual_pool(self):
        """懒加载“立即更新”专用执行器（与站点调度池解耦，站点未运行时也可用）。"""
        if self._manual_executor is None:
            self._manual_executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="UpdateNow")
        return self._manual_executor

    def update_position_now(self, website, author_id):
        """立即更新单个位点：后台执行一次 _update_position，不等待轮次调度。

        与轮次调度可能并发处理同一位点——增量同步语义（upload 关联已存在即停）
        使重复处理无害；同一“立即更新”重复点击会被在途登记挡下。

        Args:
            website: 站点名。
            author_id: 作者标识。

        Returns:
            dict: {"started": bool}；started=False 时附 reason
            （not_found / stopped / already_running）与用户可读的 error。
        """
        with DatabaseManager.get_db_session() as session:
            pos = session.get(PublishPos, (author_id, website))
            if pos is None:
                return {"started": False, "reason": "not_found",
                        "error": f"位点不存在: {author_id}@{website}"}
            if (pos.state or "inQueue") == "stopped":
                return {"started": False, "reason": "stopped",
                        "error": "位点已停止追踪，请先恢复追踪再更新"}
            snapshot = {"authorId": pos.authorId, "website": pos.website,
                        "addTime": pos.addTime}

        key = (website, author_id)
        status_key = f"{website}|{author_id}"
        with self._manual_lock:
            if key in self._manual_running:
                return {"started": False, "reason": "already_running",
                        "error": "该位点正在更新中"}
            self._manual_running.add(key)
        self._manual_status[status_key] = {"state": "running", "added": 0, "error": None}

        def _run():
            """执行单位点同步并登记结果（供前端轮询）。"""
            try:
                added = self._update_position(snapshot)
                self._manual_status[status_key] = {
                    "state": "done", "added": added, "error": None,
                    "finishedAt": datetime.now().isoformat(timespec="seconds")}
            except Exception as e:
                logger.error(f"立即更新失败 {author_id}@{website}: {e}")
                self._manual_status[status_key] = {
                    "state": "failed", "added": 0, "error": str(e),
                    "finishedAt": datetime.now().isoformat(timespec="seconds")}
            finally:
                with self._manual_lock:
                    self._manual_running.discard(key)

        self._manual_pool().submit(_run)
        logger.info(f"立即更新已提交: {author_id}@{website}")
        return {"started": True}

    def manual_status(self):
        """“立即更新”的状态快照（键为 "website|authorId"，供前端轮询）。"""
        return {k: dict(v) for k, v in self._manual_status.items()}


updater = Updater()

def init():
    """模块级初始化入口：初始化并启动全局 updater 单例。"""
    global updater
    updater.init()
    updater.start()
