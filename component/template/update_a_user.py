#需要重写，用来更新某个用户信息，需要重写get_one_page方法，内容为一次获取若干内容，并使用page计数，然后存到self.works中
from abc import ABC, abstractmethod
import time
import logging  
class UpdateUser(ABC):
    def __init__(self,uid):
        self.page=1
        self.uid=uid
        self.works=[]
    @abstractmethod
    def get_one_page(self):
        logging.info(f"get user {self.uid} page {self.page}")
        
        time.sleep(10)
        pass

    def __iter__(self):
        self.index = 0      # 每次迭代时重置索引
        return self         # 返回迭代器对象本身

    def __next__(self):
        
        if len(self.works)==0:
            self.get_one_page()
            self.page+=1
        if len(self.works)==0:
            raise StopIteration
        return self.works.pop(0)