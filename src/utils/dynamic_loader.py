"""动态模块加载工具。

站点脚本（下载器/更新器）不进入 sys.modules、按文件路径直接执行模块体，
因此每次加载都会重新求值，天然支持脚本热重载。仅暴露调度器实际使用的
load_module_from_file 一个入口。
"""

import importlib.util
import os
from typing import Any, Optional

from src.utils.logging.logger import SpiderLogger as logger


def load_module_from_file(file_path: str, module_name: Optional[str] = None) -> Any:
    """从指定文件路径动态加载整个模块（不注册进 sys.modules）。

    每次调用都会重新执行模块体：新增的脚本文件在下次重扫时被发现，修改过的
    脚本在重扫后生效。模块名仅用于 traceback 展示，重名文件互不冲突。

    Args:
        file_path: 脚本文件路径。
        module_name: 模块名称，为 None 时按文件名自动生成
            （``dynamic_module_<文件名>``）。

    Returns:
        Any: 执行完成的模块对象。

    Raises:
        FileNotFoundError: 文件不存在。
        ImportError: 无法创建模块规范或模块体执行失败。
    """
    try:
        abs_path = os.path.abspath(file_path)

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"文件不存在: {abs_path}")

        if module_name is None:
            module_name = f"dynamic_module_{os.path.basename(file_path).replace('.', '_')}"

        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None:
            raise ImportError(f"无法创建模块规范: {abs_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        logger.info(f"成功加载模块从文件: {abs_path}")
        return module

    except Exception as e:
        logger.error(f"加载模块从文件 '{file_path}' 失败: {e}")
        raise
