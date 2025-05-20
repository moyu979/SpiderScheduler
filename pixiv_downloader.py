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
        sleep(10)
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
        sleep(3)
        #sleep(3)
        html_content = self.driver.page_source
        
        with open(os.path.join(work_save_path,"page.html"),"w",encoding='utf-8') as f:
            f.write(html_content)

        soup = BeautifulSoup(html_content, 'html.parser')
        #找有没有阅读作品的选项，有的话说明是多页
        data=soup.find(class_="sc-9222a8f6-2 kufPoS")

        count=0
        #没有，单页作品
        if data is None:
            main=soup.find(class_="sc-e1dc2ae6-1 fUQgzA")
            url=main.get("src")
            headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                        "Referer": f"https://www.pixiv.net/artworks/{work_id}" # 标明从哪个网页跳转
                    }
            response = requests.get(url,headers=headers)
            if response.status_code == 200:
                with open(os.path.join(work_save_path,f"{count}.png"), "wb") as file:
                    file.write(response.content)
            #all_img=main.find_all("figure")
            
            # for img in all_img:

            #     adata=img.find("img")
            #     if adata is not None:
            #         url=adata.get("src")
            #         headers = {
            #             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            #             "Referer": f"https://www.pixiv.net/artworks/{work_id}" # 标明从哪个网页跳转
            #         }
            #         response = requests.get(url,headers=headers)
            #         if response.status_code == 200:
            #             with open(os.path.join(work_save_path,f"{count}.png"), "wb") as file:
            #                 file.write(response.content)
            #         count=count+1
        else:
            logging.info("多页作品")
            self.driver.get(f"https://www.pixiv.net/artworks/{work_id}#1")
            sleep(3)
            self.driver.refresh()
            html_content = self.driver.page_source
            with open(os.path.join(work_save_path,"page_all.html"),"w",encoding='utf-8') as f:
                f.write(html_content)
            soup = BeautifulSoup(html_content, 'html.parser')
            data=soup.find(class_="sc-cd1ec630-1 bnUbSD")
            if data is None:
                logging.info("没有找到图片")
                self.driver.quit()
                return False
            img_group=data.find_all(class_="gtm-expand-full-size-illust")
            print(img_group)
            count=0
            for a in img_group:
                url=a.get("href")
                print(url)
                if url.endswith(".png") or url.endswith(".jpg") or url.endswith(".jpeg"):
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