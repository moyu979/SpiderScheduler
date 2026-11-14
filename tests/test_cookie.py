"""Cookie 管理与登录代理端点测试：存取、HTML 同源改写、保存/删除、Netscape 导出。
"""
import os
import time

import pytest
import requests
from flask import Flask

from src.config.config import ConfigManager
from src.server.apis.cookie_api import CookieApi, _rewrite_html, _SESSIONS
from src.utils.cookie_manager import CookieManager, CookieNotFoundError


@pytest.fixture(autouse=True)
def cookie_env(monkeypatch, tmp_path):
    """base_path 指向临时目录，隔离 cookie 文件与会话表"""
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    saved_sites = dict(ConfigManager.config_dict.get("websites") or {})
    ConfigManager.config_dict["websites"] = {"fakesite": "http://127.0.0.1:8399"}
    _SESSIONS.clear()
    yield
    _SESSIONS.clear()
    ConfigManager.config_dict["websites"] = saved_sites


@pytest.fixture()
def client():
    """构建只注册 CookieApi 蓝图的 Flask test_client。"""
    app = Flask(__name__)
    app.register_blueprint(CookieApi().blueprint)
    return app.test_client()


def test_cookie_manager_save_get_header_delete():
    """测试 CookieManager 保存、读取、请求头拼装、状态查询与删除全流程。"""
    assert CookieManager.exists("pixiv") is False
    with pytest.raises(CookieNotFoundError):
        CookieManager.get("pixiv")

    cookies = [
        {"name": "PHPSESSID", "value": "abc123", "domain": ".pixiv.net", "path": "/", "expires": None, "secure": True},
        {"name": "p_ab", "value": "xyz", "domain": ".pixiv.net", "path": "/", "expires": 1900000000, "secure": False},
    ]
    assert CookieManager.save("pixiv", cookies) == 2
    assert CookieManager.exists("pixiv") is True

    loaded = CookieManager.get("pixiv")
    assert [c["name"] for c in loaded] == ["PHPSESSID", "p_ab"]
    assert CookieManager.get_header("pixiv") == "PHPSESSID=abc123; p_ab=xyz"

    rows = CookieManager.status()
    assert rows == [{"website": "pixiv", "cookieCount": 2,
                     "updateTime": rows[0]["updateTime"]}]

    assert CookieManager.delete("pixiv") is True
    assert CookieManager.delete("pixiv") is False
    assert CookieManager.exists("pixiv") is False


def test_cookie_file_and_netscape_export(tmp_path):
    """cookie_file 路径暴露与 Netscape 导出：按需生成、内容正确、跟随源刷新、删除联动。"""
    cookies_root = os.path.join(str(tmp_path), "datas", "cookies")
    assert CookieManager.exists("pixiv") is False
    with pytest.raises(CookieNotFoundError):
        CookieManager.netscape_file("pixiv")

    cookies = [
        {"name": "SESSDATA", "value": "s1", "domain": ".bilibili.com",
         "path": "/", "expires": None, "secure": True},
        {"name": "bad", "value": "no-domain"},  # 缺 domain，导出时跳过
        {"name": "buvid", "value": "b1", "domain": "www.bilibili.com",
         "path": "/x", "expires": 1900000000, "secure": False},
    ]
    assert CookieManager.save("pixiv", cookies) == 3
    assert CookieManager.cookie_file("pixiv") == os.path.join(cookies_root, "pixiv.json")

    txt = CookieManager.netscape_file("pixiv")
    assert txt == os.path.join(cookies_root, "netscape", "pixiv.txt")
    lines = open(txt, encoding="utf-8").read().splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert lines[1] == f".bilibili.com\tTRUE\t/\tTRUE\t{CookieManager.FAR_FUTURE_EXPIRY}\tSESSDATA\ts1"
    assert lines[2] == f"www.bilibili.com\tFALSE\t/x\tFALSE\t1900000000\tbuvid\tb1"

    # status() 不受 netscape 导出子目录影响
    rows = CookieManager.status()
    assert [r["website"] for r in rows] == ["pixiv"]

    # 源 JSON 更新后（mtime 变化）自动重新导出：先把导出文件的时间戳拨旧
    stale = time.time() - 10
    os.utime(txt, (stale, stale))
    CookieManager.save("pixiv", [
        {"name": "SESSDATA", "value": "s2", "domain": ".bilibili.com",
         "path": "/", "expires": None, "secure": False},
    ])
    lines = open(CookieManager.netscape_file("pixiv"), encoding="utf-8").read().splitlines()
    assert lines[1] == f".bilibili.com\tTRUE\t/\tFALSE\t{CookieManager.FAR_FUTURE_EXPIRY}\tSESSDATA\ts2"

    # 删除 cookie 时联动清理导出文件
    CookieManager.delete("pixiv")
    assert os.path.exists(txt) is False
    assert CookieManager.exists("pixiv") is False


