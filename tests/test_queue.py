import os

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.config import ConfigManager

from src.service.downloader import Downloader
from src.server.apis.download_api import DownloadApi
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Base, Works


@pytest.fixture()
def db(tmp_path):
    """把 DatabaseManager 指到临时库，测试后还原"""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    DatabaseManager.engine = engine
    DatabaseManager.SessionLocal = sessionmaker(bind=engine)
    yield engine
    DatabaseManager.engine = None
    DatabaseManager.SessionLocal = None
    engine.dispose()


def _add(**kw):
    with DatabaseManager.get_db_session() as s:
        s.add(Works(**kw))


def _state(work_number, website="pixiv"):
    with DatabaseManager.get_db_session() as s:
        return s.get(Works, (work_number, website)).state


def test_claim_orders_by_priority_and_skips_states(db):
    _add(workNumber="A", website="pixiv", state="inQueue", downloadPriority=0)
    _add(workNumber="B", website="pixiv", state="inQueue", downloadPriority=5)
    _add(workNumber="C", website="pixiv", state="stopped", downloadPriority=9)
    _add(workNumber="D", website="pixiv", state=None)

    d = Downloader()
    first = d._claim_next_work('pixiv')
    assert (first["workNumber"], first["state"]) == ("B", "downloading")
    assert d._claim_next_work("pixiv")["workNumber"] == "A"
    assert d._claim_next_work("pixiv")["workNumber"] == "D"  # NULL 视为待下载
    assert d._claim_next_work('pixiv') is None  # 只剩 stopped，不被认领


def test_claim_carries_website_and_downloadinfo(db):
    _add(workNumber="W", website="danbooru", state="inQueue", downloadInfo='{"rating":"safe"}')
    d = Downloader()
    work = d._claim_next_work("danbooru")
    assert work["website"] == "danbooru"
    assert work["downloadInfo"] == '{"rating":"safe"}'


def test_finish_marks_done_with_download_date(db):
    _add(workNumber="W", website="pixiv", state="inQueue")
    d = Downloader()
    d._claim_next_work('pixiv')

    d._finish_work("W", "pixiv", success=True)

    with DatabaseManager.get_db_session() as s:
        w = s.get(Works, ("W", "pixiv"))
        assert w.state == "done"
        assert w.downloadDate


def test_finish_marks_failed(db):
    _add(workNumber="W", website="pixiv", state="inQueue")
    d = Downloader()
    d._claim_next_work('pixiv')

    d._finish_work("W", "pixiv", success=False)

    assert _state("W") == "failed"


def test_finish_does_not_overwrite_stopped(db):
    _add(workNumber="W", website="pixiv", state="inQueue")
    d = Downloader()
    d._claim_next_work('pixiv')
    # 模拟下载进行中收到 stop
    with DatabaseManager.get_db_session() as s:
        s.get(Works, ("W", "pixiv")).state = "stopped"

    d._finish_work("W", "pixiv", success=True)

    assert _state("W") == "stopped"


def test_requeue_stale_downloading(db):
    _add(workNumber="W", website="pixiv", state="downloading")
    _add(workNumber="V", website="pixiv", state="done")

    Downloader()._requeue_stale_downloading('pixiv')

    assert _state("W") == "inQueue"
    assert _state("V") == "done"  # 已完成的不受影响


def test_requeue_api_endpoint(db):
    _add(workNumber="W", website="pixiv", state="failed")

    app = Flask(__name__)
    app.register_blueprint(DownloadApi().blueprint)
    client = app.test_client()

    resp = client.post("/api/download/requeue_work", json={"workNumber": "W", "website": "pixiv"})
    assert resp.status_code == 200
    assert _state("W") == "inQueue"

    resp = client.post("/api/download/requeue_work", json={"workNumber": "ghost", "website": "pixiv"})
    assert resp.status_code == 404


# ---------- 下载路径包装（缓存/直写） ----------

class FakeWorker:
    """按 download_path 写一个文件，返回相对路径；cache_missing 控制不返回路径"""
    written = []

    def __init__(self, work_info, download_path, download_info=None):
        self.download_path = download_path

    def download_it(self):
        path = os.path.join(self.download_path, "img.bin")
        os.makedirs(self.download_path, exist_ok=True)
        with open(path, "w") as f:
            f.write("data")
        FakeWorker.written.append(path)
        return "img.bin"


