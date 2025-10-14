import os
import sqlite3
import shutil
from datetime import datetime
from src.utils.database.database import DatabaseManager
from src.utils.logging.logger import SpiderLogger as logger

def init_database():
    logger.info("开始初始化数据库")
    DatabaseManager.init_database()