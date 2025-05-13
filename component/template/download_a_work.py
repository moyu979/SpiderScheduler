
#这是下载功能的一个模板，需要重写download_it方法，功能为下载self.work_id对应的作品
from abc import ABC, abstractmethod
import time
import logging  

class DownloadWork(ABC):
    def __init__(self, work_id):
        self.work_id = work_id

    @abstractmethod
    def download_it(self,path=None):
        logging.info(f"download work {self.work_id}")
        
        time.sleep(10)
