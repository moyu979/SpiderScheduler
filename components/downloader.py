import sqlite3
import os

import subprocess
import random

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
from time import sleep
from moviepy.editor import VideoFileClip
from .decorator import show_process

from . import timeControl
import datas

@show_process.decorate_all_methods
class downloader:
    def __init__(self):
        self.continue_download=True
        self.working=False

    def downloadAll(self):
        self.working=True
        while self.continue_download:
            self.downloadOne()
        logging.info(f"Stoped by cmd")
        self.working=False

    def downloadSome(self,download_number=10):
        self.working=True
        for i in range(0,download_number):
            logging.info(f"download {i}th video")
            self.downloadOne()
            if not self.continue_download:
                logging.info(f"Stoped by cmd")
                break
        self.working=False

    def downloadUser(self,user_id):
        self.working=True
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        videos=cursor.execute("SELECT * FROM upload WHERE uploader=?",(user_id,)).fetchall()
        conn.close()
        logging.info(f"need to download {len(videos)}")
        for video in videos:
            if not self.continue_download:
                logging.info(f"Stoped by cmd")
                break
            self.downloadChosen(video[1])
        self.working=False

    def download_wanted(self,video_id):
        self.working=True
        conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
        cursor = conn.cursor()
        data=cursor.execute("SELECT * FROM videos WHERE video_id=?",(video_id,)).fetchall()
        conn.close()
        if len(data)==0:
            video_name,video_kind=self.get_info_by_id(video_id)
            conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"))
            cursor = conn.cursor()
            data=cursor.execute("INSERT INTO videos (video_number,title,kind,state,)",(video_id,video_name,video_kind,"inQueue")).fetchall()
            conn.commit()
            conn.close()
        self.downloadChosen(video_id)
        self.working=False

    
    def get_info_by_id(self,video_id):
        """
        这个方法主要完成以下功能：
        给定的视频号，获得视频标题和类型
        """
        pass


    
    def download(self,data):
        """
        这个方法主要完成以下功能：
        根据优先级从高到底，下载指定视频
        """
        logging.error(f"download func not finished")

    
    def downloadOne(self):
        """
        这个方法主要完成以下功能：
        根据优先级从高到底，下载任意视频
        """
        pass

    
    def downloadChosen(self,video_id):
        """
        这个方法主要完成以下功能：
        根据给出的节目视频id，下载指定视频
        """
        logging.error(f"download Chosen one video not finished")