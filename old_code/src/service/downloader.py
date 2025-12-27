from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.config.globalVars import download_script_path
from src.utils.dynamic_loader import load_class_from_file
from src.utils.BlockingThreadPoolExecutor import BlockingThreadPoolExecutor
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
        
        # 确保配置已加载
        if not ConfigManager.config_dict:
            logger.info("配置未加载，正在初始化配置...")
            #ConfigManager.init_config()
        
        # 动态加载DownloadWork类，用于下载任务
        self.downloader_class = load_class_from_file(download_script_path, "DownloadWork")


        # 线程池
        self.executor = BlockingThreadPoolExecutor(
            max_workers=ConfigManager.get('download_setting', 'download_thread'),
            name="DownloadThreadPool"
        )

        # 在后台线程中启动下载任务
        try:
            self._download_runner = Thread(target=lambda: self.download_thread(), daemon=True, name="DownloadScheduler")
            self._download_runner.start()
            logger.info("下载调度线程已启动")
        except Exception as e:
            logger.error(f"启动下载调度线程失败: {e}")

        logger.info("Downloader初始化完成")

    def download_thread(self):
        while True:
            try:
                # 记录下载时间
                start_time = datetime.now()
                logger.info(f"开始执行下载线程，时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # 初始化下载计数
                download_count = 0
                
                while True:
                    # 检查是否达到下载次数限制
                    once_download = ConfigManager.get('download_setting', 'once_download')
                    if download_count >= once_download and once_download != -1:
                        logger.info(f"达到下载次数限制 {once_download}，停止下载")
                        break
                    
                    # 从数据库读取一个works
                    session = DatabaseManager.SessionLocal()
                    try:
                        work = session.query(Works).first()
                        if not work:
                            logger.info("没有可下载的作品，停止下载")
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
                        
                        # 包装下载任务，包含waiting_play逻辑
                        def download_task(work_data, waiting_play_flag, download_interval):
                            # 获取下载相关配置
                            download_path = ConfigManager.get('download_setting', 'download_path')
                            cache_path = ConfigManager.get('download_setting', 'cache_path')
                            use_cache = ConfigManager.get('download_setting', 'use_cache')
                            
                            # 初始化DownloadWork实例，传递正确的参数
                            downloader_instance = self.downloader_class(
                                work_info=work_data,
                                download_path=download_path,
                                cache_path=cache_path,
                                use_cache=use_cache,
                                logger=logger
                            )
                            downloader_instance.start()
                            
                            # 根据waiting_play决定是否睡眠
                            if waiting_play_flag:
                                time.sleep(download_interval)
                            else:
                                time.sleep(download_interval)
                        
                        # 提交包装后的下载任务
                        waiting_play = ConfigManager.get('download_setting', 'waiting_play')
                        download_interval = ConfigManager.get('download_setting', 'download_interval')
                        self.executor.submit(download_task, work_dict, waiting_play, download_interval)
                        
                        download_count += 1
                        logger.info(f"提交下载任务 {download_count}: {work_dict.get('workNumber')}")
                        
                    finally:
                        session.close()
                
                # 计算下次开始时间
                elapsed = (datetime.now() - start_time).total_seconds()
                target_interval = ConfigManager.get('download_setting', 'download_interval')
                remain = target_interval - elapsed
                if remain > 0:
                    time.sleep(remain)
                    
            except Exception as e:
                logger.error(f"下载线程循环异常: {e}")
                time.sleep(5)

