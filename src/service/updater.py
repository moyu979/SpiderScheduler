from src.config.config import ConfigManager
from src.config.globalVars import update_script_path

from src.utils.dynamic_loader import load_class_from_file
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import User, Works, Upload
from datetime import datetime
import time
from sqlalchemy.exc import IntegrityError
import random
from threading import Lock, Thread

class Updater:
    """
    用户更新器
    每隔配置中的check_interval时间，检查数据库中所有用户的uid，
    为每个用户创建对应的update_a_user类实例，使用迭代器方式检查更新
    """
    def __init__(self):
        self.update_user_class = None
        self.executor = None
        
    def init(self):
        logger.info("Updater初始化开始")
        
        # 动态加载UpdateUser类，用于特定用户的更新
        self.update_user_class = load_class_from_file(update_script_path, "UpdateUser")
        
        # 创建线程池
        self.executor = ThreadPool(
            max_workers=ConfigManager.get('update_setting', 'update_thread'), 
            name="UserUpdater"
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

    def update_loop(self):
        while True:
            if not ConfigManager.get('update_setting', 'do_update'):
                logger.info("更新功能已关闭，休眠中...")
                time.sleep(ConfigManager.get('update_setting', 'check_interval'))
                continue
            try:
                # 1) 记录现在的时间
                start_time = datetime.now()
                logger.info(f"开始执行更新线程，时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

                # 2) 查询所有用户并转字典
                with DatabaseManager.get_db_session() as session:
                    users = session.query(User).all()
                    user_dicts = [{
                        "userId": u.userId,
                        "addTime": u.addTime,
                    } for u in users]
                    logger.info(f"查询到用户数量: {len(user_dicts)}")

                # 3) 初始化 update_user_class 并行格式化，按间隔提交
                total_users = 0
                total_works = 0
                _counter_lock = Lock()
                for idx, usr in enumerate(user_dicts, start=1):
                    
                    def task(user_snapshot: dict):
                        updater = self.update_user_class(user_snapshot,logger)

                        user_id = user_snapshot.get('userId')
                        processed = 0

                        for item in updater:
                                # 1) 写 Works，忽略 PK 冲突
                                work_number = item.get('workid') or item.get('workNumber')
                                if not work_number:
                                    logger.warning("遇到无效作品数据：缺少 workid/workNumber，已跳过")
                                    continue

                                works_data = {
                                    'workNumber': work_number,
                                    'upTime': item.get('upTime'),
                                    'title': item.get('title'),
                                    'kind': item.get('kind'),
                                    'state': item.get('state'),
                                    'downloadDate': item.get('downloadDate'),
                                    'downloadPriority': item.get('downloadPriority'),
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
                                        session_upload.add(Upload(userId=user_id, workNumber=work_number))
                                        # Upload 自动提交
                                except IntegrityError:
                                    logger.info(f"用户 {user_id} 与作品 {work_number} 已存在关联，停止本用户迭代")
                                    break

                                processed += 1

                        logger.info(f"用户 {user_id} 格式化完成，处理作品数: {processed}")
                        # 汇总计数（线程安全）
                        nonlocal total_users, total_works
                        with _counter_lock:
                            total_users += 1
                            total_works += processed

                    logger.info(f"提交用户更新任务 {idx}/{len(user_dicts)}: {usr.get('userId')}")
                    self.executor.submit(task, usr)
                    # 每个用户提交后随机休眠 commit_interval 的 ±10%
                    time.sleep(ConfigManager.get('update_setting', 'commit_interval') * random.uniform(0.9, 1.1))

                # 循环结束后，根据开始时间控制整体休眠到下次检查时间（check_interval 的 ±10%）
                # 等待所有任务完成后记录汇总
                self.executor.wait_for_completion()
                logger.info(f"本次更新汇总: 处理用户数={total_users}, 累计作品数={total_works}")
                elapsed = (datetime.now() - start_time).total_seconds()
                target = ConfigManager.get('update_setting', 'check_interval') * random.uniform(0.9, 1.1)
                remain = target - elapsed
                if remain > 0:
                    time.sleep(remain)
                else:
                    logger.info(f"本次更新耗时: {elapsed:.2f}秒，已超过下次检查时间，不休眠")
            except Exception as e:
                logger.error(f"更新线程循环异常: {e}")
                # 简单退避，避免异常导致的忙等
                time.sleep(5)

updater = Updater()

def init():
    global updater
    updater.init() 
    updater.start()