"""下载队列管理端点：作品入队、停止、重排与下载配置更新。

全部端点挂在 /api/download 前缀下，与 REPL 的作品操作共用同一批模型与
配置写入路径，保证行为语义一致。
"""

import json
from flask import Blueprint, request, jsonify
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Works
from src.config.config import GetUnknownKey

class DownloadApi:
    """作品/下载队列管理端点：入队、停止、重排与下载配置更新。"""
    
    def __init__(self):
        self.blueprint = Blueprint('download_api', __name__, url_prefix='/api/download')
        self._register_routes()
    
    def _register_routes(self):
        """注册下载管理相关路由"""

        #更新下载配置
        @self.blueprint.route('/config', methods=['PUT'])
        def update_download_config():
            """更新下载配置"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 验证配置字典是否存在
                if 'download' not in ConfigManager.config_dict:
                    return jsonify({
                        'success': False,
                        'error': '配置字典 download 不存在'
                    }), 400
                
                # 更新配置项
                updated_keys = []
                errors = []
                
                for key, value in data.items():
                    try:
                        # 验证键是否存在
                        if key not in ConfigManager.config_dict['download']:
                            errors.append(f"配置键 '{key}' 不存在")
                            continue
                        
                        # 更新配置
                        ConfigManager.set('download', key, value)
                        updated_keys.append(key)
                        logger.info(f"更新下载配置: {key} = {value}")
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
                logger.error(f"更新下载配置失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'更新配置失败: {str(e)}'
                }), 500
        
        #增加下载的作品，通过orm实现，将作品id直接写到数据库的works中，其他的参数先空着就行
        @self.blueprint.route('/add_work', methods=['POST'])
        def add_work():
            """添加作品到下载队列"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 获取作品ID
                work_number = data.get('workNumber') or data.get('work_number') or data.get('work_id')
                if not work_number:
                    return jsonify({
                        'success': False,
                        'error': '缺少作品ID (workNumber/work_number/work_id)'
                    }), 400
                
                # 转换为字符串
                work_number = str(work_number)

                # 站点标识：与 (workNumber, website) 联合主键配套，默认 pixiv，与 REPL 一致
                website = str(data.get('website') or 'pixiv').strip() or 'pixiv'

                # downloadInfo：统一下载参数，接受 JSON 字符串或任意可序列化对象，统一以 JSON 文本入库
                download_info = data.get('downloadInfo') or data.get('download_info')
                if isinstance(download_info, (dict, list)):
                    download_info = json.dumps(download_info, ensure_ascii=False)
                elif download_info is not None:
                    download_info = str(download_info)

                # 使用ORM添加作品到数据库
                with DatabaseManager.get_db_session() as session:
                    # 检查作品是否已存在（同一 workNumber 可存在于不同 website）
                    existing_work = session.query(Works).filter_by(workNumber=work_number, website=website).first()
                    if existing_work:
                        return jsonify({
                            'success': False,
                            'error': f'作品 {work_number}@{website} 已存在',
                            'work_number': work_number,
                            'website': website
                        }), 400

                    # 创建新作品，只设置 workNumber/website，其他字段使用默认值
                    new_work = Works(
                        workNumber=work_number,
                        website=website,
                        upTime="",
                        title=None,
                        kind=None,
                        state="inQueue",  # 默认状态为 inQueue
                        downloadDate=None,
                        downloadPriority=0,
                        downloadInfo=download_info
                    )

                    # 添加到会话
                    session.add(new_work)
                    # get_db_session 会自动提交

                logger.info(f"成功添加作品到下载队列: {work_number}@{website}")
                return jsonify({
                    'success': True,
                    'message': '作品添加成功',
                    'work_number': work_number,
                    'website': website
                }), 201
                
            except Exception as e:
                logger.error(f"添加作品失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'添加作品失败: {str(e)}'
                }), 500

        #停止下载某部作品，通过将state改为stopped
        @self.blueprint.route('/stop_work', methods=['POST'])
        def stop_work():
            """停止下载指定作品"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400
                
                # 获取作品ID
                work_number = data.get('workNumber') or data.get('work_number') or data.get('work_id')
                if not work_number:
                    return jsonify({
                        'success': False,
                        'error': '缺少作品ID (workNumber/work_number/work_id)'
                    }), 400
                
                # 转换为字符串
                work_number = str(work_number)

                # 站点标识：与 (workNumber, website) 联合主键配套，默认 pixiv，与 REPL 一致
                website = str(data.get('website') or 'pixiv').strip() or 'pixiv'

                # 使用ORM更新作品状态
                with DatabaseManager.get_db_session() as session:
                    # 查找作品
                    work = session.query(Works).filter_by(workNumber=work_number, website=website).first()
                    if not work:
                        return jsonify({
                            'success': False,
                            'error': f'作品 {work_number}@{website} 不存在'
                        }), 404

                    # 更新状态为 stopped
                    work.state = "stopped"
                    # get_db_session 会自动提交

                logger.info(f"成功停止作品下载: {work_number}@{website}")
                return jsonify({
                    'success': True,
                    'message': '作品下载已停止',
                    'work_number': work_number,
                    'website': website,
                    'state': 'stopped'
                }), 200

            except Exception as e:
                logger.error(f"停止作品下载失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'停止作品下载失败: {str(e)}'
                }), 500

        #把作品重新排回下载队列（failed/stopped/done 均可重排，重排后状态为 inQueue）
        @self.blueprint.route('/requeue_work', methods=['POST'])
        def requeue_work():
            """重新入队指定作品"""
            try:
                # 获取请求数据
                data = request.get_json()
                if not data:
                    return jsonify({
                        'success': False,
                        'error': '请求体不能为空'
                    }), 400

                # 获取作品ID
                work_number = data.get('workNumber') or data.get('work_number') or data.get('work_id')
                if not work_number:
                    return jsonify({
                        'success': False,
                        'error': '缺少作品ID (workNumber/work_number/work_id)'
                    }), 400

                # 转换为字符串
                work_number = str(work_number)

                # 站点标识：与 (workNumber, website) 联合主键配套，默认 pixiv，与 REPL 一致
                website = str(data.get('website') or 'pixiv').strip() or 'pixiv'

                # 使用ORM更新作品状态
                with DatabaseManager.get_db_session() as session:
                    # 查找作品
                    work = session.query(Works).filter_by(workNumber=work_number, website=website).first()
                    if not work:
                        return jsonify({
                            'success': False,
                            'error': f'作品 {work_number}@{website} 不存在'
                        }), 404

                    # 重新入队
                    work.state = "inQueue"
                    # get_db_session 会自动提交

                logger.info(f"作品已重新入队: {work_number}@{website}")
                return jsonify({
                    'success': True,
                    'message': '作品已重新入队',
                    'work_number': work_number,
                    'website': website,
                    'state': 'inQueue'
                }), 200

            except Exception as e:
                logger.error(f"作品重新入队失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'作品重新入队失败: {str(e)}'
                }), 500


                