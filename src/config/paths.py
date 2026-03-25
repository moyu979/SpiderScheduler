import os

def base_path() -> str:
    # 延迟导入，避免循环依赖
    from src.config.config import config_manager
    return config_manager.base_path

def download_script_path() -> str:
    return os.path.join(base_path(), "scripts", "download_a_work.py")

def update_script_path() -> str:
    return os.path.join(base_path(), "scripts", "update_a_user.py")

def db_path() -> str:
    return os.path.join(base_path(), "datas", "spider.db")

def log_path() -> str:
    return os.path.join(base_path(), "datas", "log")

def download_path() -> str:
    return os.path.join(base_path(), "datas", "download")

def download_cache_path() -> str:
    return os.path.join(base_path(), "datas", "download_cache")

def config_path() -> str:
    return os.path.join(base_path(), "confs")