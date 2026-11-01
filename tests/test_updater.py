"""Updater 的站点级配置与每站点调度测试。"""

from datetime import datetime
from threading import Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.config import ConfigManager
from src.service.updater import Updater
from src.utils.threadPool.threadPool import ThreadPool
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Base, PublishPos, Works, Upload


@pytest.fixture()
def db(tmp_path):
    """DatabaseManager 指向临时库，测试后还原"""
    engine = create_engine(f"sqlite:///{tmp_path / 'u.db'}")
    Base.metadata.create_all(engine)
    DatabaseManager.engine = engine
    DatabaseManager.SessionLocal = sessionmaker(bind=engine)
    yield engine
    DatabaseManager.engine = None
    DatabaseManager.SessionLocal = None
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_config():
    saved = dict(ConfigManager.config_dict)
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict["update_setting"] = {
        "do_update": True, "update_thread": 1, "update_interval": 3600, "commit_interval": 0,
    }
    yield
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict.update(saved)


def test_site_setting_overrides_and_falls_back():
    ConfigManager.config_dict["update_sites"] = {
        "pixiv": {"update_thread": 3, "update_interval": -1},
    }
    assert Updater.site_setting("pixiv", "update_thread") == 3       # 站点覆盖
    assert Updater.site_setting("danbooru", "update_thread") == 1    # 未配置回落全局
    assert Updater.site_setting("pixiv", "commit_interval") == 0     # 站点段未写的键回落全局


def test_pending_positions_per_site(db):
    with DatabaseManager.get_db_session() as s:
        s.add_all([
            PublishPos(authorId="p1", website="pixiv", state="inQueue"),
            PublishPos(authorId="p2", website="pixiv", state="stopped"),
            PublishPos(authorId="d1", website="danbooru", state="inQueue"),
        ])

    u = Updater()
    pixiv = u._pending_positions("pixiv")
    assert [p["authorId"] for p in pixiv] == ["p1"]        # 只查本站、且过滤 stopped
    assert u._pending_positions("danbooru")[0]["authorId"] == "d1"


def test_update_position_inserts_and_stops_incrementally(db):
    with DatabaseManager.get_db_session() as s:
        s.add(PublishPos(authorId="p1", website="pixiv", state="inQueue"))

    class FakeUpdateUser:
        def __init__(self, usr, logging):
            self.works = [{"workid": "w1", "title": "A"}, {"workid": "w2", "title": "B"}]

        def __iter__(self):
            self.works = [{"workid": "w1", "title": "A"}, {"workid": "w2", "title": "B"}]
            return self

        def __next__(self):
            if self.works:
                return self.works.pop(0)
            raise StopIteration

    class FakeDispatcher:
        def get(self, website):
            return FakeUpdateUser

    u = Updater()
    u.dispatcher = FakeDispatcher()

    pos = {"authorId": "p1", "website": "pixiv", "addTime": None}
    assert u._update_position(pos) == 2   # 首次：两个作品入库

    with DatabaseManager.get_db_session() as s:
        assert s.query(Works).count() == 2
        assert s.query(Upload).count() == 2

    # 第二次：第一个关联已存在 → 增量停止，新增 0
    assert u._update_position(pos) == 0
    assert u._update_position(pos) == 0   # 幂等


def test_incremental_stop_at_first_known_link(db):
    """脚本产出从新到旧：撞到第一条已知关联即停止（w2 未入库）"""
    with DatabaseManager.get_db_session() as s:
        s.add(PublishPos(authorId="p1", website="pixiv", state="inQueue"))
        s.add(Works(workNumber="old", website="pixiv", state="inQueue"))
        s.add(Upload(website="pixiv", authorId="p1", workNumber="old"))

    produced = {"items": [{"workid": "new"}, {"workid": "old"}, {"workid": "older"}]}

    class FakeUpdateUser:
        def __init__(self, usr, logging):
            self.items = list(produced["items"])

        def __iter__(self):
            return self

        def __next__(self):
            if self.items:
                return self.items.pop(0)
            raise StopIteration

    class FakeDispatcher:
        def get(self, website):
            return FakeUpdateUser

    u = Updater()
    u.dispatcher = FakeDispatcher()
    processed = u._update_position({"authorId": "p1", "website": "pixiv", "addTime": None})

    assert processed == 1   # new 入库后撞到 old → 停止
    with DatabaseManager.get_db_session() as s:
        assert s.query(Works).count() == 2   # old + new；older 未被处理
