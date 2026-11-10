"""
脚本分发器：按 website 把作品/用户路由到对应的用户脚本类

支持多文件来源：每个文件一个（或多个）站点类，路由表跨文件合并；
网站到类的映射完全由类声明的 website 属性决定。
"""

import ast
import os
import re
import subprocess
import sys
import threading
from importlib import metadata

from src.utils.dynamic_loader import load_module_from_file
from src.utils.logging.logger import SpiderLogger as logger

# 脚本头部的依赖声明：# requirements: pkg1, pkg2>=1.0 （可写多行，每行一条或多条逗号分隔）
_REQUIREMENTS_RE = re.compile(r'^\s*#\s*requirements:\s*(.+?)\s*$', re.MULTILINE | re.IGNORECASE)
# 并发重载时避免重复触发 pip
_INSTALL_LOCK = threading.Lock()


def parse_requirements(text):
    """从脚本源码提取 requirements 声明。

    匹配形如 ``# requirements: pkg1, pkg2>=1.0`` 的注释行（可多行、逗号分隔）。
    写进 docstring 内的同形文本不会被匹配（正则按行首 # 锚定）。

    Args:
        text: 脚本源码全文。

    Returns:
        list[str]: 需求字符串列表（保持声明顺序，已去空白）。
    """
    specs = []
    for match in _REQUIREMENTS_RE.finditer(text):
        for part in match.group(1).split(','):
            part = part.strip()
            if part:
                specs.append(part)
    return specs


def declared_websites(content):
    """静态解析脚本源码中各类声明的 website（不执行代码），返回站点名列表"""
    sites = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return sites
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            targets = []
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                targets = [stmt.target]
            for target in targets:
                if not (isinstance(target, ast.Name) and target.id == 'website'):
                    continue
                try:
                    value = ast.literal_eval(stmt.value)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(value, str) and value.strip():
                    sites.append(value.strip())
                elif isinstance(value, (list, tuple)):
                    sites.extend(v.strip() for v in value if isinstance(v, str) and v.strip())
    return sites


def _spec_name(spec):
    """取需求中的发行包名（去掉版本说明与环境标记）"""
    return re.split(r'[<>=!~;\[\s]', spec, maxsplit=1)[0].strip()


def _satisfied(spec):
    """需求是否已满足：未安装为不满足；装了 packaging 时校验版本约束，否则只看是否已安装"""
    name = _spec_name(spec)
    if not name:
        return True
    try:
        installed_version = metadata.version(name)
    except metadata.PackageNotFoundError:
        return False
    try:
        from packaging.requirements import Requirement
        return Requirement(spec).specifier.contains(installed_version, prereleases=True)
    except ImportError:
        return True


def ensure_requirements(script_path):
    """安装脚本头部声明且尚未安装的依赖。

    缺失检测优先使用 importlib.metadata；环境里有 packaging 时按版本约束精确
    校验，否则只按“是否已安装”判断。安装通过 ``sys.executable -m pip install``
    在锁内执行（防并发重载重复安装），超时 10 分钟。

    失败（网络/包名/版本冲突）只记录日志、不抛出——随后模块导入会以更明确的
    ImportError 暴露真实问题。

    Args:
        script_path: 脚本文件路径（读取其头部的依赖声明）。
    """
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        logger.warning(f"读取脚本依赖声明失败 {script_path}: {e}")
        return
    specs = parse_requirements(text)
    if not specs:
        return
    missing = [spec for spec in specs if not _satisfied(spec)]
    if not missing:
        logger.info(f"脚本依赖已满足: {', '.join(specs)}")
        return
    with _INSTALL_LOCK:
        # 双重检查：并发重载时避免重复安装
        missing = [spec for spec in missing if not _satisfied(spec)]
        if not missing:
            return
        logger.info(f"安装脚本声明的依赖: {', '.join(missing)}")
        try:
            proc = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', *missing],
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"安装脚本依赖超时: {', '.join(missing)}")
            return
        if proc.returncode != 0:
            logger.error(f"安装脚本依赖失败: {(proc.stderr or proc.stdout).strip()[:500]}")
            return
        logger.info(f"脚本依赖安装完成: {', '.join(missing)}")


class ScriptRouteError(Exception):
    """没有找到适用于指定 website 的脚本类"""


