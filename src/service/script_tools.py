"""脚本运行时工具集（ScriptTools）。

downloader 在执行每个下载任务前，构造一个与"当前任务站点"绑定的工具实例，
注入为脚本实例的 ``tools`` 属性。脚本由此获得：

- 统一日志出口（框架 SpiderLogger，自动按类归因）；
- 站点登录态浏览器（Selenium，自动注入 CookieManager 的 cookie，无头模式
  自动清除 UA 的 HeadlessChrome 标记）；
- 站点入口地址查询（websites.yaml）；
- 动态注册扩展工具的入口（register），后续可平滑增加新能力。

依赖策略：selenium 为可选依赖，仅在调用 get_driver 时才导入——脚本头部
写 ``# requirements: selenium`` 即可在加载前由框架自动装好；未安装时抛出
带修复指引的 ScriptToolsError。浏览器用完须 ``driver.quit()``（Selenium
driver 不支持 with 语法，由调用方负责收尾）。
"""

from src.config.config import ConfigManager
from src.utils.cookie_manager import CookieManager
from src.utils.logging.logger import SpiderLogger as logger


class ScriptToolsError(Exception):
    """工具集操作失败（站点未配置 / 依赖缺失 / 浏览器装配失败）。"""


class ScriptTools:
    """脚本运行时工具集：日志、站点信息、登录态浏览器与扩展注册。

    框架按任务注入（实例属性，构造完成后赋值）；以库方式使用时也可直接
    构造，参数与注入值一致。

    Attributes:
        website: 本任务所属站点名（cookie / 站点地址都按它解析）。
        logger: 框架日志门面（SpiderLogger），getter 内部与脚本共用。
        cookie_manager: cookie 入口，默认注入 CookieManager 类（文件传入）；
            嵌入式用法可替换为任何提供 exists()/get() 接口的实现。
        config_manager: 配置入口，默认全局 config_manager 单例。
    """

    def __init__(self, website, logger_=None,
                 cookie_manager=CookieManager, config_manager=ConfigManager):
        """装配与单个任务站点绑定的工具实例。

        Args:
            website: 本任务所属站点名。
            logger_: 日志门面；None 时用全局 SpiderLogger。
            cookie_manager: cookie 入口；默认 CookieManager 类。
            config_manager: 配置入口；默认全局 ConfigManager 单例。
        """
        self.website = website
        self.logger = logger_ if logger_ is not None else logger
        self.cookie_manager = cookie_manager
        self.config_manager = config_manager

    # ---------------- 日志 ----------------

    def log(self, level, message):
        """以站点上下文写一条日志（级别用名字，如 "info"/"warning"）。

        Args:
            level: 日志级别名（大小写不敏感，对应 SpiderLogger 的方法名）。
            message: 日志消息。
        """
        getattr(self.logger, str(level).lower())(message)

    # ---------------- 站点信息 ----------------

    def site_origin(self):
        """返回本站点在 websites.yaml 中配置的入口地址（去尾部斜杠）。

        Returns:
            str: 形如 ``https://www.example.com`` 的入口地址。

        Raises:
            ScriptToolsError: websites.yaml 未配置该站点。
        """
        sites = self.config_manager.config_dict.get('websites') or {}
        url = str(sites.get(self.website) or '').strip()
        if not url:
            available = ', '.join(sorted(sites)) or '无'
            raise ScriptToolsError(
                f"websites.yaml 中没有配置 website={self.website!r} 的入口地址（可用: {available}）")
        return url.rstrip('/')

    # ---------------- 代理 ----------------

    def proxy_url(self):
        """返回 system.yaml 配置的代理地址（``http://<ip>:<port>``）。

        use_proxy 为假、配置段/键缺失或格式异常时返回 None——脚本可无条件
        调用本方法，按返回值自行决定是否走代理。

        Returns:
            str | None: 代理地址，未启用代理时为 None。
        """
        try:
            if not self.config_manager.get('system', 'use_proxy'):
                return None
            ip = str(self.config_manager.get('system', 'proxy_ip')).strip()
            port = str(self.config_manager.get('system', 'proxy_port')).strip()
            if not ip or not port:
                return None
            if "://" in ip:  # 允许直接把完整代理串写进 proxy_ip
                return ip
            return f"http://{ip}:{port}"
        except Exception:  # GetUnknownKey 等：未配置即视为不走代理
            return None

    def get_proxies(self):
        """返回可直接传给 requests 的代理字典（独立于 Selenium 的兜底方式）。

        典型用法：``requests.get(url, proxies=tools.get_proxies())``——
        未启用代理时返回空字典，可不加判断直接传。

        Returns:
            dict: ``{"http": 地址, "https": 地址}``，未启用代理时为 ``{}``。
        """
        url = self.proxy_url()
        return {"http": url, "https": url} if url else {}

    def _proxy_address(self, proxy):
        """解析 get_driver 的 proxy 参数为实际代理地址（None 表示不走代理）。"""
        if proxy == "auto":
            return self.proxy_url()
        return proxy

    # ---------------- 浏览器 ----------------

    @staticmethod
    def _selenium_cookie(cookie):
        """文件存储的 'expires' 键转为 add_cookie 认的 'expiry'，剔除未知键。"""
        known = ("name", "value", "path", "domain", "secure", "httpOnly", "sameSite")
        converted = {k: cookie[k] for k in known if cookie.get(k) is not None}
        expires = cookie.get("expiry") or cookie.get("expires")
        if expires is not None:
            converted["expiry"] = int(float(expires))
        return converted

    def get_driver(self, headless=True, extra_arguments=None, inject_cookies=True,
                   proxy="auto", chrome_path=None):
        """创建一个携带本站点登录态与代理配置的 Chrome（Selenium）。

        流程：组装选项（无头/窗口/去自动化特征/代理）→ 创建 driver（chromedriver
        由 selenium-manager 自动匹配，或用指定 chrome_path）→ 无头时经 CDP 把
        UA 的 HeadlessChrome 标记去掉（保留真实版本号）→ 打开站点入口页并逐条
        注入 cookie → 返回。装配中途失败会关闭已创建的 driver 再抛错；用完请
        ``driver.quit()``。

        Args:
            headless: 是否无头；调度后台默认 True，本地调试可设 False。
            extra_arguments: 追加的 Chrome 启动参数列表（可为 None）。
            inject_cookies: 是否注入本站点的登录 cookie（CookieManager）。
            proxy: 代理来源。"auto"（默认）按 system.yaml 的 use_proxy 自动
                决定；显式传地址字符串（如 ``socks5://127.0.0.1:1080``）按
                指定地址走代理；传 None 强制不走代理。
            chrome_path: 指定 chromedriver/浏览器可执行文件；默认交给
                selenium-manager 自动匹配。

        Returns:
            selenium.webdriver.Chrome: 已就绪的 driver（已处于站点入口页）。

        Raises:
            ScriptToolsError: 未安装 selenium（提示在脚本头部声明依赖）、
                站点未配置入口地址，或浏览器装配失败。
        """
        try:
            from selenium import webdriver
        except ImportError as e:
            raise ScriptToolsError(
                "未安装 selenium；请在脚本头部加 '# requirements: selenium'，"
                "框架会在加载脚本前自动安装") from e

        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        address = self._proxy_address(proxy)
        if address:
            options.add_argument(f"--proxy-server={address}")
            self.log("info", f"[tools] 浏览器走代理 {address}")
        for argument in extra_arguments or []:
            options.add_argument(argument)

        try:
            if chrome_path:
                from selenium.webdriver.chrome.service import Service
                driver = webdriver.Chrome(service=Service(chrome_path), options=options)
            else:
                driver = webdriver.Chrome(options=options)
        except Exception as e:
            raise ScriptToolsError(f"创建 Chrome 失败: {e}") from e

        try:
            if headless:
                # 无头 UA 带 HeadlessChrome/<真实版本> 标记（Chrome 156 实测），
                # 经 CDP 覆盖为仅去掉该标记的真实 UA，版本号与客户端提示保持一致
                real_ua = driver.execute_script("return navigator.userAgent") or ""
                if "Headless" in real_ua:
                    driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                        "userAgent": real_ua.replace("HeadlessChrome", "Chrome")})

            if inject_cookies:
                # add_cookie 前需先处于同域页面
                driver.get(self.site_origin())
                cookies = []
                if self.cookie_manager is not None and self.cookie_manager.exists(self.website):
                    cookies = self.cookie_manager.get(self.website)
                else:
                    self.log("info", f"[tools] {self.website} 无登录 cookie，以匿名状态打开浏览器")
                injected = 0
                for cookie in cookies:
                    try:
                        driver.add_cookie(self._selenium_cookie(cookie))
                        injected += 1
                    except Exception as e:
                        self.log("warning", f"[tools] 注入 cookie {cookie.get('name')} 失败，跳过: {e}")
                if cookies:
                    self.log("info", f"[tools] 已注入 {injected}/{len(cookies)} 条 cookie")
            return driver
        except Exception as e:
            try:
                driver.quit()
            except Exception:
                pass
            if isinstance(e, ScriptToolsError):
                raise
            raise ScriptToolsError(f"浏览器装配失败: {e}") from e

    # ---------------- 扩展 ----------------

    def register(self, name, fn):
        """动态注册一个工具，之后可经 ``self.tools.<name>(...)`` 调用。

        用于给脚本渐进式增加新能力（如截图、代理切换、验证码识别）而无需
        改动框架注入点；注册名与既有属性冲突时拒绝。

        Args:
            name: 工具名（将挂为实例属性，须是合法属性名）。
            fn: 可调用对象（第一个参数即本 tools 实例，便于访问 logger 等）。

        Raises:
            ScriptToolsError: 名字非法或与既有属性冲突。
        """
        if not name.isidentifier() or name.startswith('_'):
            raise ScriptToolsError(f"非法工具名: {name!r}（须为不以 _ 开头的合法属性名）")
        if hasattr(self, name):
            raise ScriptToolsError(f"工具名与既有属性冲突: {name!r}")

        tools_ref = self

        def _bound(*args, **kwargs):
            """绑定调用：把 tools 实例作为第一个参数传给注册的函数。"""
            return fn(tools_ref, *args, **kwargs)

        setattr(self, name, _bound)
