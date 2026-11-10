"""ScriptTools 单元测试：日志出口、站点地址、浏览器装配（桩测）与动态注册。"""

import pytest

from src.service.script_tools import ScriptTools, ScriptToolsError
from src.config.config import ConfigManager


@pytest.fixture()
def tools_env(monkeypatch, tmp_path):
    """隔离 websites 配置与 cookie 目录，返回绑定了桩 cookie 的 tools 工厂"""
    saved = dict(ConfigManager.config_dict)
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict["websites"] = {"e2e": "http://127.0.0.1:9000/"}
    yield tmp_path
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict.update(saved)


def _make_tools(cookie_manager=None):
    return ScriptTools(website="e2e", cookie_manager=cookie_manager)


# ---------------- 日志与站点信息 ----------------

def test_log_dispatches_to_logger_facade():
    calls = []

    class _StubLogger:
        def info(self, msg): calls.append(("info", msg))
        def warning(self, msg): calls.append(("warning", msg))

    tools = ScriptTools(website="e2e", logger_=_StubLogger())
    tools.log("INFO", "a")
    tools.log("warning", "b")
    assert calls == [("info", "a"), ("warning", "b")]


def test_site_origin_reads_websites_and_strips_trailing_slash(tools_env):
    assert _make_tools().site_origin() == "http://127.0.0.1:9000"


def test_site_origin_raises_for_unconfigured_site(tools_env):
    tools = ScriptTools(website="ghost")
    with pytest.raises(ScriptToolsError, match="ghost"):
        tools.site_origin()


# ---------------- 浏览器装配（桩测 selenium） ----------------

class _FakeOptions:
    def __init__(self):
        self.arguments = []

    def add_argument(self, argument):
        self.arguments.append(argument)


class _FakeDriver:
    """记录调用的假 driver；UA 带 HeadlessChrome 标记（Chrome 156 实测形态）"""

    REAL_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) HeadlessChrome/156.0.0.0 Safari/537.36")

    def __init__(self, options):
        self.options = options
        self.pages = []
        self.cookies = []
        self.cdp = []
        self.quit_called = False

    def execute_script(self, script):
        return self.REAL_UA

    def execute_cdp_cmd(self, cmd, params):
        self.cdp.append((cmd, params))

    def get(self, url):
        self.pages.append(url)

    def add_cookie(self, cookie):
        self.cookies.append(cookie)

    def quit(self):
        self.quit_called = True


class _StubCookieManager:
    """桩 cookie 入口：记录 exists/get 调用"""

    instances = []

    def __init__(self, cookies):
        self.cookies = cookies
        self.exists_called = False
        _StubCookieManager.instances.append(self)

    def exists(self, website):
        self.exists_called = True
        return bool(self.cookies)

    def get(self, website):
        return self.cookies


@pytest.fixture()
def fake_selenium(monkeypatch):
    """替身 selenium.webdriver，并记录最后一次创建的 driver"""
    # selenium 已从 requirements.txt 移除（运行时懒加载可选）：
    # 环境未装时跳过这批用例，而不是 fixture error
    pytest.importorskip("selenium")
    import selenium.webdriver as wd

    created = []

    class _Factory:
        ChromeOptions = _FakeOptions

        @staticmethod
        def Chrome(options=None, **kwargs):
            driver = _FakeDriver(options)
            driver.init_kwargs = kwargs
            created.append(driver)
            return driver

    monkeypatch.setattr(wd, "ChromeOptions", _FakeOptions, raising=False)
    monkeypatch.setattr(wd, "Chrome", _Factory.Chrome)
    yield created


def test_get_driver_headless_assembles_and_overrides_ua(tools_env, fake_selenium):
    tools = _make_tools(cookie_manager=_StubCookieManager([]))
    driver = tools.get_driver(headless=True, extra_arguments=["--lang=zh-CN"])

    assert driver.options.arguments == [
        "--headless=new", "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled", "--lang=zh-CN",
    ]
    # 无头时经 CDP 去掉 HeadlessChrome 标记且保留真实版本号
    assert driver.cdp and driver.cdp[0][0] == "Network.setUserAgentOverride"
    ua = driver.cdp[0][1]["userAgent"]
    assert "Headless" not in ua and "Chrome/156.0.0.0" in ua
    # 无 cookie：打开站点入口页后直接返回
    assert driver.pages == ["http://127.0.0.1:9000"]
    assert not driver.quit_called


