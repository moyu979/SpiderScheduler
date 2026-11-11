"""Cookie 管理与登录代理端点测试：存取、HTML 同源改写、保存/删除。
"""
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
