import time
import sqlite3
import os
import logging

import numpy as np

from bs4 import BeautifulSoup
from component.tools import timeControl
from component import datas

from component.Browser.chrome import Browser
from component.database.initDatabase import init_database
class Controller:
    def __init__(self):
        self.driver=Browser().get_driver()
        
        init_database()
        logging.info("初始化成功")

    def daily_update(self):
        while True:
            if datas.conf["auto_check"]:
                logging.info(f"自动已开启，下次检查为约{datas.conf["update_interval"]}s后")
                self.update_all_user()
                time.sleep(datas.conf["update_interval"])

    def add_a_user(self,user_id):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO user (userId,addTime) VALUES (?,?)",
                (user_id,timeControl.now_time())
            )
        except Exception:
            logging.warning("用户已经存在，什么都不做")
            conn.close()
            return
        conn.commit()
        conn.close()
        self.update_user(user_id)

    def update_all_user(self):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        users=cursor.execute("SELECT * FROM user").fetchall()
        conn.close()
        for user in users:
            self.update_user(user[0])

    def update_user(self,user_id):
        logging.info(f"正在更新{user_id}")
        self._update_user(user_id)

    def change_work_priority(self,video_number,priority=0):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE works SET downloadPriority=? where workNumber=?",(priority,video_number))
        except Exception:
            logging.error(Exception)

        conn.commit()
        conn.close()

    def add_work(self,work_number):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO works (upTime,workNumber,title,kind,state,downloadDate,downloadPriority) VALUES (?,?,?,?,?,?,?)",\
                           ("",work_number,"","","inQueue","",0))
        except Exception:
            logging.error(str(Exception))

        conn.commit()
        conn.close()

        
    def _update_user(self,user_id):
        logging.info("这个是需要你完成的！请完成获取用户的投稿并且写到数据库的功能")
