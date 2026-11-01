"""配置管理 API：列出配置段、按段读写 YAML、整体重载。

配置段的写路径走 ConfigManager.replace_section（校验根节点为映射、段必须已存在、
原子写盘 + 内存即时生效），与配置系统的热重载和环境变量覆盖机制完全兼容。
"""

import yaml
from flask import Blueprint, jsonify, request

from src.config.config import ConfigManager
from src.utils.logging.logger import SpiderLogger as logger


def _err(message, code=400):
    """统一错误响应：success=False + message。"""
    return jsonify({'success': False, 'error': message}), code


class ConfigApi:
    """配置管理端点（/api/system/config*）。

    提供配置段列表、单段 YAML 读写与整体重载。不允许通过 API 创建不存在的
    配置段；写入即持久化到文件并在内存立即生效。
    """

    def __init__(self):
        self.blueprint = Blueprint('system_config_api', __name__, url_prefix='/api/system')
        self._register_routes()

    def _register_routes(self):
        """注册全部配置管理路由。"""

        @self.blueprint.route('/config')
        def config_sections():
            """列出全部已加载的配置段名。"""
            with ConfigManager._config_lock:
                names = sorted(ConfigManager.config_dict.keys())
            return jsonify({'success': True, 'sections': names})

        @self.blueprint.route('/config/<name>/raw')
        def config_section_raw(name):
            """以 YAML 文本读取单个配置段。"""
            with ConfigManager._config_lock:
                data = ConfigManager.config_dict.get(name)
                if data is None:
                    return _err(f"配置段不存在: {name}", 404)
            content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                                     default_flow_style=False)
            return jsonify({'success': True, 'name': name, 'content': content})

        @self.blueprint.route('/config/<name>/raw', methods=['PUT'])
        def save_section_raw(name):
            """以 YAML 文本整体替换单个配置段（写盘 + 内存即时生效）。"""
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
            """从配置文件整体重载（等效等待一次热重载周期）。"""
            try:
                ConfigManager.load_all_configs()
                return jsonify({'success': True})
            except Exception as e:
                logger.error(f"重载配置失败: {e}")
                return _err(f"重载配置失败: {str(e)}", 500)
