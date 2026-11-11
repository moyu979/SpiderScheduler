"""REST API 服务：组装 Flask 应用并在后台线程运行。

职责：注册全部 API 蓝图、托管前端单页（/）、注册全局错误处理（含登录代理
页根相对请求的 404 救援）。使用 werkzeug make_server 以支持优雅关闭；
init(run_in_background=True) 在守护线程启动，stop() 供退出流程调用。
"""

import threading
from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.server.apis.download_api import DownloadApi
from src.server.apis.update_api import UpdateApi
from src.server.apis.query_api import QueryApi
from src.server.apis.cookie_api import CookieApi
from src.server.apis.script_api import ScriptApi
from src.server.apis.config_api import ConfigApi
from src.server.apis.website_api import WebsitesApi

class RestApiService:
    """REST API 服务。

    组装 Flask 应用：注册全部 API 蓝图、托管前端单页（/）、注册错误处理
    （含登录代理页根相对请求的 404 救援）。使用 werkzeug make_server 以支持
    优雅关闭。

    Attributes:
        app: Flask 应用实例。
        host: 监听地址（system.rest_api_host 配置项）。
        port: 监听端口（system.rest_api_port 配置项）。
        debug: 是否调试模式（system.debug 配置项，缺省 False）。
    """
    
    def __init__(self):
        """创建 Flask 应用、读取监听配置并完成全部注册。"""
        logger.info("REST API 服务初始化开始")
        
        # 创建 Flask 应用
        self.app = Flask(__name__)
        # 上传保护：脚本/表单请求体上限
        self.app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
        
        # 获取配置
        self.host = ConfigManager.get('system', 'rest_api_host')
        self.port = ConfigManager.get('system', 'rest_api_port')
        self.debug = ConfigManager.get('system', 'debug') or False
        
        # 服务器实例（用于优雅关闭）
        self._server = None
        
        # 注册所有 API 模块
        self._register_apis()

        # 托管前端单页应用
        self._register_web()

        # 注册全局错误处理
        self._register_error_handlers()

        logger.info("REST API 服务初始化完成")

    def _register_web(self):
        """托管前端单页应用（src/server/web/index.html），与 API 同源无需 CORS。"""
        web_dir = Path(__file__).resolve().parent / "web"

        @self.app.route("/")
        def index():
            """返回前端单页 index.html。"""
            return send_from_directory(web_dir, "index.html")
    
    def _register_apis(self):
        """注册所有 API 模块。"""
        # 创建 API 实例
        download_api = DownloadApi()
        update_api = UpdateApi()
        query_api = QueryApi()
        cookie_api = CookieApi()
        script_api = ScriptApi()
        config_api = ConfigApi()
        website_api = WebsitesApi()

        # 注册蓝图
        self.app.register_blueprint(download_api.blueprint)
        self.app.register_blueprint(update_api.blueprint)
        self.app.register_blueprint(query_api.blueprint)
        self.app.register_blueprint(cookie_api.blueprint)
        self.app.register_blueprint(script_api.blueprint)
        self.app.register_blueprint(config_api.blueprint)
        self.app.register_blueprint(website_api.blueprint)

        logger.info("所有 API 模块已注册")
    
    def _register_error_handlers(self):
        """注册全局错误处理器（404/405/500 与未捕获异常兜底）。"""
        
        @self.app.errorhandler(404)
        def not_found(error):
            """404 兜底：代理页来源的请求重定向回代理路径，其余返回 JSON 错误。"""
            # 登录代理页里 JS 发出的根相对请求（fetch('/x')）会落到本应用 404；
            # 若来自代理页，重定向回代理路径救回来
            referer = request.headers.get('Referer', '')
            marker = '/api/cookie/'
            if marker in referer:
                website = referer.split(marker, 1)[1].split('/', 1)[0]
                from flask import redirect
                target = f"{marker}{website}/proxy{request.path}"
                if request.query_string:
                    # 原请求的查询串必须带回，否则救援后的请求丢参数
                    target += '?' + request.query_string.decode('utf-8', errors='replace')
                return redirect(target, code=302)
            return jsonify({
                'success': False,
                'error': 'API 端点不存在',
                'code': 404
            }), 404
        
        @self.app.errorhandler(405)
        def method_not_allowed(error):
            """405 兜底：返回 JSON 错误结构。"""
            return jsonify({
                'success': False,
                'error': 'HTTP 方法不允许',
                'code': 405
            }), 405
        
        @self.app.errorhandler(500)
        def internal_error(error):
            """500 兜底：记录日志并返回 JSON 错误结构。"""
            logger.error(f"服务器内部错误: {error}")
            return jsonify({
                'success': False,
                'error': '服务器内部错误',
                'code': 500
            }), 500
        
        @self.app.errorhandler(Exception)
        def handle_exception(e):
            """未捕获异常兜底：记录日志并返回 JSON 错误结构。"""
            logger.error(f"未处理的异常: {e}")
            return jsonify({
                'success': False,
                'error': '服务器内部错误',
                'code': 500
            }), 500
    
    def start(self):
        """启动 HTTP 服务并阻塞（应在后台线程调用）。

        Raises:
            Exception: 启动失败时记录日志后原样抛出。
        """
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
        """优雅停止 HTTP 服务（等待已接受的请求处理完毕）。"""
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
    """初始化并启动 REST API 服务器。

    Args:
        run_in_background: 是否在后台线程运行，默认 True。

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