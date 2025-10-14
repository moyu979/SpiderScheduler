from src.utils.logging.logger import SpiderLogger as logger
from src.service.downloader import Downloader
from src.service.updater import Updater



class BackendManager:
    def __init__(self):

        
        logger.info("BackendManager初始化")
        self.downloader = Downloader()
        self.updater = Updater()
        

    def add_user(self):
        pass

    def delete_user(self):
        pass

    def disconnect(self):
        pass