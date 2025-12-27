from flask import Blueprint, request, jsonify
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.config.config import GetUnknownKey


class GlobalApi:
    """全局配置管理 API 类"""
    
    def __init__(self):
        self.blueprint = Blueprint('global_api', __name__, url_prefix='/api/global')
        self._register_routes()
    
    def _register_routes(self):
        """注册全局配置管理相关路由"""
        
        @self.blueprint.route('/config', methods=['PUT'])
        def update_global_config():
            """更新全局配置"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 验证配置字典是否存在
                if 'global_conf' not in ConfigManager.config_dict:
                    return jsonify({
                        'success': False,
                        'error': '配置字典 global_conf 不存在'
                    }), 400
                
                # 更新配置项
                updated_keys = []
                errors = []
                
                for key, value in data.items():
                    try:
                        # 验证键是否存在
                        if key not in ConfigManager.config_dict['global_conf']:
                            errors.append(f"配置键 '{key}' 不存在")
                            continue
                        
                        # 更新配置
                        ConfigManager.set('global_conf', key, value)
                        updated_keys.append(key)
                        logger.info(f"更新全局配置: {key} = {value}")
                    except GetUnknownKey as e:
                        errors.append(str(e))
                    except Exception as e:
                        errors.append(f"更新配置 '{key}' 失败: {str(e)}")
                        logger.error(f"更新配置失败 {key}: {e}")
                
                # 返回结果
                if errors:
                    return jsonify({
                        'success': False,
                        'error': '部分配置更新失败',
                        'updated_keys': updated_keys,
                        'errors': errors
                    }), 400
                
                return jsonify({
                    'success': True,
                    'message': '配置更新成功',
                    'updated_keys': updated_keys
                }), 200
                
            except Exception as e:
                logger.error(f"更新全局配置失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'更新配置失败: {str(e)}'
                }), 500

