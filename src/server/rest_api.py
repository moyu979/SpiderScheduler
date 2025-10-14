from flask import Flask, jsonify
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.server.api import InfoApi, DownloadApi, UpdateApi

class RestApiService:
    """REST API 服务类"""
    
    def __init__(self, updater, downloader):
        logger.info("REST API 服务初始化开始")
        
        # 创建 Flask 应用
        self.app = Flask(__name__)
        self.updater = updater
        self.downloader = downloader
        
        # 获取配置
        self.host = ConfigManager.get('network', 'rest_api_host')
        self.port = ConfigManager.get('network', 'rest_api_port')
        self.debug = ConfigManager.get('global_conf', 'debug') or False
        
        # 注册所有 API 模块
        self._register_apis()
        
        # 注册全局错误处理
        self._register_error_handlers()
        
        logger.info("REST API 服务初始化完成")
    
    def _register_apis(self):
        """注册所有 API 模块"""
        # 创建 API 实例
        info_api = InfoApi()
        download_api = DownloadApi(self.downloader)
        update_api = UpdateApi(self.updater)
        
        # 注册蓝图
        self.app.register_blueprint(info_api.blueprint)
        self.app.register_blueprint(download_api.blueprint)
        self.app.register_blueprint(update_api.blueprint)
        
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
            self.app.run(
                host=self.host,
                port=self.port,
                debug=self.debug,
                threaded=True
            )
        except Exception as e:
            logger.error(f"启动 REST API 服务失败: {e}")
            raise
    
    def stop(self):
        """停止 REST API 服务"""
        logger.info("停止 REST API 服务")
        # Flask 应用没有内置的停止方法，这里只是记录日志
        # 实际停止需要通过进程管理来实现