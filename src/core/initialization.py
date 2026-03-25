# src/initer/init.py (或 src/core/initialization.py)

"""
系统初始化模块
负责初始化所有基础设施：文件、配置、日志、数据库
"""

from pathlib import Path
import shutil
from src.config.config import config_manager

from src.utils.database.database import DatabaseManager
from src.utils.logging.logger import SpiderLogger as logger
from src.server.rest_api import init as init_rest_api
from src.service.updater import init as init_updater
from src.service.downloader import init as init_downloader

def init_files() -> None:
    """初始化工作目录结构"""
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    docker_dir = Path(config_manager.base_path)
    
    if not assets_dir.exists():
        raise FileNotFoundError("模板目录不存在")
    
    docker_dir.mkdir(parents=True, exist_ok=True)
    
    for source_path in assets_dir.rglob("*"):
        relative_path = source_path.relative_to(assets_dir)
        target_path = docker_dir / relative_path
        
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            if not target_path.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)


def init():
    """初始化后端系统 - 统一入口"""
    # 1. 初始化文件结构
    init_files()
    
    # 2. 初始化配置系统
    config_manager.init_config()
    
    # 3. 初始化日志系统
    logger.init_log()
    
    # 4. 初始化数据库
    logger.info("开始初始化数据库")
    DatabaseManager.init_database()
    
    # 5. 初始化REST API服务
    init_rest_api()

    # 6. 初始化更新器
    # init_updater()

    # 7. 初始化下载器
    # init_downloader()

    # 5. 记录完成
    logger.info("初始化后端系统完成")