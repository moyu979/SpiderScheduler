"""
脚本分发器：按 website 把作品/用户路由到对应的用户脚本类
"""

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
    """从脚本源码提取 requirements 声明，返回需求字符串列表"""
    specs = []
    for match in _REQUIREMENTS_RE.finditer(text):
        for part in match.group(1).split(','):
            part = part.strip()
            if part:
                specs.append(part)
    return specs


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
    """安装脚本头部声明且尚未安装的依赖；失败仅记录，不阻断脚本加载"""
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
    加载用户脚本模块，按 website 属性在多个脚本类之间路由。

    约定：
    - 脚本里的公共类声明 `website = "站点名"`（或站点名列表）即注册到对应站点；
      同一文件可以放多个站点的类，类名不限。
    - 模块内没有任何类声明 website 时，视为传统单站点脚本，
      回退到 fallback_class_name 指定的类，并对任意 website 生效（向后兼容）。
    """

    def __init__(self, script_path: str, fallback_class_name: str):
        self.script_path = script_path
        self.fallback_class_name = fallback_class_name
        self._routes = {}  # website -> class
        self._wildcard = None
        self.load()

    def load(self):
        """（重新）加载脚本模块并建立路由表；失败时抛异常且旧路由原样保留"""
        # 加载前确保脚本头部声明的依赖已安装（脚本顶部的 import 才能成功）
        ensure_requirements(self.script_path)
        module = load_module_from_file(self.script_path)

        routes = {}
        for name in dir(module):
            if name.startswith('_'):
                continue
            obj = getattr(module, name)
            if not isinstance(obj, type):
                continue
            website = getattr(obj, 'website', None)
            if isinstance(website, str) and website.strip():
                routes[website.strip()] = obj
            elif isinstance(website, (list, tuple)):
                for site in website:
                    if isinstance(site, str) and site.strip():
                        routes[site.strip()] = obj

        # 先完整解析，最后一次性提交，保证失败时旧路由不被破坏
        wildcard = None
        if not routes:
            fallback = getattr(module, self.fallback_class_name, None)
            if not isinstance(fallback, type):
                raise AttributeError(
                    f"脚本 {self.script_path} 中既没有声明 website 的类，也找不到兜底类 '{self.fallback_class_name}'"
                )
            wildcard = fallback

        self._routes = routes
        self._wildcard = wildcard

        if routes:
            route_desc = ", ".join(f"{w} -> {c.__name__}" for w, c in sorted(routes.items()))
            logger.info(f"脚本路由表 {self.script_path}: {route_desc}")
        else:
            logger.info(f"脚本 {self.script_path} 未声明 website，使用传统单类兜底: {wildcard.__name__}")

    def snapshot(self):
        """当前路由表快照（website -> 类名），供系统 API 展示"""
        return {
            'websites': {w: c.__name__ for w, c in sorted(self._routes.items())},
            'fallback': self._wildcard.__name__ if self._wildcard else None,
        }

    def get(self, website):
        """返回适用于 website 的脚本类；未注册且无兜底时抛 ScriptRouteError"""
        if isinstance(website, str) and website in self._routes:
            return self._routes[website]
        if self._wildcard is not None:
            return self._wildcard
        available = ", ".join(sorted(self._routes)) or "无"
        raise ScriptRouteError(
            f"脚本 {self.script_path} 中没有适用于 website={website!r} 的类（可用: {available}）"
        )

    def websites(self):
        """已注册的站点列表"""
        return sorted(self._routes.keys())
