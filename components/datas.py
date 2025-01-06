import os
import json
conf={
    "waiting_play":False,
    "random_download":False,
    "sleep_second":10,
    "download_vip":False,
    "data_path":os.path.abspath("./testFile"),
    "chrome_path":"C:\\Program Files\\chromedriver-win64\\chromedriver.exe",
    "cookiePath":os.path.join(os.path.expanduser("~"), "yourCookie.txt"),
    "port":50051,
    "db_name":"test.db",
    "not_work_mode":True,
    "update_interval":1,
    "download_priority":(1,0,-1)
}
if os.path.exists("./conf.json"):
    path="./conf.json"
    with open(path, "r", encoding="utf-8") as file:
        conf = json.load(file)

def save_data(path="./conf.json"):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(conf, file, ensure_ascii=False, indent=4)