"""
系统管理 API：脚本热重载/上传、配置段查看/编辑/重载

- 脚本：改完工作目录里的脚本后 POST reload 即时生效，失败时旧路由保留并返回原因；
  也可直接通过 Web 上传脚本文件（保存前做 UTF-8/语法校验，保存后自动重载对应分发器）；
- 配置：GET 列出段，raw 端点以 YAML 文本读写单个段（写盘 + 内存即时生效），
  不存在的段不允许通过 API 创建；POST reload 从文件整体重载。
"""

import os

import yaml
from flask import Blueprint, jsonify, request

from src.config.config import ConfigManager
from src.config.paths import download_script_path, update_script_path
from src.service.downloader import downloader
from src.service.updater import updater
from src.utils.logging.logger import SpiderLogger as logger

# 上传脚本的目标：kind -> (落盘文件名, 指向路径的函数)
_SCRIPT_TARGETS = {
    'download': ('download_a_work.py', download_script_path),
    'update': ('update_a_user.py', update_script_path),
}

MAX_SCRIPT_SIZE = 512 * 1024


def _err(message, code=400):
    return jsonify({'success': False, 'error': message}), code


class SystemApi:
    """系统管理 API 类"""

    def __init__(self):
        self.blueprint = Blueprint('system_api', __name__, url_prefix='/api/system')
        self._register_routes()

    def _register_routes(self):

        @self.blueprint.route('/scripts')
        def scripts_info():
            """两个分发器的当前路由表"""
            return jsonify({'success': True, 'routes': _routes_snapshot()})

        @self.blueprint.route('/scripts/reload', methods=['POST'])
        def reload_scripts():
            """重载用户脚本；失败的分发器保留旧路由并返回原因"""
            errors = []
            for name, svc in (('update', updater), ('download', downloader)):
                d = svc.dispatcher
                if d is None:
                    continue
                try:
                    d.load()
                except Exception as e:
                    logger.error(f"重载 {name} 脚本失败（保留旧路由）: {e}")
                    errors.append(f"{name}: {e}")
            routes = _routes_snapshot()
            if errors:
                return jsonify({'success': False, 'error': '；'.join(errors),
                                'routes': routes}), 400
            logger.info("用户脚本已重载")
            return jsonify({'success': True, 'routes': routes})

        @self.blueprint.route('/scripts/<kind>/source')
        def script_source(kind):
            """查看当前脚本内容"""
            if kind not in _SCRIPT_TARGETS:
                return _err(f"未知脚本类型: {kind}（可选: {', '.join(_SCRIPT_TARGETS)}）")
            path = _SCRIPT_TARGETS[kind][1]()
            if not os.path.exists(path):
                return _err(f"脚本文件不存在: {path}", 404)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return jsonify({'success': True, 'kind': kind,
                            'filename': _SCRIPT_TARGETS[kind][0], 'content': content})

        @self.blueprint.route('/scripts/upload', methods=['POST'])
        def upload_script():
            """上传脚本：语法校验 → 落盘 → 自动重载对应分发器（失败保留旧路由）"""
            kind = request.form.get('kind')
            if kind not in _SCRIPT_TARGETS:
                return _err(f"未知脚本类型: {kind}（可选: {', '.join(_SCRIPT_TARGETS)}）")
            file = request.files.get('file')
            if file is None or not file.filename:
                return _err("缺少上传文件（multipart 字段名 file）")
            raw = file.read()
            if len(raw) > MAX_SCRIPT_SIZE:
                return _err(f"脚本过大（上限 {MAX_SCRIPT_SIZE // 1024} KB）")
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                return _err("脚本必须是 UTF-8 编码的文本文件")

            filename, path_fn = _SCRIPT_TARGETS[kind]
            try:
                compile(content, filename, 'exec')
            except SyntaxError as e:
                return _err(f"脚本语法错误，未保存: {e}")

            path = path_fn()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"已通过系统 API 上传脚本 {path}（{len(content)} 字符）")

            # 上传即重载：失败时文件已保存、旧路由继续生效
            svc = downloader if kind == 'download' else updater
            d = svc.dispatcher
            reload_result = {'ok': True}
            if d is not None:
                try:
                    d.load()
                    reload_result['snapshot'] = d.snapshot()
                except Exception as e:
                    logger.error(f"上传 {kind} 脚本后重载失败（保留旧路由）: {e}")
                    reload_result = {'ok': False, 'error': str(e), 'snapshot': d.snapshot()}
            return jsonify({'success': True, 'kind': kind,
                            'saved_path': path, 'reload': reload_result})

        @self.blueprint.route('/config')
        def config_sections():
            """列出全部配置段名"""
            with ConfigManager._config_lock:
                names = sorted(ConfigManager.config_dict.keys())
            return jsonify({'success': True, 'sections': names})

        @self.blueprint.route('/config/<name>/raw')
        def config_section_raw(name):
            """以 YAML 文本读取单个配置段"""
            with ConfigManager._config_lock:
                data = ConfigManager.config_dict.get(name)
                if data is None:
                    return _err(f"配置段不存在: {name}", 404)
            content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                                     default_flow_style=False)
            return jsonify({'success': True, 'name': name, 'content': content})

        @self.blueprint.route('/config/<name>/raw', methods=['PUT'])
        def save_section_raw(name):
            """以 YAML 文本整体替换单个配置段（写盘 + 内存即时生效）"""
            body = request.get_json(silent=True) or {}
            if 'content' not in body:
                return _err('请求体需包含 content 字段（YAML 文本）')
            try:
                data = yaml.safe_load(body['content'])
            except yaml.YAMLError as e:
                return _err(f"YAML 解析失败: {e}")
            try:
                ConfigManager.replace_section(name, data)
            except KeyError as e:
                return _err(str(e), 404)
            except ValueError as e:
                return _err(str(e))
            except Exception as e:
                logger.error(f"保存配置段 {name} 失败: {e}")
                return _err(f"保存失败: {str(e)}", 500)
            logger.info(f"配置段 {name} 已通过系统 API 更新")
            return jsonify({'success': True, 'name': name})

        @self.blueprint.route('/config/reload', methods=['POST'])
        def reload_config():
            """从配置文件整体重载（等效等待一次热重载周期）"""
            try:
                ConfigManager.load_all_configs()
                return jsonify({'success': True})
            except Exception as e:
                logger.error(f"重载配置失败: {e}")
                return _err(f"重载配置失败: {str(e)}", 500)


def _routes_snapshot():
    return {
        'update': updater.dispatcher.snapshot() if updater.dispatcher else {'initialized': False},
        'download': downloader.dispatcher.snapshot() if downloader.dispatcher else {'initialized': False},
    }
