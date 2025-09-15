
#这是下载功能的一个模板，需要重写download_it方法，功能为下载self.work_id对应的作品
from abc import ABC, abstractmethod
import time
import os
import random
from typing import Optional, Dict, Any
from ..utils.logger import logger
from ..utils.config import get_download_setting, get_path
from ..utils.exceptions import DownloadError

class DownloadWork(ABC):
    def __init__(self, work_id):
        self.work_id = work_id
        self.download_path = get_download_setting('DOWNLOAD_PATH')
        self.cache_path = get_download_setting('CACHE_PATH')
        self.use_cache = get_download_setting('use_cache')
        logger.info(f"初始化下载任务，作品ID: {self.work_id}")

    @abstractmethod
    def download_it(self, path: Optional[str] = None) -> Dict[str, Any]:
        """
        下载指定的作品
        
        Args:
            path: 下载路径，如果为None则使用默认路径
            
        Returns:
            Dict包含下载结果信息
            
        Raises:
            DownloadError: 下载失败时抛出
        """
        logger.info(f"开始下载作品 {self.work_id}")
        
        # 使用指定的路径或默认路径
        download_path = path if path else self.download_path
        
        # 确保下载目录存在
        if not os.path.exists(download_path):
            os.makedirs(download_path, exist_ok=True)
            logger.info(f"创建下载目录: {download_path}")
        
        # 随机睡眠时间，模拟真实的下载行为
        # 基础时间5-15秒，加上随机0-5秒的额外时间
        base_time = random.uniform(5, 15)
        extra_time = random.uniform(0, 5)
        sleep_time = base_time + extra_time
        
        logger.info(f"模拟下载中，预计耗时 {sleep_time:.1f} 秒...")
        time.sleep(sleep_time)
        
        logger.info(f"作品 {self.work_id} 下载完成")
        return {
            "status": "success",
            "work_id": self.work_id,
            "download_path": download_path,
            "download_time": sleep_time
        }
