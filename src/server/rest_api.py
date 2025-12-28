import threading
from typing import Optional
from flask import Flask, jsonify
from werkzeug.serving import make_server
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.server.apis.download_api import DownloadApi
from src.server.apis.global_api import GlobalApi
from src.server.apis.update_api import UpdateApi
from src.server.apis.network_api import NetworkApi

class RestApiService:
    """REST API 服务类"""
    
    def __init__(self):
        logger.info("REST API 服务初始化开始")
        
        # 创建 Flask 应用
        self.app = Flask(__name__)
        
        # 获取配置
        self.host = ConfigManager.get('network', 'rest_api_host')
        self.port = ConfigManager.get('network', 'rest_api_port')
        self.debug = ConfigManager.get('global_conf', 'debug') or False
        
        # 服务器实例（用于优雅关闭）
        self._server = None
        
        # 注册所有 API 模块
        self._register_apis()
        
        # 注册全局错误处理
        self._register_error_handlers()
        
        logger.info("REST API 服务初始化完成")
    
    def _register_apis(self):
        """注册所有 API 模块"""
        # 创建 API 实例
        download_api = DownloadApi()
        global_api = GlobalApi()
        update_api = UpdateApi()
        network_api = NetworkApi()
        
        # 注册蓝图
        self.app.register_blueprint(download_api.blueprint)
        self.app.register_blueprint(global_api.blueprint)
        self.app.register_blueprint(update_api.blueprint)
        self.app.register_blueprint(network_api.blueprint)
        
        logger.info("所有 API 模块已注册")
    
    def _register_error_handlers(self):
        """注册全局错误处理器"""
        
        @self.app.errorhandler(404)
        def not_found(error):
            return jsonify({
                'success': False,
                'error': 'API 端点不存在',
                'code': 404
            }), 404
        
        @self.app.errorhandler(405)
        def method_not_allowed(error):
            return jsonify({
                'success': False,
                'error': 'HTTP 方法不允许',
                'code': 405
            }), 405
        
        @self.app.errorhandler(500)
        def internal_error(error):
            logger.error(f"服务器内部错误: {error}")
            return jsonify({
                'success': False,
                'error': '服务器内部错误',
                'code': 500
            }), 500
        
        @self.app.errorhandler(Exception)
        def handle_exception(e):
            logger.error(f"未处理的异常: {e}")
            return jsonify({
                'success': False,
                'error': '服务器内部错误',
                'code': 500
            }), 500
    
    def start(self):
        """启动 REST API 服务"""
        try:
            logger.info(f"启动 REST API 服务: {self.host}:{self.port}")
            # 使用 Werkzeug 服务器，可以优雅关闭
            self._server = make_server(
                self.host,
                self.port,
                self.app,
                threaded=True
            )
            self._server.serve_forever()
        except Exception as e:
            logger.error(f"启动 REST API 服务失败: {e}")
            raise
    
    def stop(self):
        """停止 REST API 服务"""
        if self._server:
            logger.info("正在停止 REST API 服务...")
            try:
                self._server.shutdown()
                logger.info("REST API 服务已停止")
            except Exception as e:
                logger.error(f"停止 REST API 服务时出错: {e}")
        else:
            logger.warning("REST API 服务未运行，无需停止")



# ==================== 全局实例 ====================
# 在文件底部定义全局实例，方便其他模块导入使用

rest_api: Optional[RestApiService] = None


def init(run_in_background: bool = True):
    """
    初始化并启动 REST API 服务器
    
    Args:
        run_in_background: 是否在后台线程运行，默认 True
    
    使用示例:
        from src.server.rest_api import init
        init()  # 后台运行
    """
    global rest_api
    
    # 检查是否已经初始化
    if rest_api is not None:
        logger.warning("REST API 服务已经初始化，跳过重复初始化")
        return
    
    # 创建 REST API 服务实例
    rest_api = RestApiService()
    
    # 启动服务器
    if run_in_background:
        # 在后台线程运行
        thread = threading.Thread(
            target=rest_api.start,
            daemon=True,
            name="RestApiServer"
        )
        thread.start()
        logger.info("REST API 服务器已在后台线程启动")
    else:
        # 阻塞运行
        rest_api.start()