"""站点 meta 文件 API：任意站点运行态文件的列表/读取/上传/按通配删除。

cookie（登录代理产物）归 CookieApi 管；本蓝图管站点 meta 目录
（BASEPATH/datas/meta/<website>/）里的其余文件——session、storageState、
API token 等任意字节内容，经 MetaManager 原子读写。浏览器上传入口在
前端 Cookie 页的站点行（src/server/web/index.html）。
"""

import os

from flask import Blueprint, jsonify, request, send_file

from src.utils.logging.logger import SpiderLogger as logger
from src.utils.meta import MetaFileError, MetaManager


def _err(message, code=400):
    """统一错误响应：success=False + error=message 的 JSON 与状态码。"""
    return jsonify({'success': False, 'error': message}), code


class MetaApi:
    """站点 meta 文件管理端点：列表、读取、上传、按通配删除。

    所有路径级输入（website/name/pattern）都经 MetaManager 白名单校验，
    非法即 400，杜绝路径穿越；请求体大小沿用应用级 MAX_CONTENT_LENGTH。

    Attributes:
        blueprint: 挂载全部路由的 Flask 蓝图。
    """

    def __init__(self):
        """创建蓝图并注册全部 meta 文件路由。"""
        self.blueprint = Blueprint('meta_api', __name__, url_prefix='/api/meta')
        self._register_routes()

    def _register_routes(self):
        """注册全部 meta 文件路由。"""

        @self.blueprint.route('/<website>')
        def list_files(website):
            """站点 meta 文件列表（name/size/updateTime，按文件名排序）。

            Returns:
                JSON：success 与 files；站点名非法 400。
            """
            try:
                return jsonify({'success': True, 'files': MetaManager.list_files(website)})
            except MetaFileError as e:
                return _err(str(e))
            except Exception as e:
                logger.error(f"列出 {website} 的 meta 文件失败: {e}")
                return _err(f"列出 meta 文件失败: {str(e)}", 500)

        @self.blueprint.route('/<website>/file/<name>', methods=['GET'])
        def read_file(website, name):
            """读取一个 meta 文件的原始字节。

            Returns:
                Response：文件内容；站点名/文件名非法 400、文件不存在 404。
            """
            try:
                path = MetaManager.file_path(website, name)
            except MetaFileError as e:
                return _err(str(e))
            if not os.path.exists(path):
                return _err(f"meta 文件不存在: {name}", 404)
            return send_file(path)

        @self.blueprint.route('/<website>/file/<name>', methods=['POST'])
        def save_file(website, name):
            """上传/覆盖一个 meta 文件（MetaManager 原子写）。

            请求体两种形态二选一：multipart 的 "file" 字段（前端上传），或
            原始字节 body（脚本 curl --data-binary 直传）。

            Returns:
                JSON：success 与 name/size；非法文件名 400、空请求体 400。
            """
            if 'file' in request.files:
                data = request.files['file'].read()
            else:
                data = request.get_data()
            if not data:
                return _err("请求体为空（multipart 的 file 字段或原始字节 body 二选一）")
            try:
                MetaManager.save_file(website, name, data)
            except MetaFileError as e:
                return _err(str(e))
            return jsonify({'success': True, 'name': name, 'size': len(data)})

        @self.blueprint.route('/<website>/<pattern>', methods=['DELETE'])
        def delete_files(website, pattern):
            """按通配模式删除 meta 文件（fnmatch 语义，如 cookie*；只删文件）。

            Returns:
                JSON：success、removed（是否实际删除）与 files（删除名单）；
                模式含路径分隔符等非法字符 400。
            """
            try:
                removed = MetaManager.delete(website, pattern)
            except MetaFileError as e:
                return _err(str(e))
            return jsonify({'success': True, 'removed': bool(removed), 'files': removed})
