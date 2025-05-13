import os
import json

# todo：依照不同系统设定默认浏览器和路径

class Config:
    conf={
        "auto_check":False,#是否启用每天的自动检查更新
        "update_interval":86400,#检查更新的频率
        "waiting_play":False,#是否在下载之间插入长睡眠，以模拟正常播放
        "sleep_second":10,#如果不启用长睡眠，每个下载的间隔
        "random_download":False,#是否随机下载
        "download_vip":False,#是否下载vip内容
        "data_path":os.path.abspath("./data"),#数据的存放位置
        "browser":"chrome",#使用的浏览器
        #"chrome_path":"/opt/homebrew/bin/chromedriver",#chrome的路径
        "chrome_path":"C:\Program Files\chromedriver\chromedriver.exe",#chrome的路径
        "use_cookie":True,#是否使用cookie
        "cookie_path":"./data/cookie.pkl",#使用的话cookie的位置
        "domain":"https://www.pixiv.net",
        "port":50051,#使用的通信端口
        "db_name":"test.db",#数据库名称
        "download_priority":(1,0,-1),
        "use_proxy":False,#是否使用代理，不使用为None
        "proxy_ip":"127.0.0.1",
        "proxy_port":"7897",
        "download_thread":1,
        "update_thread":1,
        "once_download":-1
        }
    @classmethod
    def get(cls, key):
        """获取配置项"""
        return cls.conf.get(key, None)
    @classmethod 
    def to_json(cls, path="./data/conf.json"):
        """将配置保存为 JSON 文件"""
        os.makedirs(os.path.dirname(path), exist_ok=True)  # 确保目录存在
        with open(path, "w", encoding="utf-8") as file:
            json.dump(cls.conf, file, ensure_ascii=False, indent=4)
        print(f"配置已保存到 {path}")

    @classmethod
    def from_json(cls, path="./data/conf.json"):
        """从 JSON 文件加载配置"""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                cls.conf = json.load(file)
            print(f"配置已从 {path} 加载")
        else:
            #cls.conf["db_path"]=os.path.join(cls.conf["data_path"],cls.conf["db_name"])
            print(f"配置文件 {path} 不存在，使用默认配置")

def get(key):
    """获取配置项"""
    return Config.conf.get(key, None)
def to_json(path="./data/conf.json"):
    return Config.to_json(path)

def init_config():
    """初始化配置"""
    if not os.path.exists("./data"):
        os.makedirs("./data")
    if not os.path.exists("./data/conf.json"):
        Config.to_json()
    else:
        Config.from_json()