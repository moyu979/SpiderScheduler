"""
运行实例管理模块
用于保存和管理全局运行实例，避免循环导入问题
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.backendManager import BackendManager
    from src.server.rest_api import RestApiService
    # 根据实际路径调整
    # from src.service.downloader import Downloader
    # from src.service.updater import Updater

# 运行实例（延迟初始化，初始值为 None）
backend_manager: Optional['BackendManager'] = None
rest_api_service: Optional['RestApiService'] = None
downloader: Optional['Downloader'] = None
updater: Optional['Updater'] = None


def init_entities():
    """
    初始化所有运行实例
    注意：需要在所有基础设施初始化完成后调用
    """
    global backend_manager, rest_api_service, downloader, updater
    
    # 延迟导入，避免循环导入
    from src.core.backendManager import BackendManager
    from src.server.rest_api import RestApiService
    # 根据实际路径调整导入
    # from src.service.downloader import Downloader
    # from src.service.updater import Updater
    
    # 创建实例
    backend_manager = BackendManager()
    downloader = backend_manager.downloader
    updater = backend_manager.updater
    rest_api_service = backend_manager.api_service if hasattr(backend_manager, 'api_service') else None


def get_backend_manager() -> 'BackendManager':
    """获取 BackendManager 实例"""
    if backend_manager is None:
        raise RuntimeError("BackendManager 未初始化，请先调用 init_entities()")
    return backend_manager


def get_rest_api_service() -> 'RestApiService':
    """获取 RestApiService 实例"""
    if rest_api_service is None:
        raise RuntimeError("RestApiService 未初始化，请先调用 init_entities()")
    return rest_api_service


def get_downloader() -> 'Downloader':
    """获取 Downloader 实例"""
    if downloader is None:
        raise RuntimeError("Downloader 未初始化，请先调用 init_entities()")
    return downloader


def get_updater() -> 'Updater':
    """获取 Updater 实例"""
    if updater is None:
        raise RuntimeError("Updater 未初始化，请先调用 init_entities()")
    return updater


# ==================== 使用示例 ====================
# 
# 方式一：直接导入实例（推荐，简洁）
# from src.core.entitys import backend_manager, downloader, updater
# 
# 使用：
# if backend_manager:
#     backend_manager.start()
# 
# 
# 方式二：使用 getter 函数（推荐，更安全）
# from src.core.entitys import get_backend_manager, get_downloader
# 
# 使用：
# backend = get_backend_manager()
# backend.start()
# 
# 
# 方式三：在初始化时导入
# from src.core.entitys import init_entities
# init_entities()  # 在 main.py 或初始化代码中调用
# 
# ====================================================

