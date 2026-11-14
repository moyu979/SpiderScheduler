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
    """预置 update 配置段，测试后还原全局配置字典。"""
    saved = dict(ConfigManager.config_dict)
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict["update"] = {
        "do_update": True,
        "site": {"default": {"update_thread": 1, "update_interval": 3600,
                             "commit_interval": 0}},
    }
    yield
    ConfigManager.config_dict.clear()
    ConfigManager.config_dict.update(saved)


def test_site_setting_overrides_and_falls_back():
    """测试 site_setting 两层回落：站点覆盖优先，未配置键回落 default。"""
    # 只加站点段，保留 fixture 预置的 site.default
    ConfigManager.config_dict["update"]["site"]["pixiv"] = {"update_thread": 3, "update_interval": -1}
    assert Updater.site_setting("pixiv", "update_thread") == 3       # 站点覆盖
    assert Updater.site_setting("danbooru", "update_thread") == 1    # 未配置回落 default
    assert Updater.site_setting("pixiv", "commit_interval") == 0     # 站点段未写的键回落 default


def test_pending_positions_per_site(db):
    """测试待更新位点按站点查询且过滤 stopped 状态。"""
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
    """测试首次同步入库 works/upload，重复调用增量停止且幂等。"""
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


def test_update_position_injects_page_interval(db, tmp_path, monkeypatch):
    """框架把解析好的翻页间隔灌给 updater 脚本：站点覆盖优先于 default"""
    from src.service.dispatcher import ScriptDispatcher

    ConfigManager.config_dict["update"] = {
        "do_update": True,
        "site": {"default": {"page_interval": 5}, "pixiv": {"page_interval": 3.5}},
    }
    probe = tmp_path / "probe.txt"
    monkeypatch.setenv("PAGE_INTERVAL_PROBE", str(probe))
    script = tmp_path / "probe_updater.py"
    script.write_text('''
import os


class ProbeUpdater:
    website = "pixiv"
    cookie_manager = None

    def __init__(self, usr, logging):
        self.website = usr.get("website")

    def __iter__(self):
        # 记录框架注入的翻页间隔后立即结束迭代（0 作品）
        with open(os.environ["PAGE_INTERVAL_PROBE"], "w") as f:
            f.write(str(self.page_interval))
        return iter(())
''', encoding='utf-8')

    u = Updater()
    u.dispatcher = ScriptDispatcher(sources=[str(script)], fallback_class_name="NoSuchClass")
    pos = {"authorId": "a", "website": "pixiv", "addTime": "t"}
    assert u._update_position(pos) == 0
    assert probe.read_text() == "3.5"      # 站点覆盖优先

    # 撤掉站点覆盖 → 回落 site.default
    ConfigManager.config_dict["update"]["site"]["pixiv"].pop("page_interval")
    probe.write_text("")
    assert u._update_position(pos) == 0
    assert probe.read_text() == "5.0"


# ---------- 立即更新（绕过轮次调度） ----------

def _wait_status(u, key, timeout=5):
    """轮询等待立即更新任务离开 running 态，返回最终状态"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = u.manual_status().get(key)
        if st and st["state"] != "running":
            return st
        time.sleep(0.05)
    return u.manual_status().get(key)


def test_update_position_now_runs_and_records(db, tmp_path):
    """测试立即更新异步执行、状态记录与 downloadInfo（作者+作品号）写入。"""
    from src.service.dispatcher import ScriptDispatcher
    from src.utils.database.models import Upload, Works

    with DatabaseManager.get_db_session() as s:
        s.add(PublishPos(authorId="a", website="pixiv", state="inQueue"))
    script = tmp_path / "now_updater.py"
    script.write_text('''
class NowUpdater:
    website = "pixiv"
    cookie_manager = None

    def __init__(self, usr, logging):
        self.website = usr.get("website")
        self.author_id = usr.get("authorId")

    def __iter__(self):
        return iter([{"workid": "NOW1", "title": "t", "kind": "normal",
                      "upTime": "", "state": None, "downloadPriority": 0}])
''', encoding='utf-8')
    u = Updater()
    u.dispatcher = ScriptDispatcher(sources=[str(script)], fallback_class_name="NoSuchClass")

    result = u.update_position_now("pixiv", "a")
    assert result["started"] is True
    status = _wait_status(u, "pixiv|a")
    assert status["state"] == "done" and status["added"] == 1

    with DatabaseManager.get_db_session() as s:
        work = s.get(Works, ("NOW1", "pixiv"))
        assert work is not None
        assert s.get(Upload, ("pixiv", "a", "NOW1")) is not None
        # downloadInfo：作者 + 作品号（对 bilibili 即作者 + BV 号）
        import json
        assert json.loads(work.downloadInfo) == {"authorId": "a", "workNumber": "NOW1"}


def test_update_position_now_merges_yielded_download_info(db, tmp_path):
    """更新器可经 item["downloadInfo"] 产出作品级下载参数：与预置合并落盘，异常形态降级。"""
    import json

    from src.service.dispatcher import ScriptDispatcher
    from src.utils.database.models import Works

    with DatabaseManager.get_db_session() as s:
        s.add(PublishPos(authorId="a", website="pixiv", state="inQueue"))
    script = tmp_path / "merge_updater.py"
    script.write_text('''
class MergeUpdater:
    website = "pixiv"

    def __init__(self, usr, logging):
        self.author_id = usr.get("authorId")

    def __iter__(self):
        yield {"workid": "M1", "downloadInfo": {"quality": "1080p", "authorId": "a"}}
        yield {"workid": "M2", "downloadInfo": "not-a-dict"}
        yield {"workid": "M3"}
        yield {"workid": "M4", "downloadInfo": {"bad": object()}}
''', encoding='utf-8')
    u = Updater()
    u.dispatcher = ScriptDispatcher(sources=[str(script)], fallback_class_name="NoSuchClass")

    result = u.update_position_now("pixiv", "a")
    assert result["started"] is True
    status = _wait_status(u, "pixiv|a")
    assert status["state"] == "done" and status["added"] == 4

    with DatabaseManager.get_db_session() as s:
        # dict 产出：与预置合并，同名键以产出为准
        assert json.loads(s.get(Works, ("M1", "pixiv")).downloadInfo) == {
            "authorId": "a", "workNumber": "M1", "quality": "1080p"}
        # 非 dict：告警并降级为预置
        assert json.loads(s.get(Works, ("M2", "pixiv")).downloadInfo) == {
            "authorId": "a", "workNumber": "M2"}
        # 未产出：预置不变（向后兼容）
        assert json.loads(s.get(Works, ("M3", "pixiv")).downloadInfo) == {
            "authorId": "a", "workNumber": "M3"}
        # 含不可序列化对象：整体降级为预置
        assert json.loads(s.get(Works, ("M4", "pixiv")).downloadInfo) == {
            "authorId": "a", "workNumber": "M4"}


def test_update_position_now_validations(db):
    """测试立即更新对不存在与已停止位点返回对应原因。"""
    with DatabaseManager.get_db_session() as s:
        s.add(PublishPos(authorId="b", website="pixiv", state="stopped"))

    u = Updater()
    assert u.update_position_now("pixiv", "ghost")["reason"] == "not_found"
    assert u.update_position_now("pixiv", "b")["reason"] == "stopped"
