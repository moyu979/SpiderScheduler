import os
import sqlite3
import shutil
from datetime import datetime
from database.database import db_manager
import src.configs.config as config
from src.logger import logger

def init_database():
    logger.info("开始初始化数据库")
    db_manager.init_database()