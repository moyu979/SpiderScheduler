import sqlite3
import os

import subprocess
import random

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import pickle
import logging
from time import sleep


from component.tools import timeControl
from component import datas
from component.Browser.chrome import Browser

class Downloader:
    def __init__(self):
        self.continue_download=True
        self.working=False
        self.driver=Browser().get_driver()

    def download_all(self):
        self.working=True
        while self.continue_download:
            if not self.downloadOne():
                logging.info("都下完啦")
                break
        logging.info(f"Stoped by cmd")
        self.working=False

    def download_some(self,download_number=2):
        self.working=True
        for i in range(0,download_number):
            logging.info(f"download {i}th video")
            self.downloadOne()
            if not self.continue_download:
                logging.info(f"Stoped by cmd")
                break
        self.working=False

    def download_user(self,user_id):
        self.working=True
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        works=cursor.execute("SELECT * FROM upload WHERE userId=? and state=?",(user_id,"inQueue")).fetchall()
        conn.close()

        logging.info(f"需要下载这个用户的 {len(works)} 段作品")
        for work in works:
            if not self.continue_download:
                logging.info(f"Stoped by cmd")
                break
            self._download(work)
        self.working=False

    def download_wanted(self,work_id):
        self.working=True
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        data=cursor.execute("SELECT * FROM works WHERE workNumber=?",(work_id,)).fetchall()
        conn.close()
        if len(data)==0:
            work_name,work_kind=self.get_info_by_id(work_id)
            conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
            cursor = conn.cursor()
            cursor.execute("INSERT INTO works (workNumber,title,kind,state) VALUES (?,?,?,?)",(work_id,work_name,work_kind,"inQueue")).fetchall()
            data=cursor.execute("SELECT * FROM works WHERE workNumber=?",(work_id,)).fetchall()
            conn.commit()
            conn.close()
        data=data[0]
        print(data)
        if self._download(data):
            conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
            cursor = conn.cursor()
            cursor.execute("update works set state='finished' where workNumber=?",(data[1],))
            cursor.execute("update works set downloadDate=? where workNumber=?",(timeControl.now_time(),data[1]))
            conn.commit()
            conn.close()
        self.working=False

    def get_info_by_id(self,video_id):
        """
        这个方法主要完成以下功能：
        给定的视频号，获得视频标题和类型,可以不写
        """
        return "",""
    
    def downloadOne(self):
        for i in datas.conf["download_priority"]:
            conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
            cursor = conn.cursor()
            one_data=cursor.execute("SELECT * FROM works WHERE state=? and downloadPriority=?",("inQueue",i)).fetchone()
            cursor.close()
            conn.commit()
            conn.close()
            if one_data is None:
                continue
            else:
                if self._download(one_data):
                    conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
                    cursor = conn.cursor()
                    cursor.execute("update works set state='finished' where workNumber=?",(one_data[1],))
                    cursor.execute("update works set downloadDate=? where workNumber=?",(timeControl.now_time(),one_data[1]))
                    conn.commit()
                    conn.close()
                return True
            
        return False
    
    def _download(self,data):
        logging.info("这个是需要你完成的！请完成获取用户的投稿并且写到数据库的功能")