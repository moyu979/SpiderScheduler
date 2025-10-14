"""
SpiderScheduler 后端初始化模块
负责初始化配置系统和日志系统
"""

from src.initer.init_files import init_files
def init_backend():
    """初始化后端系统"""
    # 初始化文件结构
    init_files()

    """
    # 初始化配置系统
    config_manager = init_config()

    #初始化日志系统
    logger.init_log()
    
    # 初始化数据库
    db_manager.init_database()

    backend_manager = BackendManager()

    # 记录初始化完成日志
    logger.info("初始化后端系统完成")

    return backend_manager
    """

    return None

