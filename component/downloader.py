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
        logging.info(f"正在下载{data}")
        work_id=data[1]
        user=self._get_user(data)
        total_save_path=os.path.join(datas.conf["data_path"],f"{user}")
        if not os.path.exists(total_save_path):
            os.mkdir(total_save_path)
        work_save_path=os.path.join(total_save_path,f"{work_id}")
        if not os.path.exists(work_save_path):
            os.mkdir(work_save_path)
        
        self.driver.get(f"https://www.pixiv.net/artworks/{work_id}")
        html_content = self.driver.page_source
        
        with open(os.path.join(work_save_path,"page.html"),"w",encoding='utf-8') as f:
            f.write(html_content)

        soup = BeautifulSoup(html_content, 'html.parser')
        data=soup.find(class_="sc-emr523-2 wEKy")
        count=0
        if data is None:
            main=soup.find("main")
            all_img=main.find_all("figure")
            for img in all_img:
                adata=img.find("a")
                if adata is not None:
                    url=adata.get("href")
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                        "Referer": f"https://www.pixiv.net/artworks/{work_id}" # 标明从哪个网页跳转
                    }
                    response = requests.get(url,headers=headers)
                    if response.status_code == 200:
                        with open(os.path.join(work_save_path,f"{count}.png"), "wb") as file:
                            file.write(response.content)
                    count=count+1
        else:
            self.driver.get(f"https://www.pixiv.net/artworks/{work_id}#1")
            self.driver.refresh()
            html_content = self.driver.page_source
            with open(os.path.join(work_save_path,"page_all.html"),"w",encoding='utf-8') as f:
                f.write(html_content)
            soup = BeautifulSoup(html_content, 'html.parser')
            data=soup.find(class_="sc-1oz5uvo-1 ivxzyL")
            img_group=data.find_all("a")
            count=0
            for a in img_group:
                url=a.get("href")
                if url.endswith(".png"):
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                        "Referer": f"https://www.pixiv.net/artworks/{work_id}" # 标明从哪个网页跳转
                    }
                    response = requests.get(url,headers=headers)
                    if response.status_code == 200:
                        with open(os.path.join(work_save_path,f"{count}.png"), "wb") as file:
                            file.write(response.content)
                    count=count+1
                    logging.info("下载成功")

        logging.info("下载成功")
        return True
    
    def _get_user(self,data):
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        res=cursor.execute("select * from upload where workNumber=?",(data[1],)).fetchall()
        conn.close()
        if len(res)==0:
            return 0
        else:
            return res[0][0] 

                    