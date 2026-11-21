"""下载队列管理端点：作品入队、停止、重排、产物下载与下载配置更新。

全部端点挂在 /api/download 前缀下，与 REPL 的作品操作共用同一批模型与
配置写入路径，保证行为语义一致。
"""

import io
import json
import os
import tarfile
import urllib.parse
from queue import Empty, Full, Queue
from threading import Event, Thread

from flask import Blueprint, request, jsonify, Response
from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager
from src.service.downloader import Downloader
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Works
from src.config.config import GetUnknownKey

_TAR_DONE = object()  # 打包流的结束哨兵


def _tar_gz_stream(target, arcname):
    """把 target 打成 tar.gz 并返回逐块流式响应（不落盘、不整载内存）。

    后台线程以 tarfile 流模式（w|gz）写有界队列，请求线程的生成器逐块排空
    ——产物普遍是已压缩媒体，compresslevel 取 1 省下的 CPU 远比压缩率重要。
    客户端断开时生成器提前关闭并置 aborted，写线程 put 超时感知后虚写放行
    tar 收尾退出，不泄漏线程。

    Args:
        target: 待打包的产物目录或文件（绝对路径）。
        arcname: 归档内顶层条目名。

    Returns:
        Response: application/gzip 附件流。
    """
    q = Queue(maxsize=32)
    aborted = Event()

    class _QueueSink(io.RawIOBase):
        """tarfile 流模式的写入端：字节块塞进有界队列，塞满即背压。"""

        def writable(self):
            return True

        def write(self, b):
            data = bytes(b)
            while True:
                try:
                    q.put(data, timeout=1)
                    return len(data)
                except Full:
                    if aborted.is_set():
                        return len(data)  # 下游已断开：虚写让 tar 收尾退出

        def close(self):
            pass  # 队列生命周期由本函数管理，tarfile 关闭不落队列

    def _produce():
        try:
            with tarfile.open(fileobj=_QueueSink(), mode='w|gz', compresslevel=1) as tar:
                tar.add(target, arcname=arcname)
        except Exception as e:
            logger.warning(f"产物打包流异常: {e}")
        finally:
            for _ in range(10):
                try:
                    q.put(_TAR_DONE, timeout=1)
                    break
                except Full:
                    if aborted.is_set():
                        break  # 生成器已关闭，无人消费，直接退出

    def _generate():
        try:
            while True:
                try:
                    chunk = q.get(timeout=5)
                except Empty:
                    continue
                if chunk is _TAR_DONE:
                    return
                yield chunk
        finally:
            aborted.set()

    Thread(target=_produce, daemon=True, name='tar-stream').start()
    # 附件名取净化后的作品号（作品号可能含非 ASCII/路径不友好字符）
    safe = ''.join(c if (c.isalnum() or c in '._-') else '_' for c in str(arcname)) or 'work'
    fname = f"{safe}.tar.gz"
    return Response(_generate(), headers={
        'Content-Type': 'application/gzip',
        'Content-Disposition':
            f"attachment; filename=\"{fname}\"; filename*=UTF-8''{urllib.parse.quote(fname)}",
    })