class FakeNoneWorker(FakeWorker):
    def download_it(self):
        return None


class FakeDispatcher:
    def __init__(self, worker):
        self.worker = worker

    def get(self, website):
        return self.worker


@pytest.fixture()
def cache_env(tmp_path, monkeypatch):
    final_root = tmp_path / "final"
    cache_root = tmp_path / "cache"
    ConfigManager.config_dict["download_setting"] = {
        "use_cache": True,
        "download_path": str(final_root),
        "cache_path": str(cache_root),
        "waiting_play": False,
        "sleep_second": 0,
    }
    yield {"final": final_root, "cache": cache_root}
    ConfigManager.config_dict.pop("download_setting", None)


def _run_with(d, worker, monkeypatch, work_number="W", website="pixiv"):
    FakeWorker.written = []
    monkeypatch.setattr(d, "dispatcher", FakeDispatcher(worker))
    d._run_download_task({"workNumber": work_number, "website": website, "downloadInfo": None})


def test_cache_on_copies_to_final_and_cleans(db, cache_env, monkeypatch):
    _add(workNumber="W", website="pixiv", state="downloading")
    d = Downloader()
    _run_with(d, FakeWorker, monkeypatch)

    final_file = cache_env["final"] / "pixiv" / "pixiv_W" / "img.bin"
    assert final_file.read_text() == "data"           # 产物已拷贝到最终路径
    assert not (cache_env["cache"] / "pixiv_W").exists()  # 缓存工作目录已清理
    assert _state("W") == "done"


def test_cache_off_writes_final_directly(db, cache_env, monkeypatch):
    ConfigManager.config_dict["download_setting"]["use_cache"] = False
    _add(workNumber="W", website="pixiv", state="downloading")
    d = Downloader()
    _run_with(d, FakeWorker, monkeypatch)

    assert (cache_env["final"] / "pixiv" / "pixiv_W" / "img.bin").read_text() == "data"
    assert not (cache_env["cache"] / "pixiv_W").exists()  # 全程没碰缓存
    assert _state("W") == "done"


def test_cache_on_without_payload_marks_failed(db, cache_env, monkeypatch):
    _add(workNumber="W", website="pixiv", state="downloading")
    d = Downloader()
    _run_with(d, FakeNoneWorker, monkeypatch)

    assert _state("W") == "failed"                    # 缓存模式必须返回产物路径


def test_unsafe_work_dir_name_sanitized():
    assert Downloader._work_dir_name("pixiv", "a/b:c?") == "pixiv_a_b_c_"


# ---------- 每站点独立配置 ----------

def test_site_setting_overrides_and_falls_back():
    ConfigManager.config_dict["download_setting"] = {
        "sleep_second": 10,
        "waiting_play": False,
        "download_path": "./global/${BASE_PATH}/dl",
    }
    ConfigManager.config_dict["download_sites"] = {
        "pixiv": {"sleep_second": 3, "download_path": "./site/${BASE_PATH}/dl"},
    }
    # 站点段覆盖
    assert Downloader.site_setting("pixiv", "sleep_second") == 3
    # 未配置的站点回落全局
    assert Downloader.site_setting("danbooru", "sleep_second") == 10
    # 站点段未写的键回落全局
    assert Downloader.site_setting("pixiv", "waiting_play") is False
    # 覆盖值同样做 ${BASE_PATH} 替换
    assert Downloader.site_setting("pixiv", "download_path") == f"./site/{ConfigManager.base_path}/dl"


def test_claim_isolated_per_site(db):
    # danbooru 优先级更高，但按站点认领互不越界
    _add(workNumber="P1", website="pixiv", state="inQueue", downloadPriority=0)
    _add(workNumber="D1", website="danbooru", state="inQueue", downloadPriority=9)

    d = Downloader()
    assert d._claim_next_work("pixiv")["workNumber"] == "P1"
    assert d._claim_next_work("danbooru")["workNumber"] == "D1"


def test_pending_sites(db):
    _add(workNumber="P1", website="pixiv", state="inQueue")
    _add(workNumber="P2", website="pixiv", state="done")
    _add(workNumber="D1", website="danbooru", state="stopped")

    assert Downloader()._pending_sites() == {"pixiv"}  # 只有存在待下载作品的站点
