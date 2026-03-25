from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from config import config


class DownloadWork:
    config_manager = None
    logger = None
    def __init__(self, work_info, download_path, cache_path):
        """
        下载任务初始化
        
        Args:
            work_info (dict): 作品信息字典，包含以下字段：
                - workNumber (str): 作品编号，唯一标识
                - upTime (str): 上传时间
                - title (str): 作品标题
                - kind (str): 作品类型
                - state (str): 作品状态
                - downloadDate (str): 下载日期
                - downloadPriority (int): 下载优先级
            download_path (str): 下载的最终存储路径，作品文件将保存到此目录
            cache_path (str): 缓存文件夹的根目录，用于存储临时文件和缓存数据
            logger: 提供日志功能的类实例，用于记录下载过程中的日志信息
            config_manager: 提供配置功能的类实例，用于获取配置信息
        """
        # 基础骨架：仅保存必要状态，具体实现由子类完成
        pass

    def download_it(self, path: Optional[str] = None) -> Dict[str, Any]:
        """子类实现具体下载逻辑，并返回结果字典。"""
        pass
