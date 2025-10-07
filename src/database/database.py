import os
import sqlite3
import shutil
from datetime import datetime
import src.configs.config as config
from src.logger import logger

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self):
        pass
    
    def init_database(self):
        self.db_path = config.get("path",'db_file')
        """初始化数据库"""
        if not os.path.exists(self.db_path):
            logger.error(f"数据库文件不存在: {self.db_path}")
            init_sql_path = os.path.join(os.path.dirname(__file__), 'init.sql')
            with open(init_sql_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            self._create_database(sql_content)


    def _backup_database(self, reason):
        """备份数据库文件"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"{self.db_path}.{reason}.{timestamp}.backup"
            shutil.copy2(self.db_path, backup_name)
            logger.info(f"数据库已备份: {backup_name}")
            return backup_name
        except Exception as e:
            logger.error(f"备份数据库失败: {e}")
            return None
    
    def _create_database(self, sql_content):
        """创建新数据库"""
        try:
            # 确保数据库目录存在
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"创建数据库目录: {db_dir}")
            
            # 创建数据库连接
            self.connection = sqlite3.connect(self.db_path)
            cursor = self.connection.cursor()
            
            # 执行SQL语句
            cursor.executescript(sql_content)
            self.connection.commit()
            
            cursor.close()
            self.connection.close()
            
            logger.info(f"成功创建数据库: {self.db_path}")
            return True
            
        except Exception as e:
            logger.error(f"创建数据库失败: {e}")
            if self.connection:
                self.connection.close()
            return False

    def get_connection(self):
        """获取数据库连接"""
        try:
            if not self.connection:
                self.connection = sqlite3.connect(self.db_path)
            return self.connection
        except Exception as e:
            logger.error(f"获取数据库连接失败: {e}")
            return None
    
    def close_connection(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.debug("数据库连接已关闭")

# 创建默认数据库管理器实例
db_manager = DatabaseManager()

def init_database():
    db_manager.init_database()