def test_netscape_export_empty_cookies():
    """cookie 文件为空时 Netscape 导出与 get 一样报 CookieNotFoundError。"""
    CookieManager.save("pixiv", [])
    with pytest.raises(CookieNotFoundError):
        CookieManager.netscape_file("pixiv")


def test_netscape_lines_conversion():
    """netscape_lines 纯转换：任意 Selenium 格式列表 → Netscape 行（内存传入 cookie 的临时导出用）。"""
    lines = CookieManager.netscape_lines([
        {"name": "a", "value": "1", "domain": ".example.com",
         "path": "/", "expires": None, "secure": True},
        {"name": "bad"},                       # 缺 domain，跳过
        {"name": "b", "value": "2", "domain": "example.com"},  # path/secure/expires 全走默认
    ])
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert lines[1] == f".example.com\tTRUE\t/\tTRUE\t{CookieManager.FAR_FUTURE_EXPIRY}\ta\t1"
    assert lines[2] == f"example.com\tFALSE\t/\tFALSE\t{CookieManager.FAR_FUTURE_EXPIRY}\tb\t2"
    assert len(lines) == 3


def test_rewrite_html_makes_same_origin(client):
    """测试 HTML 中绝对/协议相对/根相对地址与 JS 字符串均改写为代理同源路径并注入 base。"""
    origin = "https://www.pixiv.net"
    html = b"""<html><head><title>t</title></head><body>
      <a href="https://www.pixiv.net/login">abs</a>
      <img src="//www.pixiv.net/a.png">
      <link rel="stylesheet" href="/css/x.css">
      <form action="/login"><script>location.href='https://www.pixiv.net/step2'</script></form>
    </body></html>"""
    out = _rewrite_html("pixiv", origin, html).decode()
    assert 'href="/api/cookie/pixiv/proxy/login"' in out          # 绝对地址
    assert 'src="/api/cookie/pixiv/proxy/a.png"' in out           # 协议相对
    assert 'href="/api/cookie/pixiv/proxy/css/x.css"' in out      # 根相对
    assert "location.href='/api/cookie/pixiv/proxy/step2'" in out  # JS 内字符串
    assert '<base href="/api/cookie/pixiv/proxy/">' in out        # base 注入
    assert 'src="//www.pixiv.net' not in out and 'https://www.pixiv.net' not in out


def test_status_lists_configured_sites(client):
    """测试 status 端点按 websites 配置列出站点及其 cookie 状态。"""
    data = client.get("/api/cookie/status").get_json()
    assert data["success"]
    assert data["rows"] == [{"website": "fakesite", "domain": "http://127.0.0.1:8399",
                             "hasCookie": False, "cookieCount": 0, "updateTime": None}]


def test_login_page_contains_proxy_iframe(client):
    """测试登录页包含代理 iframe 地址与“完成并保存”入口。"""
    resp = client.get("/api/cookie/fakesite/login_page")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '/api/cookie/fakesite/proxy/' in body
    assert "完成并保存" in body


def test_login_page_unknown_website_400(client):
    """测试未知站点的登录页返回 400 并在错误信息中指名站点。"""
    resp = client.get("/api/cookie/ghost/login_page")
    assert resp.status_code == 400
    assert "ghost" in resp.get_json()["error"]


def test_save_persists_session_cookies(client):
    """测试 save 端点把代理会话 cookie 持久化并在保存后销毁会话。"""
    session = requests.Session()
    session.cookies.set("sid", "abc", domain="127.0.0.1", path="/")
    _SESSIONS["fakesite"] = session

    resp = client.post("/api/cookie/fakesite/save")
    assert resp.status_code == 200
    assert resp.get_json()["cookieCount"] == 1

    loaded = CookieManager.get("fakesite")
    assert loaded[0]["name"] == "sid" and loaded[0]["value"] == "abc"
    assert "fakesite" not in _SESSIONS  # 保存后会话销毁


def test_save_without_login_session_fails(client):
    """测试没有登录会话时 save 端点返回 400。"""
    resp = client.post("/api/cookie/fakesite/save")
    assert resp.status_code == 400


def test_delete_endpoint(client):
    """测试删除 cookie 端点首次成功、重复删除返回未删除。"""
    CookieManager.save("fakesite", [{"name": "a", "value": "b"}])
    assert client.delete("/api/cookie/fakesite").get_json()["removed"] is True
    assert client.delete("/api/cookie/fakesite").get_json()["removed"] is False
