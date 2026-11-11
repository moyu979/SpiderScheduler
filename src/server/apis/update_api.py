"""发布位点管理端点：位点添加、停止/恢复追踪与更新配置更新。

全部端点挂在 /api/update 前缀下，与 REPL 的 add-pos 共用同一批模型与
配置写入路径，保证行为语义一致。
"""

from flask import Blueprint, request, jsonify
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.config.config import GetUnknownKey
from src.service.updater import updater
from src.utils.database.database import DatabaseManager
from src.utils.database.models import PublishPos
from datetime import datetime


class UpdateApi:
    """发布位点管理端点：添加、停止/恢复追踪与更新配置更新。

    Attributes:
        blueprint: 挂载全部路由的 Flask 蓝图。
    """

    def __init__(self):
        """创建蓝图并注册全部更新管理路由。"""
        self.blueprint = Blueprint('update_api', __name__, url_prefix='/api/update')
        self._register_routes()

    def _register_routes(self):
        """注册更新管理相关路由。"""
        
        # 更新更新配置
        @self.blueprint.route('/config', methods=['PUT'])
        def update_update_config():
            """更新更新配置。

            Returns:
                JSON：success 与 updated_keys；部分键失败时 400 附 errors，
                请求体为空或 update 段不存在 400，整体异常 500。
            """
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 验证配置字典是否存在
                if 'update' not in ConfigManager.config_dict:
                    return jsonify({
                        'success': False,
                        'error': '配置字典 update 不存在'
                    }), 400
                
                # 更新配置项
                updated_keys = []
                errors = []
                
                for key, value in data.items():
                    try:
                        # 验证键是否存在
                        if key not in ConfigManager.config_dict['update']:
                            errors.append(f"配置键 '{key}' 不存在")
                            continue
                        
                        # 更新配置
                        ConfigManager.set('update', key, value)
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

        # 增加一个发布位点，不知道的列先空着就行
        @self.blueprint.route('/add_pos', methods=['POST'])
        def add_pos():
            """添加发布位点。

            Returns:
                JSON：success、author_id 与 website；位点已存在或缺作者ID
                时 400，异常 500。
            """
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 获取作者ID
                author_id = data.get('authorId') or data.get('author_id') or data.get('uid')
                if not author_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少作者ID (authorId/author_id/uid)'
                    }), 400

                # 转换为字符串
                author_id = str(author_id)

                # 站点标识：与 (authorId, website) 联合主键配套，默认 pixiv，与 REPL 一致
                website = str(data.get('website') or 'pixiv').strip() or 'pixiv'

                # 使用ORM添加发布位点
                with DatabaseManager.get_db_session() as session:
                    # 检查位点是否已存在（同一 authorId 可存在于不同 website）
                    existing_pos = session.query(PublishPos).filter_by(authorId=author_id, website=website).first()
                    if existing_pos:
                        return jsonify({
                            'success': False,
                            'error': f'位点 {author_id}@{website} 已存在',
                            'author_id': author_id,
                            'website': website
                        }), 400

                    # 创建新位点
                    new_pos = PublishPos(
                        authorId=author_id,
                        website=website,
                        addTime=datetime.now().isoformat(timespec='seconds'),
                        state="inQueue"
                    )

                    # 添加到会话
                    session.add(new_pos)
                    # get_db_session 会自动提交

                logger.info(f"成功添加发布位点: {author_id}@{website}")
                return jsonify({
                    'success': True,
                    'message': '位点添加成功',
                    'author_id': author_id,
                    'website': website
                }), 201

            except Exception as e:
                logger.error(f"添加位点失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'添加位点失败: {str(e)}'
                }), 500

        # 停止对某个发布位点的追踪，通过将 state 设置为 stopped
        @self.blueprint.route('/stop_pos', methods=['POST'])
        def stop_pos():
            """停止追踪指定发布位点。

            Returns:
                JSON：success、author_id、website 与 state（stopped）；
                位点不存在 404，异常 500。
            """
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 获取作者ID
                author_id = data.get('authorId') or data.get('author_id') or data.get('uid')
                if not author_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少作者ID (authorId/author_id/uid)'
                    }), 400

                # 转换为字符串
                author_id = str(author_id)

                # 站点标识：与 (authorId, website) 联合主键配套，默认 pixiv，与 REPL 一致
                website = str(data.get('website') or 'pixiv').strip() or 'pixiv'

                # 使用ORM更新位点状态
                with DatabaseManager.get_db_session() as session:
                    # 查找位点
                    pos = session.query(PublishPos).filter_by(authorId=author_id, website=website).first()
                    if not pos:
                        return jsonify({
                            'success': False,
                            'error': f'位点 {author_id}@{website} 不存在'
                        }), 404

                    # 更新状态为 stopped
                    pos.state = "stopped"
                    # get_db_session 会自动提交

                logger.info(f"成功停止追踪位点: {author_id}@{website}")
                return jsonify({
                    'success': True,
                    'message': '位点追踪已停止',
                    'author_id': author_id,
                    'website': website,
                    'state': 'stopped'
                }), 200

            except Exception as e:
                logger.error(f"停止追踪位点失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'停止追踪位点失败: {str(e)}'
                }), 500

        # 恢复对某个发布位点的追踪（stopped -> inQueue）
        @self.blueprint.route('/resume_pos', methods=['POST'])
        def resume_pos():
            """恢复追踪指定发布位点。

            Returns:
                JSON：success、author_id、website 与 state（inQueue）；
                位点不存在 404，异常 500。
            """
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400

                # 获取作者ID
                author_id = data.get('authorId') or data.get('author_id') or data.get('uid')
                if not author_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少作者ID (authorId/author_id/uid)'
                    }), 400

                # 转换为字符串
                author_id = str(author_id)

                # 站点标识：与 (authorId, website) 联合主键配套，默认 pixiv，与 REPL 一致
                website = str(data.get('website') or 'pixiv').strip() or 'pixiv'

                # 使用ORM更新位点状态
                with DatabaseManager.get_db_session() as session:
                    # 查找位点
                    pos = session.query(PublishPos).filter_by(authorId=author_id, website=website).first()
                    if not pos:
                        return jsonify({
                            'success': False,
                            'error': f'位点 {author_id}@{website} 不存在'
                        }), 404

                    # 更新状态为 inQueue
                    pos.state = "inQueue"
                    # get_db_session 会自动提交

                logger.info(f"成功恢复追踪位点: {author_id}@{website}")
                return jsonify({
                    'success': True,
                    'message': '位点追踪已恢复',
                    'author_id': author_id,
                    'website': website,
                    'state': 'inQueue'
                }), 200

            except Exception as e:
                logger.error(f"恢复追踪位点失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'恢复追踪位点失败: {str(e)}'
                }), 500

        # 立即更新单个位点（绕过轮次调度，后台执行）
        @self.blueprint.route('/update_now', methods=['POST'])
        def update_now():
            """立即更新指定位点（后台执行，立即返回是否受理）。

            Returns:
                JSON：success 与受理结果（started/author_id/website 或
                reason）；位点不存在 404、已停止 400，异常 500。
            """
            try:
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400

                author_id = data.get('authorId') or data.get('author_id') or data.get('uid')
                website = data.get('website') or 'pixiv'
                if not author_id:
                    return jsonify({
                        'success': False,
                        'error': '缺少作者ID (authorId/author_id/uid)'
                    }), 400
                author_id = str(author_id)
                website = str(website).strip() or 'pixiv'

                result = updater.update_position_now(website, author_id)
                if not result.get("started"):
                    code = {"not_found": 404, "stopped": 400}.get(result.get("reason"), 200)
                    return jsonify({'success': False, **result}), code
                logger.info(f"立即更新已受理: {author_id}@{website}")
                return jsonify({'success': True, 'started': True,
                                'author_id': author_id, 'website': website}), 200

            except Exception as e:
                logger.error(f"立即更新失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'立即更新失败: {str(e)}'
                }), 500

        # “立即更新”状态查询（供前端轮询）
        @self.blueprint.route('/update_now/status')
        def update_now_status():
            """返回全部立即更新任务的状态快照。

            Returns:
                JSON：success 与 statuses（全部立即更新任务的快照）。
            """
            return jsonify({'success': True, 'statuses': updater.manual_status()})
