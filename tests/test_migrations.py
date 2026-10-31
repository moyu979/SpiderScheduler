import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.utils.database import database as db_module
from src.utils.database.models import Base


def test_migrations_stamp_version_on_fresh_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    db_module.DatabaseManager.engine = engine
    try:
        Base.metadata.create_all(engine)
        db_module.DatabaseManager._run_migrations(is_new=True)

        with engine.connect() as conn:
            version = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        assert version == db_module.HEAD_SCHEMA_VERSION

        # 重复执行应保持幂等
        db_module.DatabaseManager._run_migrations(is_new=False)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        assert version == db_module.HEAD_SCHEMA_VERSION
    finally:
        db_module.DatabaseManager.engine = None
        engine.dispose()


def test_old_user_table_migrated_to_publish_pos(tmp_path):
    """v1 旧库（user 表）→ v2：表和列更名，数据保留"""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    db_module.DatabaseManager.engine = engine
    try:
        with engine.begin() as conn:
            # 手工构造 v1 结构（user 表 + upload 指向 user 的复合外键）
            conn.execute(text('''
                CREATE TABLE works (
                    "workNumber" VARCHAR NOT NULL, website VARCHAR NOT NULL,
                    "upTime" VARCHAR, title VARCHAR, kind VARCHAR, state VARCHAR,
                    "downloadDate" VARCHAR, "downloadPriority" INTEGER, "otherInfo" VARCHAR,
                    downloadInfo VARCHAR, PRIMARY KEY ("workNumber", website))'''))
            conn.execute(text('''
                CREATE TABLE user (
                    "userId" VARCHAR NOT NULL, website VARCHAR NOT NULL,
                    "addTime" VARCHAR, state VARCHAR, PRIMARY KEY ("userId", website))'''))
            conn.execute(text('''
                CREATE TABLE upload (
                    website VARCHAR NOT NULL, "userId" VARCHAR NOT NULL, "workNumber" VARCHAR NOT NULL,
                    PRIMARY KEY (website, "userId", "workNumber"),
                    CONSTRAINT fk_upload_user FOREIGN KEY("userId", website)
                        REFERENCES user ("userId", website) DEFERRABLE INITIALLY DEFERRED,
                    CONSTRAINT fk_upload_works FOREIGN KEY("workNumber", website)
                        REFERENCES works ("workNumber", website) DEFERRABLE INITIALLY DEFERRED)'''))
            conn.execute(text("INSERT INTO user VALUES ('u1', 'pixiv', '2026-03-26T00:25:59', 'inQueue')"))
            conn.execute(text("INSERT INTO upload VALUES ('pixiv', 'u1', 'w1')"))
            conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
            conn.execute(text("INSERT INTO schema_version VALUES (1)"))

        # 旧库上 create_all 会先建出空的 publish_pos，迁移应处理这种情况
        Base.metadata.create_all(engine)
        db_module.DatabaseManager._run_migrations(is_new=False)

        with engine.begin() as conn:
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "publish_pos" in tables and "user" not in tables
            rows = conn.execute(text("SELECT authorId, website, state FROM publish_pos")).fetchall()
            assert rows == [("u1", "pixiv", "inQueue")]  # 数据无损
            upload_rows = conn.execute(text("SELECT website, authorId, workNumber FROM upload")).fetchall()
            assert upload_rows == [("pixiv", "u1", "w1")]
            version = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
            assert version == db_module.HEAD_SCHEMA_VERSION
    finally:
        db_module.DatabaseManager.engine = None
        engine.dispose()


def test_sqlite_pragmas_applied(tmp_path):
    """连接级 PRAGMA：外键开启、busy_timeout 设置、WAL 生效"""
    engine = create_engine(f"sqlite:///{tmp_path / 'pragma.db'}")
    event.listens_for(engine, "connect")(db_module._set_sqlite_pragma)
    Base.metadata.create_all(engine)
    try:
        with engine.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
            busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert fk == 1
        assert busy == 30000
        assert mode == "wal"
    finally:
        engine.dispose()
