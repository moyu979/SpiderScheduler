import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.config.config import config_manager
from src.config.paths import db_path as _global_db_path
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.database.models import Base

# 当前模型对应的 schema 版本。修改 models.py 时：
#   1. 新建 migrations/000N_说明.py，提供 apply(engine) 函数（须幂等）
#   2. 把此常量 +1
# 全新数据库由 create_all 直接建出最新结构；旧库按版本号补跑迁移。
# 版本历史：1 = multiWeb 初始结构；2 = user 表更名为 publish_pos（发布位点）
HEAD_SCHEMA_VERSION = 2


# SQLite 连接级参数：WAL 降低读写互斥、busy_timeout 缓解并发写锁冲突、开启外键约束
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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

        db_conf = config_manager.config_dict.get('database') or {}
        raw_url = str(db_conf.get('url') or '').strip()
        if raw_url and '${DB_PATH}' not in raw_url:
            # 完整连接串（如 Postgres），原样使用
            db_url = raw_url
        else:
            # sqlite 文件路径统一由 paths.py 给出并取绝对路径：
            # yaml 里手拼 "./${DB_PATH}" 在 BASEPATH 为绝对路径时会产生
            # "sqlite:///./tmp/..." 这类按 cwd 误解的畸形 URL
            db_url = f"sqlite:///{os.path.abspath(cls.db_path)}"
        is_new_database = not os.path.exists(cls.db_path)

        # 创建数据库引擎（echo / connect_args 均由 database.yaml 配置）
        cls.engine = create_engine(
            db_url,
            echo=bool(db_conf.get('echo', False)),
            connect_args=cls._build_connect_args(db_conf, db_url),
        )

        # SQLite 运行参数：WAL 降低读写互斥、busy_timeout 缓解并发写锁冲突、开启外键约束
        if cls.engine.dialect.name == "sqlite":
            event.listens_for(cls.engine, "connect")(_set_sqlite_pragma)

        # 使用ORM创建缺失的表（只建不改，结构变更走 migrations）
        Base.metadata.create_all(bind=cls.engine)
        cls._run_migrations(is_new=is_new_database)

        if is_new_database:
            logger.info(f"成功创建数据库: {cls.db_path}")
        else:
            logger.info(f"数据库已存在: {cls.db_path}")

        # 创建会话工厂
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    @classmethod
    def _build_connect_args(cls, db_conf: dict, db_url: str) -> dict:
        """connect_args 来自配置；SQLite 默认关闭同线程检查以支持多线程会话"""
        connect_args = dict(db_conf.get('connect_args') or {})
        if db_url.startswith('sqlite'):
            connect_args.setdefault('check_same_thread', False)
        return connect_args

    @classmethod
    def _run_migrations(cls, is_new: bool):
        """
        schema 版本表 + 顺序迁移。
        迁移文件放在 migrations/ 下，命名 000N_说明.py，提供 apply(engine)；
        已记录版本之后的文件按序补跑，每跑完一个推进版本号。
        """
        migrations_dir = Path(__file__).resolve().parent / "migrations"

        with cls.engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
            current = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
            if current is None:
                # 全新库：create_all 已按当前模型建表，直接记为最新版本；
                # 旧库：从基线版本 1 起步（基线 = 随本版本发布的手工迁移后的结构）
                current = HEAD_SCHEMA_VERSION if is_new else 1
                conn.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": current})
                logger.info(f"schema_version 初始化为 {current}")

        for migration_file in sorted(migrations_dir.glob("0*.py")):
            if migration_file.name.startswith("_"):
                continue
            try:
                version = int(migration_file.name.split("_", 1)[0])
            except ValueError:
                logger.warning(f"跳过无法识别版本号的迁移文件: {migration_file.name}")
                continue
            if version <= current:
                continue

            logger.info(f"应用数据库迁移 {migration_file.name} (v{version})")
            spec = importlib.util.spec_from_file_location(f"db_migration_{version}", migration_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.apply(cls.engine)
            with cls.engine.begin() as conn:
                conn.execute(text("UPDATE schema_version SET version = :v"), {"v": version})
            current = version

    @classmethod
    @contextmanager
    def get_db_session(cls) -> Generator[Session, None, None]:
        """数据库会话上下文管理器：退出提交、异常回滚、最后关闭。

        注意：提交后 ORM 对象即过期，跨会话使用数据必须在会话内拷贝成 dict。

        使用示例:
            with DatabaseManager.get_db_session() as session:
                work = session.query(Works).first()
                work.state = 'downloading'
                # 自动提交（如果没有异常）

        Yields:
            Session: 已绑定引擎的 SQLAlchemy 会话。

        Raises:
            RuntimeError: 数据库尚未初始化（未调用 init_database）。
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
