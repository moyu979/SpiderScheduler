"""
动态模块加载工具
提供通用的动态加载类和函数的功能
"""

import importlib.util
import os
from typing import Any, Optional
from ..logger import logger


def load_class_from_file(file_path: str, class_name: str, module_name: Optional[str] = None) -> Any:
    """
    从指定文件路径动态加载类
    
    Args:
        file_path: 文件路径
        class_name: 要加载的类名
        module_name: 模块名称，如果为None则自动生成
        
    Returns:
        加载的类
        
    Raises:
        ImportError: 当文件不存在或类加载失败时抛出
        AttributeError: 当指定的类名不存在时抛出
    """
    try:
        # 获取绝对路径
        abs_path = os.path.abspath(file_path)
        
        # 检查文件是否存在
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"文件不存在: {abs_path}")
        
        # 生成模块名称
        if module_name is None:
            module_name = f"dynamic_module_{os.path.basename(file_path).replace('.', '_')}"
        
        # 创建模块规范
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None:
            raise ImportError(f"无法创建模块规范: {abs_path}")
        
        module = importlib.util.module_from_spec(spec)
        
        # 执行模块
        spec.loader.exec_module(module)
        
        # 检查类是否存在
        if not hasattr(module, class_name):
            available_classes = [name for name in dir(module) if not name.startswith('_')]
            raise AttributeError(f"类 '{class_name}' 不存在于模块中。可用类: {available_classes}")
        
        # 获取类
        target_class = getattr(module, class_name)
        
        logger.info(f"成功加载类 '{class_name}' 从文件: {abs_path}")
        return target_class
        
    except Exception as e:
        logger.error(f"加载类 '{class_name}' 从文件 '{file_path}' 失败: {e}")
        raise


def load_function_from_file(file_path: str, function_name: str, module_name: Optional[str] = None) -> Any:
    """
    从指定文件路径动态加载函数
    
    Args:
        file_path: 文件路径
        function_name: 要加载的函数名
        module_name: 模块名称，如果为None则自动生成
        
    Returns:
        加载的函数
        
    Raises:
        ImportError: 当文件不存在或函数加载失败时抛出
        AttributeError: 当指定的函数名不存在时抛出
    """
    try:
        # 获取绝对路径
        abs_path = os.path.abspath(file_path)
        
        # 检查文件是否存在
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"文件不存在: {abs_path}")
        
        # 生成模块名称
        if module_name is None:
            module_name = f"dynamic_module_{os.path.basename(file_path).replace('.', '_')}"
        
        # 创建模块规范
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None:
            raise ImportError(f"无法创建模块规范: {abs_path}")
        
        module = importlib.util.module_from_spec(spec)
        
        # 执行模块
        spec.loader.exec_module(module)
        
        # 检查函数是否存在
        if not hasattr(module, function_name):
            available_functions = [name for name in dir(module) if callable(getattr(module, name)) and not name.startswith('_')]
            raise AttributeError(f"函数 '{function_name}' 不存在于模块中。可用函数: {available_functions}")
        
        # 获取函数
        target_function = getattr(module, function_name)
        
        logger.info(f"成功加载函数 '{function_name}' 从文件: {abs_path}")
        return target_function
        
    except Exception as e:
        logger.error(f"加载函数 '{function_name}' 从文件 '{file_path}' 失败: {e}")
        raise


def load_module_from_file(file_path: str, module_name: Optional[str] = None) -> Any:
    """
    从指定文件路径动态加载整个模块
    
    Args:
        file_path: 文件路径
        module_name: 模块名称，如果为None则自动生成
        
    Returns:
        加载的模块
        
    Raises:
        ImportError: 当文件不存在或模块加载失败时抛出
    """
    try:
        # 获取绝对路径
        abs_path = os.path.abspath(file_path)
        
        # 检查文件是否存在
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"文件不存在: {abs_path}")
        
        # 生成模块名称
        if module_name is None:
            module_name = f"dynamic_module_{os.path.basename(file_path).replace('.', '_')}"
        
        # 创建模块规范
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None:
            raise ImportError(f"无法创建模块规范: {abs_path}")
        
        module = importlib.util.module_from_spec(spec)
        
        # 执行模块
        spec.loader.exec_module(module)
        
        logger.info(f"成功加载模块从文件: {abs_path}")
        return module
        
    except Exception as e:
        logger.error(f"加载模块从文件 '{file_path}' 失败: {e}")
        raise