class DownloadApi:
    """作品/下载队列管理端点：入队、停止、重排、产物 tar 下载与配置更新。

    Attributes:
        blueprint: 挂载全部路由的 Flask 蓝图。
    """

    def __init__(self):
        """创建蓝图并注册全部下载管理路由。"""
        self.blueprint = Blueprint('download_api', __name__, url_prefix='/api/download')
        self._register_routes()

    def _register_routes(self):
        """注册下载管理相关路由。"""

        # 更新下载配置
        @self.blueprint.route('/config', methods=['PUT'])
        def update_download_config():
            """更新下载配置。

            Returns:
                JSON：success 与 updated_keys；部分键失败时 400 附 errors，
                请求体为空或 download 段不存在 400，整体异常 500。
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
        
        # 增加下载的作品，通过 orm 实现，将作品 id 直接写到数据库的 works 中，
        # 其他的参数先空着就行
        @self.blueprint.route('/add_work', methods=['POST'])
        def add_work():
            """添加作品到下载队列。

            Returns:
                JSON：success、work_number 与 website；作品已存在或缺作品ID
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

        # 停止下载某部作品，通过将 state 改为 stopped
        @self.blueprint.route('/stop_work', methods=['POST'])
        def stop_work():
            """停止下载指定作品。

            Returns:
                JSON：success、work_number、website 与 state（stopped）；
                作品不存在 404，异常 500。
            """
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

        # 把作品重新排回下载队列（failed/stopped/done 均可重排，重排后状态为 inQueue）
        @self.blueprint.route('/requeue_work', methods=['POST'])
        def requeue_work():
            """重新入队指定作品。

            Returns:
                JSON：success、work_number、website 与 state（inQueue）；
                作品不存在 404，异常 500。
            """
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

        # 把已下载作品的产物打成 tar.gz 流式下发；产物被手动移走时报错但保留
        # finalPath（移回后无需任何操作即可再下），路径越界一律拒绝
        @self.blueprint.route('/work_file', methods=['GET'])
        def download_work_file():
            """下载指定作品的产物（tar.gz 流式）。

            Query:
                workNumber（或 work_number）与 website。

            Returns:
                tar.gz 附件流；缺参 400，作品不存在 / 无产物路径 / 产物被移走
                404（附说明 JSON，不动 finalPath），路径越界 404。
            """
            work_number = str(request.args.get('workNumber')
                              or request.args.get('work_number') or '').strip()
            website = str(request.args.get('website') or 'pixiv').strip() or 'pixiv'
            if not work_number:
                return jsonify({'success': False, 'error': '缺少作品ID (workNumber/work_number)'}), 400

            try:
                with DatabaseManager.get_db_session() as session:
                    work = session.get(Works, (work_number, website))
                    if work is None:
                        return jsonify({'success': False,
                                        'error': f'作品 {work_number}@{website} 不存在'}), 404
                    final_path = work.finalPath
            except Exception as e:
                logger.error(f"查询作品产物失败: {e}")
                return jsonify({'success': False, 'error': f'查询作品产物失败: {str(e)}'}), 500

            if not final_path:
                return jsonify({'success': False,
                                'error': '该作品没有已记录的产物路径（旧数据或未成功下载）'}), 404

            try:
                root = Downloader.site_download_root(website)
            except Exception as e:
                logger.error(f"解析站点下载根失败: {e}")
                return jsonify({'success': False, 'error': f'解析站点下载根失败: {str(e)}'}), 500

            target = os.path.normpath(os.path.join(root, final_path))
            # 双重越界检查：normpath 拦 .. 逃逸，realpath 拦符号链接指到下载根之外
            real_root, real_target = os.path.realpath(root), os.path.realpath(target)
            inside_norm = target == root or target.startswith(root + os.sep)
            inside_real = real_target == real_root or real_target.startswith(real_root + os.sep)
            if not (inside_norm and inside_real):
                logger.warning(f"作品 {work_number}@{website} 产物路径越界，拒绝下载: {final_path}")
                return jsonify({'success': False, 'error': '产物路径越界，拒绝访问'}), 404

            if not os.path.exists(target):
                # 用户可能手动移走：报错但不清 finalPath，移回后立即可再下
                logger.warning(f"作品 {work_number}@{website} 的产物不存在: {target}（保留 finalPath）")
                return jsonify({'success': False,
                                'error': '产物不存在（可能已被移动或删除），路径记录已保留'}), 404

            # 归档顶层：目录用作品号命名（作品子目录名由脚本自建，可能≠作品号）；
            # 单文件保持原名（保留扩展名）
            arcname = work_number if os.path.isdir(target) else os.path.basename(target)
            logger.info(f"作品 {work_number}@{website} 产物打包下载: {target}")
            return _tar_gz_stream(target, arcname)


                