"""路径解析模块。

所有运行时路径都基于 BASEPATH（工作目录，默认 ./docker，可由 --basepath 或
BASEPATH 环境变量覆盖）派生。其余模块一律通过本模块取路径，禁止自行拼接，
以保证“代码与数据分离、一个工作目录一份完整数据”的部署约定。

路径分组：
- 配置与脚本：config_path / 各脚本来源（含多文件分发的站点目录）；
- 运行数据：db_path / log_path / cookies_path / download 相关。
"""

import glob
import os


def base_path() -> str:
    """返回当前工作目录（BASEPATH）。

    延迟读取 config_manager.base_path，以支持启动参数与测试中的动态切换。

    Returns:
        str: 工作目录路径。
    """
    from src.config.config import config_manager
    return config_manager.base_path


def config_path() -> str:
    """配置目录（BASEPATH/confs），YAML 优先加载。"""
    return os.path.join(base_path(), "confs")


def download_script_path() -> str:
    """传统下载脚本单文件（多文件分发中优先级最高，向后兼容）。"""
    return os.path.join(base_path(), "scripts", "download_a_work.py")


def update_script_path() -> str:
    """传统更新脚本单文件（多文件分发中优先级最高，向后兼容）。"""
    return os.path.join(base_path(), "scripts", "update_a_user.py")


def download_scripts_dir() -> str:
    """多文件分发：下载脚本的站点目录（scripts/download/）。"""
    return os.path.join(base_path(), "scripts", "download")


def update_scripts_dir() -> str:
    """多文件分发：更新脚本的站点目录（scripts/update/）。"""
    return os.path.join(base_path(), "scripts", "update")


def _script_sources(legacy_path: str, scripts_dir: str) -> list:
    """按优先级收集脚本文件来源列表。

    旧的单文件在前（保持向后兼容），其后是站点目录内按文件名排序的 *.py。
    不存在的路径会被过滤。

    Args:
        legacy_path: 传统单文件路径。
        scripts_dir: 站点脚本目录。

    Returns:
        list[str]: 实际存在的脚本文件路径，按优先级排序。
    """
    files = sorted(glob.glob(os.path.join(scripts_dir, "*.py"))) if os.path.isdir(scripts_dir) else []
    return [p for p in [legacy_path, *files] if os.path.exists(p)]


def download_script_sources() -> list:
    """下载脚本的全部来源（每次调用重新扫描，供分发器热重载）。"""
    return _script_sources(download_script_path(), download_scripts_dir())


def update_script_sources() -> list:
    """更新脚本的全部来源（每次调用重新扫描，供分发器热重载）。"""
    return _script_sources(update_script_path(), update_scripts_dir())


def db_path() -> str:
    """SQLite 数据库文件（BASEPATH/datas/spider.db）。"""
    return os.path.join(base_path(), "datas", "spider.db")


def log_path() -> str:
    """日志目录（BASEPATH/datas/log，按月轮转）。"""
    return os.path.join(base_path(), "datas", "log")


def cookies_path() -> str:
    """登录 cookie 存储目录（BASEPATH/datas/cookies）。"""
    return os.path.join(base_path(), "datas", "cookies")


def download_path() -> str:
    """下载产物最终保存目录（模板中的 download_path 支持 ${BASE_PATH}）。"""
    return os.path.join(base_path(), "datas", "download")


def download_cache_path() -> str:
    """下载缓存中转目录。"""
    return os.path.join(base_path(), "datas", "download_cache")