def test_get_driver_injects_cookies_with_expiry_conversion(tools_env, fake_selenium):
    cookies = [{"name": "SESSDATA", "value": "abc", "domain": ".example.com",
                "path": "/", "expires": 1790000000.5, "secure": True},
               {"name": "bad", "value": "x", "unknown_key": 1}]
    tools = _make_tools(cookie_manager=_StubCookieManager(cookies))
    driver = tools.get_driver(headless=False)  # 有头不做 UA 覆盖

    assert driver.cdp == []  # 有头：无 UA 覆盖
    assert driver.pages == ["http://127.0.0.1:9000"]
    assert driver.cookies == [
        {"name": "SESSDATA", "value": "abc", "domain": ".example.com",
         "path": "/", "secure": True, "expiry": 1790000000},
        {"name": "bad", "value": "x"},
    ]


def test_get_driver_anonymous_without_cookie_file(tools_env, fake_selenium):
    tools = _make_tools(cookie_manager=_StubCookieManager([]))
    driver = tools.get_driver()
    assert driver.pages == ["http://127.0.0.1:9000"] and driver.cookies == []


def test_get_driver_missing_selenium_gives_actionable_error(tools_env, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "selenium":
            raise ImportError("No module named 'selenium'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ScriptToolsError, match="# requirements: selenium"):
        _make_tools().get_driver()


def test_get_driver_failure_cleans_up_driver(tools_env, fake_selenium, monkeypatch):
    # 站点未配置入口 → 装配失败，driver 必须被 quit
    ConfigManager.config_dict["websites"].clear()
    tools = _make_tools(cookie_manager=_StubCookieManager([]))
    with pytest.raises(ScriptToolsError, match="websites.yaml"):
        tools.get_driver()
    assert fake_selenium[-1].quit_called


# ---------------- 代理 ----------------

def _enable_proxy(ip="127.0.0.1", port="7897"):
    ConfigManager.config_dict["system"] = {
        "use_proxy": True, "proxy_ip": ip, "proxy_port": port}


def test_proxy_disabled_yields_none_and_empty_proxies(tools_env, fake_selenium):
    tools = _make_tools()
    assert tools.proxy_url() is None
    assert tools.get_proxies() == {}
    driver = tools.get_driver()
    assert not any(a.startswith("--proxy-server") for a in driver.options.arguments)


def test_proxy_auto_applies_to_driver_and_requests(tools_env, fake_selenium):
    _enable_proxy()
    tools = _make_tools()
    assert tools.proxy_url() == "http://127.0.0.1:7897"
    assert tools.get_proxies() == {"http": "http://127.0.0.1:7897",
                                   "https": "http://127.0.0.1:7897"}
    driver = tools.get_driver()
    assert "--proxy-server=http://127.0.0.1:7897" in driver.options.arguments


def test_proxy_explicit_address_and_force_disable(tools_env, fake_selenium):
    _enable_proxy()
    tools = _make_tools()
    # 显式地址（如 socks5）优先于配置
    driver = tools.get_driver(proxy="socks5://127.0.0.1:1080")
    assert "--proxy-server=socks5://127.0.0.1:1080" in driver.options.arguments
    # proxy=None 强制不走代理（配置已启用也不注入）
    driver = tools.get_driver(proxy=None)
    assert not any(a.startswith("--proxy-server") for a in driver.options.arguments)


def test_proxy_url_accepts_full_address_in_proxy_ip(tools_env):
    _enable_proxy(ip="socks5://10.0.0.1", port="1080")
    tools = _make_tools()
    assert tools.proxy_url() == "socks5://10.0.0.1"


def test_proxy_off_when_use_proxy_false(tools_env):
    _enable_proxy()
    ConfigManager.config_dict["system"]["use_proxy"] = False
    tools = _make_tools()
    assert tools.proxy_url() is None and tools.get_proxies() == {}


def test_get_driver_chrome_path_passes_service(tools_env, fake_selenium):
    tools = _make_tools(cookie_manager=_StubCookieManager([]))
    tools.get_driver(chrome_path="/fake/chromedriver")
    service = fake_selenium[-1].init_kwargs.get("service")
    # selenium 4.15 的 Service 把路径存为 path（旧版为 executable_path）
    stored = getattr(service, "path", None) or getattr(service, "executable_path", None)
    assert service is not None and stored == "/fake/chromedriver"


# ---------------- 动态注册 ----------------

def test_register_adds_callable_and_validates(tools_env):
    tools = _make_tools()
    tools.register("screenshot", lambda self_, path: f"shot-{path}")
    assert tools.screenshot("x") == "shot-x"

    with pytest.raises(ScriptToolsError, match="冲突"):
        tools.register("screenshot", lambda self_: None)
    with pytest.raises(ScriptToolsError, match="非法工具名"):
        tools.register("_private", lambda self_: None)
    with pytest.raises(ScriptToolsError, match="非法工具名"):
        tools.register("not identifier", lambda self_: None)
