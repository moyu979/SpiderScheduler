"""
SpiderScheduler 后端初始化模块
负责初始化配置系统和日志系统
"""

from .utils.config import init_config
from .utils.logger import logger
from .utils.database import db_manager

def init_backend():
    """初始化后端系统"""
    # 初始化配置系统
    init_config()
    
    # 初始化数据库
    if db_manager.init():
        logger.info("数据库初始化成功")
    else:
        logger.error("数据库初始化失败")
    
    # 记录初始化完成日志
    logger.info("初始化conf和log完成")

if __name__ == "__main__":
    init_backend()
