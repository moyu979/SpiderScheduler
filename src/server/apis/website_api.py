"""站点入口管理端点：websites.yaml 的线上增删改查。

websites.yaml 是登录代理与脚本共用的"站点名 → 入口地址"映射。本模块把它
变成结构化的线上配置（代替手改 YAML）：新增/更新/删除统一走 ConfigManager
的原子写盘，内存即时生效，登录代理/Cookie 页/脚本随即可见。

删除带占用保护：站点仍被作品、位点或脚本路由引用时返回 409 并附占用明细，
确认删除需带 force=true——防止误删活跃站点后调度静默失联。
"""

import re

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from src.config.config import ConfigManager
from src.service.downloader import downloader
from src.service.updater import updater
from src.utils.database.database import DatabaseManager
from src.utils.database.models import PublishPos, Works
from src.utils.logging.logger import SpiderLogger as logger

# 站点名约束：会成为 cookie 文件名与 URL 路径片段
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# 入口地址必须是 http(s) 绝对地址
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def _err(message, code=400, **extra):
    """统一错误响应：success=False + message + 附加字段。"""
    payload = {"success": False, "error": message}
    payload.update(extra)
    return jsonify(payload), code


def _usage():
    """统计各站点的占用情况：{website: {works, positions, routes}}。

    routes 记录显式声明了该站点的脚本种类（download/update）；兜底路由不
    计入——兜底意味着任意站点名都会命中，删除单个入口不会使其失联。

    Returns:
        dict: 站点名 → 占用明细。
    """
    usage = {}

    with DatabaseManager.get_db_session() as session:
        for website, count in (
            session.query(Works.website, func.count(Works.workNumber))
            .group_by(Works.website).all()
        ):
            usage.setdefault(website, {"works": 0, "positions": 0, "routes": []})["works"] = count
        for website, count in (
            session.query(PublishPos.website, func.count(PublishPos.authorId))
            .group_by(PublishPos.website).all()
        ):
            usage.setdefault(website, {"positions": 0, "works": 0, "routes": []})["positions"] = count

    for kind, svc in (("download", downloader), ("update", updater)):
        d = svc.dispatcher
        if d is None:
            continue
        for website in d.websites():
            usage.setdefault(website, {"works": 0, "positions": 0, "routes": []})["routes"].append(kind)
    return usage


class WebsitesApi:
    """站点入口管理端点（/api/system/websites*）。

    提供站点列表（含占用统计）、新增/更新入口地址、带占用保护的删除。
    所有写操作即时持久化到 websites.yaml 并在内存生效。
    """

    def __init__(self):
        self.blueprint = Blueprint("system_website_api", __name__, url_prefix="/api/system")
        self._register_routes()

    def _register_routes(self):
        """注册全部站点管理路由。"""

        @self.blueprint.route("/websites")
        def list_websites():
            """列出全部站点入口与占用统计。"""
            with ConfigManager._config_lock:
                sites = dict(ConfigManager.config_dict.get("websites") or {})
            return jsonify({"success": True, "sites": sites, "usage": _usage()})

        @self.blueprint.route("/websites/<name>", methods=["PUT"])
        def put_website(name):
            """新增或更新站点入口地址。

            Body: {"url": "https://..."}；站点名会成为 cookie 文件名与 URL
            片段，仅允许字母/数字/下划线/连字符。
            """
            name = name.strip()
            if not _NAME_RE.match(name):
                return _err("站点名只能包含字母/数字/下划线/连字符")
            body = request.get_json(silent=True) or {}
            url = str(body.get("url") or "").strip()
            if not _URL_RE.match(url):
                return _err("入口地址必须是 http(s):// 开头的完整 URL")
            if "websites" not in ConfigManager.config_dict:
                return _err("配置段 websites 不存在", 404)

            with ConfigManager._config_lock:
                sites = dict(ConfigManager.config_dict.get("websites") or {})
                created = name not in sites
                sites[name] = url
                ConfigManager.replace_section("websites", sites)
            logger.info(f"站点 {name} 已{'新增' if created else '更新'}: {url}")
            return jsonify({"success": True, "website": name, "url": url, "created": created})

        @self.blueprint.route("/websites/<name>", methods=["DELETE"])
        def delete_website(name):
            """删除站点入口；仍被作品/位点/脚本路由引用时要求 force=true。"""
            if "websites" not in ConfigManager.config_dict:
                return _err("配置段 websites 不存在", 404)
            usage = _usage().get(name)
            used = bool(usage and (usage["works"] or usage["positions"] or usage["routes"]))
            if used and request.args.get("force") != "true":
                return _err(f"站点 {name} 仍被引用，确认删除请带 force=true", 409, usage=usage)

            with ConfigManager._config_lock:
                sites = dict(ConfigManager.config_dict.get("websites") or {})
                if name not in sites:
                    return _err(f"站点不存在: {name}", 404)
                sites.pop(name)
                ConfigManager.replace_section("websites", sites)
            logger.info(f"已删除站点: {name}")
            return jsonify({"success": True, "removed": name, "usage": usage})
