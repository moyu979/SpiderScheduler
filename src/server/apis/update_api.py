from flask import Blueprint, request, jsonify
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.config.config import GetUnknownKey
from src.utils.database.database import DatabaseManager
from src.utils.database.models import User
from datetime import datetime


class UpdateApi:
    """更新管理 API 类"""
    
    def __init__(self):
        self.blueprint = Blueprint('update_api', __name__, url_prefix='/api/update')
        self._register_routes()
    
    def _register_routes(self):
        """注册更新管理相关路由"""
        
        #更新更新配置
        @self.blueprint.route('/config', methods=['PUT'])
        def update_update_config():
            """更新更新配置"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 验证配置字典是否存在
                if 'update_setting' not in ConfigManager.config_dict:
                    return jsonify({
                        'success': False,
                        'error': '配置字典 update_setting 不存在'
                    }), 400
                
                # 更新配置项
                updated_keys = []
                errors = []
                
                for key, value in data.items():
                    try:
                        # 验证键是否存在
                        if key not in ConfigManager.config_dict['update_setting']:
                            errors.append(f"配置键 '{key}' 不存在")
                            continue
                        
                        # 更新配置
                        ConfigManager.set('update_setting', key, value)
                        updated_keys.append(key)
                        logger.info(f"更新更新配置: {key} = {value}")
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
                logger.error(f"更新更新配置失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'更新配置失败: {str(e)}'
                }), 500

        #增加一个监听用户，不知道的列先空着就行
        @self.blueprint.route('/add_user', methods=['POST'])
        def add_user():
            """添加监听用户"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 获取用户ID
                user_id = data.get('userId') or data.get('user_id') or data.get('uid')
                if not user_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少用户ID (userId/user_id/uid)'
                    }), 400
                
                # 转换为字符串
                user_id = str(user_id)
                
                # 使用ORM添加用户到数据库
                with DatabaseManager.get_db_session() as session:
                    # 检查用户是否已存在
                    existing_user = session.query(User).filter_by(userId=user_id).first()
                    if existing_user:
                        return jsonify({
                            'success': False,
                            'error': f'用户 {user_id} 已存在',
                            'user_id': user_id
                        }), 400
                    
                    # 创建新用户，只设置 userId，其他字段先空着
                    new_user = User(
                        userId=user_id,
                        addTime=None  # 先空着，或者可以设置为当前时间: datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    )
                    
                    # 添加到会话
                    session.add(new_user)
                    # get_db_session 会自动提交
                
                logger.info(f"成功添加监听用户: {user_id}")
                return jsonify({
                    'success': True,
                    'message': '用户添加成功',
                    'user_id': user_id
                }), 201
                
            except Exception as e:
                logger.error(f"添加用户失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'添加用户失败: {str(e)}'
                }), 500

        #停止对某个用户的监听，通过将state设置为stopped
        @self.blueprint.route('/stop_user', methods=['POST'])
        def stop_user():
            """停止监听指定用户"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 获取用户ID
                user_id = data.get('userId') or data.get('user_id') or data.get('uid')
                if not user_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少用户ID (userId/user_id/uid)'
                    }), 400
                
                # 转换为字符串
                user_id = str(user_id)
                
                # 使用ORM更新用户状态
                with DatabaseManager.get_db_session() as session:
                    # 查找用户
                    user = session.query(User).filter_by(userId=user_id).first()
                    if not user:
                        return jsonify({
                            'success': False,
                            'error': f'用户 {user_id} 不存在'
                        }), 404
                    
                    # 更新状态为 stopped
                    user.state = "stopped"
                    # get_db_session 会自动提交
                
                logger.info(f"成功停止监听用户: {user_id}")
                return jsonify({
                    'success': True,
                    'message': '用户监听已停止',
                    'user_id': user_id,
                    'state': 'stopped'
                }), 200
                
            except Exception as e:
                logger.error(f"停止监听用户失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'停止监听用户失败: {str(e)}'
                }), 500