class ScriptDispatcher:
    """
    加载用户脚本模块（支持多文件来源），按 website 属性在多个脚本类之间路由。

    约定：
    - sources 是"返回脚本文件路径列表"的函数（或直接给 str/list），按优先级排序；
      每次load都会重新求值——新上传的文件会在重扫时被发现。
    - 脚本里的公共类声明 `website = "站点名"`（或站点名列表）即注册到对应站点；
      路由表跨文件合并：同一站点在多个文件重复声明时先加载的生效并告警。
    - 某文件内没有任何类声明 website 时，其 fallback_class_name 类可作为兜底
      （至多取第一个），对未被路由到的 website 生效（向后兼容旧单文件）。
    """

    def __init__(self, sources, fallback_class_name: str):
        """加载脚本来源并构建初始路由表（构造即完成首次 load）。

        Args:
            sources: "返回脚本文件路径列表"的函数（或直接给 str/list），
                按优先级排序；每次 load 都会重新求值。
            fallback_class_name: 文件内无 website 声明时作为兜底的类名。

        Raises:
            AttributeError: 所有来源既无 website 声明也找不到兜底类。
        """
        self.sources = sources  # callable -> list[str] | str | list[str]
        self.fallback_class_name = fallback_class_name
        self._routes = {}        # website -> class
        self._wildcard = None
        self._file_routes = {}   # path -> [website, ...]
        self.load()

    def _resolve_paths(self):
        """求值脚本文件来源并过滤不存在的路径。

        sources 为可调用对象时每次调用重新求值（新上传文件即时被发现），
        也兼容直接给 str 或 list。

        Returns:
            list[str]: 实际存在的脚本文件路径，保持来源给出的优先级顺序。
        """
        sources = self.sources() if callable(self.sources) else self.sources
        if isinstance(sources, str):
            sources = [sources]
        return [p for p in sources if p and os.path.exists(p)]

    def load(self):
        """（重新）求值文件来源并逐个加载，跨文件合并路由表；失败时旧路由原样保留"""
        paths = self._resolve_paths()
        routes, file_routes, wildcard = {}, {}, None
        for path in paths:
            # 加载前确保该文件声明的依赖已安装（脚本顶部的 import 才能成功）
            ensure_requirements(path)
            module = load_module_from_file(path)

            file_sites = {}
            for name in dir(module):
                if name.startswith('_'):
                    continue
                obj = getattr(module, name)
                if not isinstance(obj, type):
                    continue
                website = getattr(obj, 'website', None)
                if isinstance(website, str) and website.strip():
                    file_sites[website.strip()] = obj
                elif isinstance(website, (list, tuple)):
                    for site in website:
                        if isinstance(site, str) and site.strip():
                            file_sites[site.strip()] = obj

            # 跨文件合并：重复站点先到先得（来源列表即优先级）
            for site, cls in sorted(file_sites.items()):
                if site in routes:
                    logger.warning(f"站点 {site} 在 {path} 重复声明，保留先加载的 {routes[site].__name__}")
                else:
                    routes[site] = cls

            if not file_sites and wildcard is None:
                fallback = getattr(module, self.fallback_class_name, None)
                if isinstance(fallback, type):
                    wildcard = fallback
                    logger.info(f"脚本 {path} 未声明 website，作为兜底: {fallback.__name__}")

            logger.debug(f"脚本扫描 {path}: 站点 {sorted(file_sites) or '无（兜底候选）'}")
            file_routes[path] = sorted(file_sites.keys())

        if not routes and wildcard is None:
            raise AttributeError(
                f"脚本来源 {paths or '（空）'} 中既没有声明 website 的类，也找不到兜底类 '{self.fallback_class_name}'"
            )

        # 全部解析成功后一次性提交，保证失败时旧路由不被破坏
        self._routes = routes
        self._wildcard = wildcard
        self._file_routes = file_routes

        if routes:
            route_desc = ", ".join(f"{w} -> {c.__name__}" for w, c in sorted(routes.items()))
            logger.info(f"脚本路由表（{len(paths)} 个文件）: {route_desc}"
                        + (f"；兜底 {wildcard.__name__}" if wildcard else ""))

    def snapshot(self):
        """当前路由表快照（website -> 类名），供系统 API 展示"""
        return {
            'websites': {w: c.__name__ for w, c in sorted(self._routes.items())},
            'fallback': self._wildcard.__name__ if self._wildcard else None,
        }

    def sites_by_file(self):
        """每个已加载文件声明的站点列表（供上传冲突检测）"""
        return {path: list(sites) for path, sites in self._file_routes.items()}

    def get(self, website):
        """返回适用于 website 的脚本类。

        匹配顺序：精确命中路由表 → 兜底类（若存在）。

        Args:
            website: 站点名。

        Returns:
            type: 该站点对应的脚本类。

        Raises:
            ScriptRouteError: 未命中且无兜底时抛出，错误信息列出可用站点。
        """
        if isinstance(website, str) and website in self._routes:
            return self._routes[website]
        if self._wildcard is not None:
            return self._wildcard
        available = ", ".join(sorted(self._routes)) or "无"
        raise ScriptRouteError(
            f"没有适用于 website={website!r} 的脚本类（可用: {available}）"
        )

    def websites(self):
        """已注册的站点列表"""
        return sorted(self._routes.keys())
