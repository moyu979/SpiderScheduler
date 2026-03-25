import os
from contextlib import contextmanager
from typing import Generator
from src.config.config import config_manager
from sqlalchemy.orm import Session
from src.config.paths import db_path as _global_db_path
from src.utils.logging.logger import SpiderLogger as logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.utils.database.models import Base


class DatabaseManager:
    """数据库管理器"""
    SessionLocal = None
    engine = None

    @classmethod
    def init_database(cls):
        """初始化数据库"""
        # paths.py 的 db_path 是函数，这里要调用获取实际路径
        cls.db_path = _global_db_path()
        
        # 确保数据库目录存在（仅适用于本地文件型 SQLite：cls.db_path 应为可映射到本机文件系统的路径。
        # 若未来改为远程数据库/IP/连接串形式，这段 dirname/makedirs 逻辑可能失效或产生不可预期的行为）
        db_dir = os.path.dirname(cls.db_path)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"创建数据库目录: {db_dir}")
        

        db_url = config_manager.get('database', 'url').replace('${DB_PATH}', _global_db_path())
        # 创建数据库引擎
        cls.engine = create_engine(
            #f"sqlite:///{cls.db_path}",
            db_url,
            echo=True,
            connect_args={"check_same_thread": False}
        )

        # 使用ORM创建所有表（如果不存在）
        is_new_database = not os.path.exists(cls.db_path)
        Base.metadata.create_all(bind=cls.engine)
        
        if is_new_database:
            logger.info(f"成功创建数据库: {cls.db_path}")
        else:
            logger.info(f"数据库已存在: {cls.db_path}")

        # 创建会话工厂
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    @classmethod
    @contextmanager
    def get_db_session(cls) -> Generator[Session, None, None]:
        """
        数据库会话上下文管理器
        
        自动处理会话的创建、提交、回滚和关闭
        使用示例:
            with DatabaseManager.get_db_session() as session:
                work = session.query(Works).first()
                work.state = 'downloading'
                # 自动提交（如果没有异常）
        """
        if cls.SessionLocal is None:
            raise RuntimeError("数据库未初始化，请先调用 DatabaseManager.init_database()")
        
        session = cls.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败，已回滚: {e}")
            raise
        finally:
            session.close()
