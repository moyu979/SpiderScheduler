"""ORM 模型测试：表结构、联合主键与外键约束行为。
"""
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.utils.database.models import Base, PublishPos, Works, Upload


@pytest.fixture()
def engine():
    """内存 SQLite 引擎（开启外键约束），建表后 yield，测试完销毁。"""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_works_has_downloadinfo_column(engine):
    """测试 works 表 DDL 含 downloadInfo 列。"""
    with engine.connect() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='works'")).scalar()
    assert "downloadInfo" in ddl


def test_upload_uses_composite_foreign_keys(engine):
    """测试 upload 表使用指向 publish_pos 与 works 的复合外键。"""
    with engine.connect() as conn:
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='upload'")).scalar()
    assert 'FOREIGN KEY("authorId", website) REFERENCES publish_pos ("authorId", website)' in ddl
    assert 'FOREIGN KEY("workNumber", website) REFERENCES works ("workNumber", website)' in ddl


def test_orphan_upload_rejected(engine):
    """测试孤儿 upload（无对应 author/work）触发外键约束被拒绝。"""
    session = sessionmaker(bind=engine)
    with session() as s:
        s.add(Upload(website="pixiv", authorId="ghost", workNumber="w1"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_same_work_number_across_websites(engine):
    """测试同一作品号可共存于不同站点（复合主键含 website）。"""
    session = sessionmaker(bind=engine)
    with session() as s:
        s.add(Works(workNumber="w1", website="pixiv", downloadInfo='{"quality":"original"}'))
        s.add(Works(workNumber="w1", website="danbooru"))
        s.commit()
        assert s.query(Works).count() == 2


def test_relationship_navigation(engine):
    """测试复合外键下的 ORM 关系导航（uploads/pos/work）与 downloadInfo 读取。"""
    session = sessionmaker(bind=engine)
    with session() as s:
        s.add(PublishPos(authorId="u1", website="pixiv", addTime="2026-10-31T00:00:00", state="inQueue"))
        s.add(Works(workNumber="w1", website="pixiv", downloadInfo='{"quality":"original"}'))
        s.add(Upload(website="pixiv", authorId="u1", workNumber="w1"))
        s.commit()

        pos = s.get(PublishPos, ("u1", "pixiv"))
        w = s.get(Works, ("w1", "pixiv"))
        up = s.get(Upload, ("pixiv", "u1", "w1"))
        assert pos.uploads and w.uploads
        assert up.pos.authorId == "u1" and up.work.workNumber == "w1"
        assert w.downloadInfo == '{"quality":"original"}'
