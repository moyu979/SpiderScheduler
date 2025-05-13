import component.template.update_a_user as update_a_user
import component.assistant.BrowserFactory as BrowserFactory
import component.assistant.database as db
import threading 
import sqlite3
from component.register import Register as Register
from bs4 import BeautifulSoup
import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
class Updater(update_a_user.UpdateUser):
    def __init__(self, user_id):
        super().__init__(user_id)
        
    def get_one_page(self):
        logging.info(f"get user {self.uid} page {self.page}")
        broswer = BrowserFactory.BrowserFactory.get_browser()
        if self.page == 1:
            herf=f"https://www.pixiv.net/users/{self.uid}/artworks"
        else:
            herf=f"https://www.pixiv.net/users/{self.uid}/artworks?p={self.page}"
        broswer.get(herf)
        html_content = broswer.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        pics=soup.find_all(class_="sc-iasfms-1 jthKhf")
        for pic in pics:
            workNumber=pic.find("a").get("href").replace("/artworks/","")
            title=pic.text
            a_pic=(0, workNumber, title, "normal", "inQueue", "0", "0")
            self.works.append(a_pic)
        broswer.quit()


if __name__ == "__main__":
    reg=Register(Updater(0))
    user_id = 123456  # Replace with the actual user ID you want to update
    BrowserFactory.BrowserFactory.init_cookie()
    reg.add_a_user(123456)
