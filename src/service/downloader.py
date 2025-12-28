import random
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.config.globalVars import download_script_path
from src.utils.dynamic_loader import load_class_from_file
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Works
from datetime import datetime
import time
from threading import Thread


class Downloader:
    """
    下载管理器
    管理下载任务，控制下载线程，处理下载间隔
    """
    def __init__(self):
        logger.info("Downloader初始化")
        
        # 动态加载DownloadWork类，用于下载任务
        self.downloader_class = load_class_from_file(download_script_path, "DownloadWork")


        # 线程池
        self.executor = ThreadPool(
            max_workers=ConfigManager.get('download_setting', 'download_thread'),
            name="DownloadThreadPool"
        )

        # 在后台线程中启动下载任务
        try:
            self._download_runner = Thread(target=lambda: self.download_loop(), daemon=True, name="DownloadScheduler")
            self._download_runner.start()
            logger.info("下载调度线程已启动")
        except Exception as e:
            logger.error(f"启动下载调度线程失败: {e}")

        logger.info("Downloader初始化完成")

    def download_loop(self):
        while True:
            # 检查下载功能是否启用
            if not ConfigManager.get('download_setting', 'do_download'):
                logger.info("下载功能已关闭，休眠中...")
                time.sleep(ConfigManager.get('download_setting', 'download_interval'))
                continue

            try:
                # 记录本轮下载开始时间
                start_time = datetime.now()
                logger.info(f"开始执行下载轮次，时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

                # 初始化下载计数
                download_count = 0
                once_download = ConfigManager.get('download_setting', 'once_download')

                # 本轮下载循环
                while True:
                    # 检查是否达到下载次数限制
                    if download_count >= once_download and once_download != -1:
                        logger.info(f"达到下载次数限制 {once_download}，本轮下载结束")
                        break

                    try:
                        # 从数据库读取一个works
                        with DatabaseManager.get_db_session() as session:
                            work = session.query(Works).first()
                            if not work:
                                logger.info("没有可下载的作品，本轮下载结束")
                                break

                            # 转换为字典
                            work_dict = {
                                'workNumber': work.workNumber,
                                'upTime': work.upTime,
                                'title': work.title,
                                'kind': work.kind,
                                'state': work.state,
                                'downloadDate': work.downloadDate,
                                'downloadPriority': work.downloadPriority,
                            }

                        # 包装下载任务
                        def download_task(work_data):
                            try:
                                # 获取下载相关配置
                                download_path = ConfigManager.get('download_setting', 'download_path')
                                cache_path = ConfigManager.get('download_setting', 'cache_path')
                                use_cache = ConfigManager.get('download_setting', 'use_cache')
                                waiting_play = ConfigManager.get('download_setting', 'waiting_play')
                                download_interval = ConfigManager.get('download_setting', 'download_interval')

                                # 初始化DownloadWork实例
                                downloader_instance = self.downloader_class(
                                    work_info=work_data,
                                    download_path=download_path,
                                    cache_path=cache_path,
                                    use_cache=use_cache,
                                    logger=logger
                                )

                                downloader_instance.start()

                                # 根据waiting_play决定是否在任务间休眠
                                if waiting_play:
                                    # 串行模式：等待下载间隔后再继续下一个任务
                                    time.sleep(download_interval)
                                else:
                                    # 并发模式：短暂随机休眠，避免请求过于密集
                                    time.sleep(random.uniform(0.1, 1.0))

                            except Exception as e:
                                logger.error(f"下载任务失败 {work_data.get('workNumber')}: {e}")

                        # 提交下载任务到线程池
                        self.executor.submit(download_task, work_dict)
                        download_count += 1
                        logger.info(f"提交下载任务 {download_count}: {work_dict.get('workNumber')}")

                    except Exception as e:
                        logger.error(f"处理下载任务时出错: {e}")
                        time.sleep(1)  # 短暂休眠后继续
                        continue

                # 本轮下载结束，计算下次轮次开始时间
                elapsed = (datetime.now() - start_time).total_seconds()
                target_interval = ConfigManager.get('download_setting', 'check_interval')
                remain = target_interval - elapsed

                if remain > 0:
                    logger.info(f"本轮下载耗时: {elapsed:.2f}秒，休眠 {remain:.2f}秒后开始下一轮")
                    time.sleep(remain)
                else:
                    logger.info(f"本轮下载耗时: {elapsed:.2f}秒，已超过间隔时间，立即开始下一轮")

            except Exception as e:
                logger.error(f"下载轮次异常: {e}")
                time.sleep(5)  # 异常后休眠较长时间

downloader = None

def init():
    global downloader
    downloader = Downloader()
