import os
import pickle
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from .config import get_browser, get_proxy, get_path
from .logger import logger
from .exceptions import CookieNotExist


class BrowserFactory:
    """
    浏览器工厂类
    负责创建和配置Selenium浏览器实例
    """
    
    @classmethod
    def create_browser(cls, headless=True, use_proxy=False, use_cookie=False):
        """
        创建浏览器实例
        
        Args:
            headless (bool): 是否使用无头模式，默认True
            use_proxy (bool): 是否使用代理，默认False
            use_cookie (bool): 是否使用cookie，默认False
            
        Returns:
            webdriver.Chrome: 配置好的浏览器实例
            
        Raises:
            CookieNotExist: 当请求使用cookie但cookie文件不存在时
        """
        browser_type = get_browser('BROWSER_TYPE')
        
        if browser_type.lower() == 'chrome':
            return cls._create_chrome_browser(headless, use_proxy, use_cookie)
        else:
            raise ValueError(f"不支持的浏览器类型: {browser_type}")
    
    @classmethod
    def _create_chrome_browser(cls, headless=True, use_proxy=False, use_cookie=False):
        """
        创建Chrome浏览器实例
        
        Args:
            headless (bool): 是否使用无头模式
            use_proxy (bool): 是否使用代理
            use_cookie (bool): 是否使用cookie
            
        Returns:
            webdriver.Chrome: 配置好的Chrome浏览器实例
        """
        options = Options()
        
        # 基础配置
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 无头模式配置
        if headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920x1080')
            options.add_argument('--disable-extensions')
            logger.info("启用无头模式")
        
        # 代理配置
        if use_proxy:
            proxy_settings = get_proxy()
            proxy_host = proxy_settings.get('PROXY_HOST', '127.0.0.1')
            proxy_port = proxy_settings.get('PROXY_PORT', '7897')
            proxy_url = f'http://{proxy_host}:{proxy_port}'
            options.add_argument(f'--proxy-server={proxy_url}')
            logger.info(f"配置代理: {proxy_url}")
        
        # 创建浏览器实例
        browser_path = get_browser('BROWSER_PATH')
        if browser_path and os.path.exists(browser_path):
            service = Service(executable_path=browser_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
        
        # 设置用户代理
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Cookie配置
        if use_cookie:
            cls._load_cookies(driver)
        
        logger.info("浏览器实例创建成功")
        return driver
    
    @classmethod
    def _load_cookies(cls, driver):
        """
        加载cookie到浏览器实例
        
        Args:
            driver: 浏览器实例
            
        Raises:
            CookieNotExist: 当cookie文件不存在时
        """
        cookie_path = get_path('COOKIE_FILE')
        
        if not os.path.exists(cookie_path):
            logger.error(f"Cookie文件不存在: {cookie_path}")
            raise CookieNotExist(f"Cookie文件不存在: {cookie_path}")
        
        try:
            with open(cookie_path, 'rb') as file:
                cookies = pickle.load(file)
            
            # 先访问域名，然后添加cookie
            domain = get_browser('DOMAIN')
            driver.get(domain)
            
            for cookie in cookies:
                try:
                    driver.add_cookie(cookie)
                except Exception as e:
                    logger.warning(f"添加cookie失败: {e}")
            
            logger.info(f"成功加载cookie文件: {cookie_path}")
            
        except Exception as e:
            logger.error(f"加载cookie文件失败: {e}")
            raise CookieNotExist(f"加载cookie文件失败: {e}")
    
    @classmethod
    def init_cookies(cls, domain=None):
        """
        初始化cookie文件
        如果cookie文件不存在，会启动浏览器让用户手动登录
        
        Args:
            domain (str): 要访问的域名，如果为None则使用配置中的域名
        """
        cookie_path = get_path('COOKIE_FILE')
        target_domain = domain or get_browser('DOMAIN')
        
        if os.path.exists(cookie_path):
            logger.info(f"Cookie文件已存在: {cookie_path}")
            return
        
        logger.info(f"Cookie文件不存在，开始初始化登录...")
        logger.info(f"目标域名: {target_domain}")
        
        # 创建无头浏览器进行登录
        driver = cls.create_browser(headless=False, use_cookie=False)
        
        try:
            driver.get(target_domain)
            logger.info("请在浏览器中完成登录，然后按Enter键继续...")
            input("登录完成后按Enter键继续...")
            
            # 获取并保存cookie
            cookies = driver.get_cookies()
            
            # 确保cookie目录存在
            cookie_dir = os.path.dirname(cookie_path)
            if cookie_dir and not os.path.exists(cookie_dir):
                os.makedirs(cookie_dir, exist_ok=True)
            
            with open(cookie_path, 'wb') as file:
                pickle.dump(cookies, file)
            
            logger.info(f"Cookie已保存到: {cookie_path}")
            
        except Exception as e:
            logger.error(f"初始化cookie失败: {e}")
            raise
        finally:
            driver.quit()
    
    @classmethod
    def check_cookie_exists(cls):
        """
        检查cookie文件是否存在
        
        Returns:
            bool: cookie文件是否存在
        """
        cookie_path = get_path('COOKIE_FILE')
        exists = os.path.exists(cookie_path)
        logger.debug(f"Cookie文件检查: {cookie_path} - {'存在' if exists else '不存在'}")
        return exists
