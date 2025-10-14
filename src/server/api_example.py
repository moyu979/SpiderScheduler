#!/usr/bin/env python3
"""
REST API 服务器启动示例
"""

from src.server.rest_api import RestApiService
from src.service.downloader import Downloader
from src.service.updater import Updater
from src.config.config import ConfigManager
from src.utils.logging.logger import SpiderLogger as logger

def main():
    """主函数"""
    try:
        # 初始化配置
        ConfigManager.init_config()
        
        # 创建服务实例
        downloader = Downloader()
        updater = Updater()
        
        # 创建并启动 REST API 服务
        api_service = RestApiService(updater, downloader)
        api_service.start()
        
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务...")
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        raise

if __name__ == "__main__":
    main()
