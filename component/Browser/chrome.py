import os
import logging
import pickle
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from component.datas import conf
class Browser:
    def __init__(self):
        options=Options()
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--no-sandbox')

        if conf["use_proxy"] is not None:
            logging.info("setting proxy")
            proxy_ip = "127.0.0.1"
            proxy_port = "7897"
            options.add_argument('--proxy-server=http://{}:{}'.format(proxy_ip, proxy_port))
        
        service = webdriver.ChromeService(executable_path=conf["chrome_path"])
        self.driver = webdriver.Chrome(service=service,options=options) 

        if conf["use_cookie"]:
            self.login()

    def login(self):
        if not os.path.exists(conf["cookie_path"]):
            driver = webdriver.Chrome()
            driver.get(conf["login_net"])
            input("登录并按 Enter 键继续...")
            cookies = driver.get_cookies()
            with open(conf["cookie_path"], "wb") as file:
                pickle.dump(cookies, file)
                logging.info(f"已经将cookie写入到{conf["cookie_path"]}")
            driver.quit()

        elif conf["cookie_path"].endswith(".pkl"):
            with open(conf["cookie_path"], "rb") as file:
                cookies = pickle.load(file)
            self.driver.get(conf["login_net"])
            for cookie in cookies:
                self.driver.add_cookie(cookie)
            logging.info(f"成功加载cookie文件{conf["login_net"]}")

    def get(self,url):
        return self.driver.get(url)