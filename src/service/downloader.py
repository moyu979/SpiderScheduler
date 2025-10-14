from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.config.globalVars import download_script_path
from src.utils.dynamic_loader import load_class_from_file
from utils import BlockingThreadPoolExecutor


class Downloader:
    """
    下载管理器
    管理下载任务，控制下载线程，处理下载间隔
    """
    def __init__(self):
        logger.info("Downloader初始化")

        self.downloader_class = load_class_from_file(download_script_path, "DownloadWork")

        self.download_thread = ConfigManager.get('download_setting', 'download_thread')
        self.once_download = ConfigManager.get('download_setting', 'once_download')
        self.download_interval = ConfigManager.get('download_setting', 'download_interval')
        self.use_cache = ConfigManager.get('download_setting', 'use_cache')
        self.download_path = ConfigManager.get('download_setting', 'download_path')
        self.cache_path = ConfigManager.get('download_setting', 'cache_path')
        self.download_vip = ConfigManager.get('download_setting', 'download_vip')
        self.waiting_play = ConfigManager.get('download_setting', 'waiting_play')
        self.sleep_second = ConfigManager.get('download_setting', 'sleep_second')

        # 线程池
        self.executor = BlockingThreadPoolExecutor(
            max_workers=self.download_thread,
            name="DownloadThreadPool"
        )

        logger.info("Downloader初始化完成")

