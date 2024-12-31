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
        self.conn=sqlite3.connect(os.path.join(datas.conf["data_path"],f"{datas.conf["db_name"]}"), check_same_thread=False)
        self.cursor = self.conn.cursor()

        self.continue_download=True
        self.working=False

    def downloadOne(self):
        logging.error(f"download one video not finished")

    def downloadChosen(self,video_id):
        logging.error(f"download Chosen one video not finished")

    def downloadAll(self):
        logging.error(f"download all video not finished")

    def downloadSome(self,download_number=10):
        logging.error(f"download some video not finished")

    def downloadUser(self,user_id):
        logging.error(f"download user video not finished")

    def download(self,data):
        logging.error(f"download func not finished")

    def priority(self,video_number):
        logging.error(f"download priority not finished")