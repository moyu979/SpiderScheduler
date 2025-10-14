import os
import sqlite3
import shutil
from datetime import datetime
import src.config.config as config
from src.config.globalVars import db_path
from src.utils.logging.logger import SpiderLogger as logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
class DatabaseManager:
    """数据库管理器"""
    SessionLocal=None
    engine=None
    @classmethod
    def init_database(cls):
        cls.db_path = db_path
        """初始化数据库"""
        if not os.path.exists(cls.db_path):
            logger.error(f"数据库文件不存在: {cls.db_path}")
            init_sql_path = os.path.join(os.path.dirname(__file__), 'init.sql')
            with open(init_sql_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            cls._create_database(sql_content)
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            echo=True,
            connect_args={"check_same_thread": False}
        )

        cls.SessionLocal = sessionmaker(bind=cls.engine)

    @classmethod
    def _create_database(cls, sql_content):
        """创建新数据库"""
        try:
            # 确保数据库目录存在
            db_dir = os.path.dirname(cls.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"创建数据库目录: {db_dir}")
            
            # 创建数据库连接
            cls.connection = sqlite3.connect(cls.db_path)
            cursor = cls.connection.cursor()
            
            # 执行SQL语句
            cursor.executescript(sql_content)
            cls.connection.commit()
            
            cursor.close()
            cls.connection.close()
            
            logger.info(f"成功创建数据库: {cls.db_path}")
            return True
            
        except Exception as e:
            logger.error(f"创建数据库失败: {e}")
            if cls.connection:
                cls.connection.close()
            return False
