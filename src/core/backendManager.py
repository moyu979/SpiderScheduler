from src.utils.logging.logger import logger
from src.core.downloader import Downloader
from src.core.updater import Updater



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