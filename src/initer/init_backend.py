"""
SpiderScheduler 后端初始化模块
负责初始化配置系统和日志系统
"""

from src.initer.init_files import init_files
from src.initer.init_config import init_config
from src.initer.init_database import init_database
from src.utils.logging.logger import SpiderLogger  as logger
def init_backend():
    """初始化后端系统"""
    # 初始化文件结构
    init_files()

    # 初始化配置系统
    init_config()
    
    #初始化日志系统
    logger.init_log()

    # 初始化数据库
    init_database()

    # 记录初始化完成日志
    logger.info("初始化后端系统完成")
