import os
import json
conf={
    "auto_check":False,#是否启用每天的自动检查更新
    "update_interval":86400,#检查更新的频率

    "waiting_play":False,#是否在下载之间插入长睡眠，以模拟正常播放
    "sleep_second":10,#如果不启用长睡眠，每个下载的间隔

    "random_download":False,#是否随机下载

    "download_vip":False,#是否下载vip内容

    "data_path":os.path.abspath("./data"),#数据的存放位置

    "chrome_path":"C:\\Program Files\\chromedriver-win64\\chromedriver.exe",
    
    "use_cookie":True,#是否使用cookie
    "cookie_path":"./data/cookie.pkl",#使用的话cookie的位置
    "login_net":"https://www.pixiv.net",

    "port":50051,#使用的通信端口

    "db_name":"test.db",#数据库名称
    
    "download_priority":(1,0,-1),

    "use_proxy":("127.0.0.1","7897")#是否使用代理，不使用为None

    
}

if os.path.exists("./data/conf.json"):
    path="./data/conf.json"
    with open(path, "r", encoding="utf-8") as file:
        conf = json.load(file)

def save_data(path="./data/conf.json"):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(conf, file, ensure_ascii=False, indent=4)