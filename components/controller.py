import time
from bs4 import BeautifulSoup
import json
import sqlite3
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from pathlib import Path
import logging
from .decorator import show_process
from . import timeControl
import datas

@show_process.decorate_all_methods
class controller:
    def __init__(self):
        self.init_browser()
        self.init_database()

    def init_browser(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")

        service = webdriver.ChromeService(executable_path=datas.conf["chrome_path"])
        self.driver = webdriver.Chrome(service=service,options=chrome_options) 

    def daily_update(self):
        try:
            while True:
                logging.info(f"Sleeping for {datas.conf["update_interval"]} seconds...")
                self.updateAllUser()
                time.sleep(datas.conf["update_interval"])  # sleep 5 seconds
        except KeyboardInterrupt:
            print("Program interrupted!")
        

    def init_database(self):
        if not os.path.exists(datas.conf["data_path"]):
            os.mkdir(datas.conf["data_path"])
        dbPath=os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}")
        
        if not os.path.exists(dbPath):
            conn=sqlite3.connect(dbPath)
            cursor=conn.cursor()
            script_dir = Path(__file__).resolve().parent
            sql_script=os.path.join(script_dir,"init.sql")
            with open(sql_script,"r") as script:
                sql_script=script.read()
            cursor.executescript(sql_script)
            conn.commit()
            conn.close()

    def add_a_user(self,user_id):
        try:
            conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user (userId,addTime) VALUES (?,?)",
                (user_id,timeControl.fileTimeSecond())
            )
            conn.commit()
            conn.close()
        except Exception:
            logging.info("user already in list")
            return 
        self.updateUser(user_id)
        

                
    def updateAllUser(self):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        users=cursor.execute("SELECT * FROM user").fetchall()
        conn.close()
        for user in users:
            self.updateUser(user[0])
            
    def changeDownloadPriority(self,video_number,priority=0):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        cursor.execute("UPDATE videos SET downloadPriority=? where video_number=?",(priority,video_number))
        conn.commit()
        conn.close()
    
    def updateUser(self,user_id,take_all=False):
        logging.error(f"updateUser not finished")
    def get_videos(self,soup,user_id) -> bool:
        logging.error(f"updateUser not finished")