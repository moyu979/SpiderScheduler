"""
SpiderScheduler 后端初始化模块
负责初始化配置系统和日志系统
"""

from src.initer.init_file_structure import init_files
from src.utils.configs.config import init_config
import src.utils.logger.logger as logger
from src.utils.database.database import db_manager

def init_backend():
    """初始化后端系统"""
    # 初始化文件结构
    init_files()

    # 初始化配置系统
    init_config()
    
    # 初始化数据库
    db_manager.init_database()

    logger.init_log()
    
    # 记录初始化完成日志
    logger.info("初始化conf和log完成")

