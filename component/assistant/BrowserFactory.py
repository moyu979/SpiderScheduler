import os
import logging
import pickle
from selenium import webdriver

import component.assistant.data as conf

class BrowserFactory:
    @classmethod
    def get_browser(cls, headless=False,cookie=False,force_no_cookie=False):
        if conf.get("browser") == "chrome":
            return cls.get_chrome(headless,cookie,force_no_cookie)
        else:
            raise ValueError("Unsupported browser type")
    @classmethod 
    def get_chrome(cls, headless=False,cookie=False,force_no_cookie=False):
        from selenium.webdriver.chrome.options import Options
        options=Options()
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--no-sandbox')
        if conf.get("use_proxy"):
            logging.info("setting proxy")
            proxy_ip = "127.0.0.1"
            proxy_port = "7897"
            options.add_argument('--proxy-server=http://{}:{}'.format(proxy_ip, proxy_port))
        if conf.get("headless") or headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920x1080')
        service = webdriver.ChromeService(executable_path=conf.get("browser_path"))
        driver = webdriver.Chrome(service=service,options=options)
        
        if (conf.get("use_cookie") or cookie) and not force_no_cookie:
            driver.get(conf.get("domain"))
            with open(conf.get("cookie_path"), "rb") as file:
                cookies = pickle.load(file)
            for cookie in cookies:
                driver.add_cookie(cookie)
            logging.info(f"成功加载cookie文件{conf.get('cookie_path')}")   
        return driver
    


    @classmethod
    def init_cookie(cls):
        if not os.path.exists(conf.get("cookie_path")):
            driver = BrowserFactory.get_browser(cookie=False)
            driver.get(conf.get("domain"))
            input("登录并按 Enter 键继续...")
            cookies = driver.get_cookies()
            with open(conf.get("cookie_path"), "wb") as file:
                pickle.dump(cookies, file)
                logging.info(f"已经将cookie写入到 {conf.get('cookie_path')}")
            driver.quit()
        else:
            logging.info(f"cookie文件{conf.get('cookie_path')}已经存在，跳过登录")


        
