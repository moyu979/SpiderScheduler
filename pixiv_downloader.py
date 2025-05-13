from time import sleep
import component.template.download_a_work as download_a_work
import component.assistant.BrowserFactory as BrowserFactory
from component.assistant.database import Database as db
import component.assistant.initer
import threading 
import sqlite3
from component.assistant.data import Config as datas
from component.register import Register as Register
from bs4 import BeautifulSoup
import logging
import os
import requests
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

class Downloader(download_a_work.DownloadWork):
    def __init__(self, work_number):
        super().__init__(work_number)
        
    def download_it(self):
        conn=sqlite3.connect(db.db_path)
        cursor=conn.cursor()
        cursor.execute("SELECT * FROM works WHERE workNumber=?", (self.work_id,))
        data=cursor.execute("SELECT * FROM works WHERE workNumber=?",(self.work_id,)).fetchall()
        conn.close()
        if len(data)==0:
            work_name,work_kind=self.get_info_by_id(self.work_id)
            conn=sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO works (workNumber,title,kind,state) VALUES (?,?,?,?)",(self.work_id,work_name,work_kind,"inQueue")).fetchall()
            data=cursor.execute("SELECT * FROM works WHERE workNumber=?",(self.work_id,)).fetchall()
            conn.commit()
            conn.close()
        data=data[0]
        self._download(data)
        return "success"
    def get_info_by_id(self,video_id):
        """
        这个方法主要完成以下功能：
        给定的视频号，获得视频标题和类型,可以不写
        """
        return "",""
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
        self.driver=BrowserFactory.BrowserFactory.get_browser(headless=False)
        self.driver.get(f"https://www.pixiv.net/artworks/{work_id}")
        #sleep(3)
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

                adata=img.find("img")
                if adata is not None:
                    url=adata.get("src")
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
        self.driver.quit()
        return True
    def _get_user(self,data):
        conn=sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        res=cursor.execute("select * from upload where workNumber=?",(data[1],)).fetchall()
        conn.close()
        if len(res)==0:
            return 0
        else:
            return res[0][0] 
if __name__ == "__main__":

    d=Downloader("13598770").download_it()