"""脚本管理 API：路由查看、热重载、多文件上传与删除。

脚本采用多文件分发：`scripts/<kind>/<name>.py` 每站点一个文件（kind ∈ download/update），
路由跨文件合并，由 ScriptDispatcher 完成（见其模块文档）。本模块的端点只负责文件
管理与触发重扫：

- 两级冲突检测：同名文件已存在、website 与其他脚本重复 → 409 交由用户决定覆盖（force）；
- 保存/删除成功后立即重新扫描分发器，新文件即刻生效；扫描失败保留旧路由并返回原因。

注意：脚本来源列表（含传统单文件）每次重扫重新求值，因此手工放入目录的文件
也会在下一次重扫时被发现。
"""

import os
import re

from flask import Blueprint, jsonify, request

from src.config.paths import (
    download_script_path,
    download_script_sources,
    download_scripts_dir,
    update_script_path,
    update_script_sources,
    update_scripts_dir,
)
from src.service.dispatcher import declared_websites
from src.service.downloader import downloader
from src.service.updater import updater
from src.utils.logging.logger import SpiderLogger as logger

# kind -> (传统单文件名, 传统单文件路径函数, 站点目录路径函数, 来源函数)
_SCRIPT_TARGETS = {
    'download': ('download_a_work.py', download_script_path, download_scripts_dir, download_script_sources),
    'update': ('update_a_user.py', update_script_path, update_scripts_dir, update_script_sources),
}

# 单个脚本文件的体积上限
MAX_SCRIPT_SIZE = 512 * 1024

# 上传目标文件名白名单（不含 .py 后缀）
_NAME_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _err(message, code=400, **extra):
    """统一错误响应：success=False + message + 附加字段。"""
    payload = {'success': False, 'error': message}
    payload.update(extra)
    return jsonify(payload), code


def _script_target(kind, name):
    """解析脚本文件的目标路径。

    Args:
        kind: 脚本种类（download / update）。
        name: 文件名（约定不含 .py 后缀）。传统单文件名写回原位置以保持兼容，
              其余文件进入对应的站点目录。

    Returns:
        tuple[str, bool]: (目标路径, 是否为站点目录内的多文件)。
    """
    legacy_name, legacy_path_fn, dir_fn, _ = _SCRIPT_TARGETS[kind]
    if name == legacy_name.removesuffix('.py'):
        return legacy_path_fn(), False
    return os.path.join(dir_fn(), f"{name}.py"), True


def _other_declared_websites(kind, target_path, sources_fn):
    """收集除目标文件外、当前脚本来源中已声明的全部站点。

    已加载的分发器路由（sites_by_file）与磁盘上尚未加载的文件都会计入，
    用于上传时的 website 冲突检测。

    Returns:
        set[str]: 被其他文件占用的站点名集合。
    """
    d = updater.dispatcher if kind == 'update' else downloader.dispatcher
    if d is None:
        return set()
    target = os.path.abspath(target_path)
    sites = set()
    for path, declared in d.sites_by_file().items():
        if os.path.abspath(path) != target:
            sites.update(declared)
    for source in sources_fn():
        if os.path.abspath(source) != target and source not in d.sites_by_file():
            try:
                with open(source, 'r', encoding='utf-8') as f:
                    sites.update(declared_websites(f.read()))
            except OSError:
                continue
    return sites


def _rescan_dispatcher(kind):
    """重新扫描指定种类的分发器。

    Returns:
        dict: {'ok': True, 'snapshot': ...} 或 {'ok': False, 'error': ..., 'snapshot': ...}。
        重扫失败时分发器保留旧路由，调用方应把结果透传给前端提示。
    """
    d = updater.dispatcher if kind == 'update' else downloader.dispatcher
    if d is None:
        return {'ok': True}
    try:
        d.load()
        return {'ok': True, 'snapshot': d.snapshot()}
    except Exception as e:
        logger.error(f"脚本 {kind} 重新扫描失败（保留旧路由）: {e}")
        return {'ok': False, 'error': str(e), 'snapshot': d.snapshot()}


