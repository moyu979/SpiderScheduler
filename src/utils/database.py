import os
import sqlite3
import shutil
from datetime import datetime
from .config import get_path
from .logger import logger

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self):
        self.db_path = get_path('DB_FILE')
        # init.sql在database.py的同级目录
        self.init_sql_path = os.path.join(os.path.dirname(__file__), 'init.sql')
        self.connection = None
    
    def _read_init_sql(self):
        """读取并格式化init.sql文件"""
        try:
            if not os.path.exists(self.init_sql_path):
                logger.error(f"init.sql文件不存在: {self.init_sql_path}")
                return None
            
            with open(self.init_sql_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            
            logger.info(f"成功读取init.sql文件: {self.init_sql_path}")
            return sql_content
            
        except Exception as e:
            logger.error(f"读取init.sql文件失败: {e}")
            return None
    
    def _parse_table_structure(self, sql_content):
        """解析SQL文件中的表结构"""
        tables = {}
        try:
            # 简单的SQL解析，提取CREATE TABLE语句
            lines = sql_content.split('\n')
            current_table = None
            current_columns = []
            
            for line in lines:
                line = line.strip()
                if line.upper().startswith('CREATE TABLE'):
                    # 保存前一个表的信息
                    if current_table:
                        tables[current_table] = current_columns
                    
                    # 开始新表
                    table_name = line.split()[2].strip('`"[]')
                    current_table = table_name
                    current_columns = []
                    
                elif line.upper().startswith('PRIMARY KEY') or line.upper().startswith('FOREIGN KEY'):
                    # 跳过约束定义
                    continue
                elif line and not line.startswith('--') and not line.startswith('/*'):
                    # 解析列定义
                    if '`' in line or '"' in line:
                        # 提取列名
                        parts = line.split()
                        if parts:
                            column_name = parts[0].strip('`"[]')
                            if column_name and not column_name.upper().startswith('PRIMARY'):
                                current_columns.append(column_name)
            
            # 保存最后一个表
            if current_table:
                tables[current_table] = current_columns
            
            logger.info(f"解析到 {len(tables)} 个表结构")
            for table_name, columns in tables.items():
                logger.debug(f"表 {table_name}: {', '.join(columns)}")
            
            return tables
            
        except Exception as e:
            logger.error(f"解析表结构失败: {e}")
            return {}
    
    def _check_database_exists(self):
        """检查数据库文件是否存在"""
        return os.path.exists(self.db_path)
    
    def _get_existing_tables(self):
        """获取现有数据库中的表结构"""
        try:
            self.connection = sqlite3.connect(self.db_path)
            cursor = self.connection.cursor()
            
            # 获取所有表名
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            existing_structure = {}
            for (table_name,) in tables:
                # 获取表结构
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                column_names = [col[1] for col in columns]
                existing_structure[table_name] = column_names
            
            cursor.close()
            self.connection.close()
            
            logger.info(f"现有数据库包含 {len(existing_structure)} 个表")
            return existing_structure
            
        except Exception as e:
            logger.error(f"获取现有表结构失败: {e}")
            return {}
    
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
    
    def _compare_table_structures(self, expected_tables, existing_tables):
        """比较表结构是否匹配"""
        mismatched_tables = []
        
        # 检查是否有缺失的表
        for table_name in expected_tables:
            if table_name not in existing_tables:
                mismatched_tables.append(f"缺失表: {table_name}")
                continue
            
            # 检查列是否匹配
            expected_columns = set(expected_tables[table_name])
            existing_columns = set(existing_tables[table_name])
            
            if expected_columns != existing_columns:
                missing_cols = expected_columns - existing_columns
                extra_cols = existing_columns - expected_columns
                mismatch_info = f"表 {table_name} 结构不匹配"
                if missing_cols:
                    mismatch_info += f" (缺失列: {', '.join(missing_cols)})"
                if extra_cols:
                    mismatch_info += f" (多余列: {', '.join(extra_cols)})"
                mismatched_tables.append(mismatch_info)
        
        # 检查是否有多余的表
        for table_name in existing_tables:
            if table_name not in expected_tables:
                mismatched_tables.append(f"多余表: {table_name}")
        
        return mismatched_tables
    
    def init(self):
        """初始化数据库"""
        logger.info("开始初始化数据库")
        
        # 1. 读取并解析init.sql
        sql_content = self._read_init_sql()
        if not sql_content:
            logger.error("无法读取init.sql文件，数据库初始化失败")
            return False
        
        expected_tables = self._parse_table_structure(sql_content)
        if not expected_tables:
            logger.error("无法解析表结构，数据库初始化失败")
            return False
        
        # 2. 检查数据库是否存在
        if self._check_database_exists():
            logger.info(f"数据库文件已存在: {self.db_path}")
            
            # 3. 检查现有表结构
            existing_tables = self._get_existing_tables()
            mismatched_tables = self._compare_table_structures(expected_tables, existing_tables)
            
            if mismatched_tables:
                logger.warning("数据库表结构不匹配，需要重建")
                for mismatch in mismatched_tables:
                    logger.warning(f"  - {mismatch}")
                
                # 备份现有数据库
                backup_path = self._backup_database("结构不匹配")
                if not backup_path:
                    logger.error("备份失败，无法继续初始化")
                    return False
                
                # 删除现有数据库文件
                try:
                    os.remove(self.db_path)
                    logger.info("已删除不匹配的数据库文件")
                except Exception as e:
                    logger.error(f"删除数据库文件失败: {e}")
                    return False
                
                # 创建新数据库
                return self._create_database(sql_content)
            else:
                logger.info("数据库表结构匹配，无需重建")
                return True
        else:
            logger.info(f"数据库文件不存在，将创建新数据库: {self.db_path}")
            return self._create_database(sql_content)
    
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
