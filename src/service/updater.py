import json
import random
from datetime import datetime
from threading import Event, Lock, Thread

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from src.config.config import ConfigManager
from src.config.paths import update_script_path
from src.service.dispatcher import ScriptDispatcher
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import PublishPos, Works, Upload
from src.utils.cookie_manager import CookieManager


class Updater:
    """
    用户更新器

    每隔 update_interval 时间，检查数据库中所有未停止的发布位点，
    按 website 分发到对应的 UpdateUser 脚本，用迭代器方式检查更新。

    状态约定：
    - publish_pos.state: inQueue / stopped，停止的位点不再参与更新
    - works.state 是下载管线状态：更新器写入的新作品统一为 inQueue，
      脚本抓到的源站状态保存在 otherInfo 的 siteState 键里
    """

    def __init__(self):
        self.dispatcher = None
        self.executor = None
        self._stop_event = Event()

    def init(self):
        logger.info("Updater初始化开始")

        # 按 website 分发更新脚本，未声明 website 的传统单类作为兜底
        self.dispatcher = ScriptDispatcher(update_script_path(), fallback_class_name="UpdateUser")

        # 创建线程池
        self.executor = ThreadPool(
            max_workers=ConfigManager.get('update_setting', 'update_thread'),
            name="PosUpdater"
        )

    def start(self):
        # 启动更新线程
        try:
            self._update_runner = Thread(target=lambda: Updater.update_loop(self), daemon=True, name="UpdateScheduler")
            self._update_runner.start()
            logger.info("更新调度线程已启动")
        except Exception as e:
            logger.error(f"启动更新调度线程失败: {e}")

        logger.info("Updater初始化完成")

    def stop(self):
        """请求停止调度，并等待池内任务收尾"""
        self._stop_event.set()
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)
        logger.info("Updater 已停止")

    def update_loop(self):
        while not self._stop_event.is_set():
            if not ConfigManager.get('update_setting', 'do_update'):
                logger.info("更新功能已关闭，休眠中...")
                self._stop_event.wait(timeout=max(ConfigManager.get('update_setting', 'update_interval'), 60))
                continue
            try:
                # 1) 记录现在的时间
                start_time = datetime.now()
                logger.info(f"开始执行更新线程，时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

                # 2) 查询所有未停止的发布位点并转字典
                with DatabaseManager.get_db_session() as session:
                    positions = (
                        session.query(PublishPos)
                        .filter(or_(PublishPos.state.is_(None), PublishPos.state != 'stopped'))
                        .all()
                    )
                    pos_dicts = [{
                        "authorId": pos.authorId,
                        "website": pos.website,
                        "addTime": pos.addTime,
                    } for pos in positions]
                    logger.info(f"查询到位点数量: {len(pos_dicts)}")

                # 3) 按 website 分发并并行处理，按间隔提交
                total_positions = 0
                total_works = 0
                _counter_lock = Lock()
                once_update_number = ConfigManager.get('update_setting', 'once_update_number')

                for idx, pos in enumerate(pos_dicts, start=1):
                    if self._stop_event.is_set():
                        break
                    # 每轮更新的用户数量限制
                    if once_update_number != -1 and idx - 1 >= once_update_number:
                        logger.info(f"达到更新用户数量限制 {once_update_number}，本轮更新结束")
                        break

                    def task(pos_snapshot: dict):
                        nonlocal total_positions, total_works

                        update_user_class = self.dispatcher.get(pos_snapshot.get('website'))
                        updater_instance = update_user_class(pos_snapshot, logger)
                        updater_instance.cookie_manager = CookieManager

                        author_id = pos_snapshot.get('authorId')
                        website = pos_snapshot.get('website')
                        processed = 0

                        for item in updater_instance:
                            if self._stop_event.is_set():
                                break

                            # 1) 写 Works，忽略 PK 冲突
                            work_number = item.get('workid') or item.get('workNumber')
                            if not work_number:
                                logger.warning("遇到无效作品数据：缺少 workid/workNumber，已跳过")
                                continue

                            # 源站状态与下载管线状态分离：state 统一为 inQueue
                            site_state = item.get('state')
                            other_info = (
                                json.dumps({'siteState': site_state}, ensure_ascii=False)
                                if site_state is not None else None
                            )

                            works_data = {
                                'workNumber': work_number,
                                'website': website,
                                'upTime': item.get('upTime'),
                                'title': item.get('title'),
                                'kind': item.get('kind'),
                                'state': 'inQueue',
                                'downloadDate': item.get('downloadDate'),
                                'downloadPriority': item.get('downloadPriority'),
                                'otherInfo': other_info,
                            }

                            # 为每个作品使用独立事务
                            try:
                                with DatabaseManager.get_db_session() as session_works:
                                    session_works.add(Works(**works_data))
                                    # Works 自动提交
                            except IntegrityError:
                                # Works 已存在，按要求忽略
                                pass

                            # 2) 写 Upload，若重复则跳出迭代
                            try:
                                with DatabaseManager.get_db_session() as session_upload:
                                    session_upload.add(Upload(
                                        website=website,
                                        authorId=author_id,
                                        workNumber=work_number,
                                    ))
                                    # Upload 自动提交
                            except IntegrityError:
                                logger.info(f"位点 {author_id}@{website} 与作品 {work_number} 已存在关联，停止本位点迭代")
                                break

                            processed += 1

                        logger.info(f"位点 {author_id}@{website} 同步完成，新增作品数: {processed}")
                        # 汇总计数（线程安全）
                        with _counter_lock:
                            total_positions += 1
                            total_works += processed

                    logger.info(f"提交位点更新任务 {idx}/{len(pos_dicts)}: {pos.get('authorId')}@{pos.get('website')}")
                    self.executor.submit(task, pos)
                    # 每个用户提交后随机休眠 commit_interval 的 ±10%
                    if self._stop_event.wait(timeout=ConfigManager.get('update_setting', 'commit_interval') * random.uniform(0.9, 1.1)):
                        break

                # 循环结束后，等待所有任务完成并记录汇总
                self.executor.wait_for_completion()
                logger.info(f"本次更新汇总: 处理位点数={total_positions}, 累计作品数={total_works}")

                # 根据开始时间控制整体休眠到下次检查时间（update_interval 的 ±10%，-1 表示持续更新）
                elapsed = (datetime.now() - start_time).total_seconds()
                target = ConfigManager.get('update_setting', 'update_interval')
                if target == -1:
                    logger.info(f"本次更新耗时: {elapsed:.2f}秒，间隔为 -1，立即开始下一轮")
                else:
                    target = target * random.uniform(0.9, 1.1)
                    remain = target - elapsed
                    if remain > 0:
                        self._stop_event.wait(timeout=remain)
                    else:
                        logger.info(f"本次更新耗时: {elapsed:.2f}秒，已超过下次检查时间，不休眠")
            except Exception as e:
                logger.error(f"更新线程循环异常: {e}")
                # 简单退避，避免异常导致的忙等
                self._stop_event.wait(timeout=5)

updater = Updater()

def init():
    global updater
    updater.init()
    updater.start()
