import os
import pickle

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from src.utils.logging.logger import SpiderLogger as logger
from src.config.config import ConfigManager


def _resolve_base_path(template: str) -> str:
    """
    解决配置里的占位符（例如 "./${BASE_PATH}/..."）
    """
    if not isinstance(template, str):
        return template
    return template.replace("${BASE_PATH}", ConfigManager.base_path)


class BrowserIniter:
    @classmethod
    def init_cookie(cls) -> None:
        cookie_path = _resolve_base_path(ConfigManager.get("network", "cookie_file"))
        domain = ConfigManager.get("network", "domain")

        if os.path.exists(cookie_path):
            logger.info(f"cookie文件{cookie_path}已经存在，跳过登录")
            return

        logger.info("cookie文件不存在，开始初始化（请手动登录）")
        logger.info(f"目标域名: {domain}")

        cookie_dir = os.path.dirname(cookie_path)
        if cookie_dir:
            os.makedirs(cookie_dir, exist_ok=True)

        chrome_path = ConfigManager.get("network", "chrome_path")

        options = Options()
        # 常用的反自动化/稳定性配置（与旧代码保持一致风格）
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        # 初始化 cookie 需要你手动登录，所以这里不启用 headless
        options.add_argument("--window-size=1920x1080")

        if chrome_path and os.path.exists(chrome_path):
            driver = webdriver.Chrome(service=Service(executable_path=chrome_path), options=options)
        else:
            # 让 webdriver 自动寻找 chromedriver
            driver = webdriver.Chrome(options=options)

        try:
            driver.get(domain)
            input("登录并按 Enter 键继续...")

            cookies = driver.get_cookies()
            with open(cookie_path, "wb") as file:
                pickle.dump(cookies, file)
            logger.debug(f"已经将cookie写入到 {cookie_path}")
        finally:
            driver.quit()


def init_browser() -> None:
    """
    初始化浏览器相关能力：
    - 根据配置决定是否初始化 cookie 文件
    """
    use_cookie = ConfigManager.get("network", "use_cookie")
    if use_cookie:
        logger.info("使用cookie，检查/初始化cookie文件")
        BrowserIniter.init_cookie()
    else:
        logger.info("不使用cookie")