class ScriptApi:
    """脚本管理端点（/api/system/scripts*）。

    提供脚本路由表查看、热重载、多文件上传（含冲突检测与覆盖确认）、
    按文件名查看内容与删除。所有写操作完成后都会触发一次重新扫描。
    """

    def __init__(self):
        self.blueprint = Blueprint('system_script_api', __name__, url_prefix='/api/system')
        self._register_routes()

    def _register_routes(self):
        """注册全部脚本管理路由。"""

        @self.blueprint.route('/scripts')
        def scripts_info():
            """查看两个分发器的当前路由表快照。"""
            routes = {}
            for name, svc in (('update', updater), ('download', downloader)):
                d = svc.dispatcher
                routes[name] = d.snapshot() if d is not None else {'initialized': False}
            return jsonify({'success': True, 'routes': routes})

        @self.blueprint.route('/scripts/reload', methods=['POST'])
        def reload_scripts():
            """热重载两个分发器的全部脚本文件。

            单个分发器失败不影响另一个；失败者保留旧路由并在错误信息中说明。
            """
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
            routes = {}
            for name, svc in (('update', updater), ('download', downloader)):
                d = svc.dispatcher
                routes[name] = d.snapshot() if d is not None else {'initialized': False}
            if errors:
                return jsonify({'success': False, 'error': '；'.join(errors),
                                'routes': routes}), 400
            logger.info("用户脚本已重载")
            return jsonify({'success': True, 'routes': routes})

        @self.blueprint.route('/scripts/<kind>/files')
        def script_files(kind):
            """列出该类型的全部脚本文件（传统单文件 + 站点目录）及其声明的站点。"""
            if kind not in _SCRIPT_TARGETS:
                return _err(f"未知脚本类型: {kind}（可选: {', '.join(_SCRIPT_TARGETS)}）")
            legacy_name, legacy_path_fn, _, sources_fn = _SCRIPT_TARGETS[kind]
            rows = []
            for path in sources_fn():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        websites = declared_websites(f.read())
                except OSError:
                    websites = []
                name = legacy_name if os.path.abspath(path) == os.path.abspath(legacy_path_fn()) \
                    else os.path.splitext(os.path.basename(path))[0]
                rows.append({'name': name, 'path': path, 'websites': websites,
                             'legacy': name == legacy_name})
            return jsonify({'success': True, 'files': rows})

        @self.blueprint.route('/scripts/<kind>/source')
        def script_source(kind):
            """按文件名查看脚本源码（name 约定不含 .py 后缀）。"""
            if kind not in _SCRIPT_TARGETS:
                return _err(f"未知脚本类型: {kind}（可选: {', '.join(_SCRIPT_TARGETS)}）")
            name = (request.args.get('name') or '').strip().removesuffix('.py')
            if not name or not _NAME_RE.match(name):
                return _err("缺少或非法的文件名（name，仅字母/数字/下划线/连字符）")
            path, _ = _script_target(kind, name)
            if not os.path.exists(path):
                return _err(f"脚本文件不存在: {path}", 404)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return jsonify({'success': True, 'kind': kind, 'name': name, 'content': content})

        @self.blueprint.route('/scripts/upload', methods=['POST'])
        def upload_script():
            """上传脚本文件（multipart：kind + name + file [ + force ]）。

            流程：UTF-8/语法校验 → 两级冲突检测（同名文件 / website 与其他脚本重复，
            409 由用户决定覆盖）→ 落盘 → 重新扫描分发器。
            """
            kind = request.form.get('kind')
            if kind not in _SCRIPT_TARGETS:
                return _err(f"未知脚本类型: {kind}（可选: {', '.join(_SCRIPT_TARGETS)}）")
            file = request.files.get('file')
            if file is None or not file.filename:
                return _err("缺少上传文件（multipart 字段名 file）")
            # 目标保存名（决定存成 scripts/<kind>/<name>.py）：显式指定优先；
            # 留空时从上传文件名派生（取基名、去 .py、非法字符折叠为 _）。
            # 白名单只约束这个保存名——上传的 .py 文件本身不受限制。
            name = (request.form.get('name') or '').strip().removesuffix('.py')
            if not name:
                base = os.path.basename(file.filename).removesuffix('.py')
                name = re.sub(r'[^A-Za-z0-9_\-]+', '_', base).strip('_')
            if not name or not _NAME_RE.match(name):
                return _err("目标保存名（name，不含 .py）只能包含字母/数字/下划线/连字符——"
                            "上传的 .py 文件本身不受此限制；文件名含中文等字符时，"
                            "请在“文件名”输入框手动指定保存名")
            raw = file.read()
            if len(raw) > MAX_SCRIPT_SIZE:
                return _err(f"脚本过大（上限 {MAX_SCRIPT_SIZE // 1024} KB）")
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                return _err("脚本必须是 UTF-8 编码的文本文件")

            filename, legacy_path_fn, _, sources_fn = _SCRIPT_TARGETS[kind]
            try:
                compile(content, f"{name}.py", 'exec')
            except SyntaxError as e:
                return _err(f"脚本语法错误，未保存: {e}")

            path, _ = _script_target(kind, name)

            # 两级冲突检测（force=true 表示用户已确认覆盖，跳过）
            if request.form.get('force') != 'true':
                file_exists = os.path.exists(path)
                overlap = sorted(
                    set(declared_websites(content)) & _other_declared_websites(kind, path, sources_fn)
                )
                if file_exists or overlap:
                    logger.info(f"上传 {kind}/{name}.py 存在冲突（同名文件={file_exists}，"
                                f"website 重复={overlap}），等待用户决定是否覆盖")
                    return _err(
                        ("同名文件已存在；" if file_exists else "")
                        + (f"站点与其他脚本重复: {', '.join(overlap)}；" if overlap else "")
                        + "确认覆盖请带 force=true 重新提交",
                        409,
                        conflict={'fileExists': file_exists, 'websites': overlap},
                    )

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"已通过系统 API 上传脚本 {path}（{len(content)} 字符）")

            # 保存成功后立即重新扫描：新文件/覆盖即刻生效
            reload_result = _rescan_dispatcher(kind)
            return jsonify({'success': True, 'kind': kind, 'name': name,
                            'saved_path': path, 'reload': reload_result})

        @self.blueprint.route('/scripts/<kind>/<name>', methods=['DELETE'])
        def delete_script(kind, name):
            """删除指定脚本文件并重新扫描分发器。"""
            if kind not in _SCRIPT_TARGETS:
                return _err(f"未知脚本类型: {kind}（可选: {', '.join(_SCRIPT_TARGETS)}）")
            name = name.removesuffix('.py')
            if not _NAME_RE.match(name):
                return _err("非法的文件名")
            path, _ = _script_target(kind, name)
            if not os.path.exists(path):
                return _err(f"脚本文件不存在: {path}", 404)
            os.remove(path)
            logger.info(f"已删除脚本文件: {path}")

            reload_result = _rescan_dispatcher(kind)
            return jsonify({'success': True, 'removed': name, 'reload': reload_result})
