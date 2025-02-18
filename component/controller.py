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
        self.driver.get(f"https://www.pixiv.net/users/{user_id}/artworks")
        html_content = self.driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        max_page=self.get_max_page(soup,user_id)

        for i in range(1,max_page+1):
            logging.info(f"正在下载第{i}页")

            if i==1:
                herf=f"https://www.pixiv.net/users/{user_id}/artworks"
            else:
                herf=f"https://www.pixiv.net/users/{user_id}/artworks?p={i}"
            #返回值是false意味着要截断，后面的记录过
            if not self.get_artwork(herf,user_id):
                break

        logging.info("这个是需要你完成的！请完成获取用户的投稿并且写到数据库的功能")

    def get_max_page(self,soup,user_id):
        pages=soup.find(class_="sc-xhhh7v-0 kYtoqc")
        links = [a['href'] for a in pages.find_all('a', href=True)]
        page_number=[]
        for l in links:
            link=f"/users/{user_id}/artworks?p="
            page_number.append(int(l.replace(link,"")))
        return (np.max(page_number))
    
    def get_artwork(self,herf,user_id):
        self.driver.get(herf)
        time.sleep()
        html_content = self.driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        pics=soup.find_all(class_="sc-iasfms-1 jthKhf")
        count=0
        for pic in pics:
            workNumber=pic.find("a").get("href").replace("/artworks/","")
            name=pic.text
            conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
            cursor=conn.cursor()

            try:
                cursor.execute("INSERT INTO upload (userId,workNumber) VALUES (?,?)",(user_id,workNumber))
            except Exception:
                conn.close()
                return False

            try:
                cursor.execute("INSERT INTO works (upTime,workNumber,title,kind,state,downloadDate,downloadPriority) VALUES (?,?,?,?,?,?,?)"\
                               ,("",workNumber,name,"normal","inQueue","",0))
            except Exception:
                logging.error(Exception)
                pass
            
            logging.info(f"add artwork {workNumber},{name}")
            conn.commit()
            conn.close()
            count=count+1
        logging.info(f"在此页记录了{count}")
        return True

if __name__=="__main__":
    controller=Controller()