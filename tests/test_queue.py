"""下载队列测试：认领/收尾/重排语义、缓存交付、时间窗口与线程池行为。
"""
import os
from datetime import datetime
from threading import Thread

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.config import ConfigManager, GetUnknownKey
from src.utils.threadPool.threadPool import ThreadPool

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
    ConfigManager.config_dict["download"] = {
        "site": {"default": {
            "use_cache": True,
            "download_path": str(final_root),
            "cache_path": str(cache_root),
            "waiting_play": False,
            "sleep_second": 0,
        }},
    }
    yield {"final": final_root, "cache": cache_root}
    ConfigManager.config_dict.pop("download", None)


def _run_with(d, worker, monkeypatch, work_number="W", website="pixiv"):
    FakeWorker.written = []
    monkeypatch.setattr(d, "dispatcher", FakeDispatcher(worker))
    d._run_download_task({"workNumber": work_number, "website": website, "downloadInfo": None})


def test_cache_on_copies_to_final_and_cleans(db, cache_env, monkeypatch):
    _add(workNumber="W", website="pixiv", state="downloading")
    d = Downloader()
    _run_with(d, FakeWorker, monkeypatch)

    final_file = cache_env["final"] / "pixiv" / "W" / "img.bin"
    assert final_file.read_text() == "data"           # 产物已拷贝到最终路径（站点/作品两级目录）
    assert not (cache_env["cache"] / "pixiv" / "W").exists()  # 缓存工作目录已清理
    assert _state("W") == "done"


def test_cache_off_writes_final_directly(db, cache_env, monkeypatch):
    ConfigManager.config_dict["download"]["site"]["default"]["use_cache"] = False
    _add(workNumber="W", website="pixiv", state="downloading")
    d = Downloader()
    _run_with(d, FakeWorker, monkeypatch)

    assert (cache_env["final"] / "pixiv" / "W" / "img.bin").read_text() == "data"
    assert not (cache_env["cache"] / "pixiv").exists()  # 全程没碰缓存
    assert _state("W") == "done"


def test_cache_on_without_payload_marks_failed(db, cache_env, monkeypatch):
    _add(workNumber="W", website="pixiv", state="downloading")
    d = Downloader()
    _run_with(d, FakeNoneWorker, monkeypatch)

    assert _state("W") == "failed"                    # 缓存模式必须返回产物路径


def test_unsafe_work_subdir_sanitized():
    assert Downloader._work_subdir("a/b:c?") == "a_b_c_"


# ---------- 每站点独立配置 ----------

def test_site_setting_site_overrides_default():
    """两层回落：site.<website> > site.default"""
    ConfigManager.config_dict["download"] = {
        "site": {
            "default": {"sleep_second": 7, "waiting_play": False,
                        "download_path": "./def/${BASE_PATH}/dl"},
            "pixiv": {"sleep_second": 3, "download_path": "./site/${BASE_PATH}/dl"},
        },
    }
    # 站点段最优先
    assert Downloader.site_setting("pixiv", "sleep_second") == 3
    # 未单独配置的站点回落 default
    assert Downloader.site_setting("danbooru", "sleep_second") == 7
    # 站点段未写的键回落 default
    assert Downloader.site_setting("pixiv", "waiting_play") is False
    assert Downloader.site_setting("danbooru", "waiting_play") is False
    # 两层的覆盖值同样做 ${BASE_PATH} 替换
    assert Downloader.site_setting("pixiv", "download_path") == f"./site/{ConfigManager.base_path}/dl"
    assert Downloader.site_setting("danbooru", "download_path") == f"./def/{ConfigManager.base_path}/dl"


def test_site_setting_code_fallback():
    """三层兜底：site.<website> > site.default > 代码内置默认值（default 参数）"""
    ConfigManager.config_dict["download"] = {"site": {"pixiv": {}}}
    # 两层全缺 + 给 default → 返回代码兜底值，不抛异常
    assert Downloader.site_setting("pixiv", "sleep_second", 10) == 10
    # 两层全缺 + 未给 default → GetUnknownKey（带定位信息）
    with pytest.raises(GetUnknownKey):
        Downloader.site_setting("pixiv", "sleep_second")
    # 低层有值时代码兜底不生效
    ConfigManager.config_dict["download"]["site"]["default"] = {"sleep_second": 7}
    assert Downloader.site_setting("pixiv", "sleep_second", 10) == 7


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


# ---------- 可下载时间窗口 ----------

def _window(site_window, now, website="pixiv"):
    ConfigManager.config_dict["download"] = {"site": {website: {"download_window": site_window}}}
    return Downloader._in_download_window(website, now=now)


def test_window_unset_always_allows():
    ConfigManager.config_dict["download"] = {"site": {"pixiv": {}}}
    assert Downloader._in_download_window("pixiv", now=datetime(2026, 11, 1, 12, 0)) is True


def test_daily_window_inside_and_outside():
    win = {"mode": "daily", "start": "00:00", "end": "08:00"}
    assert _window(win, datetime(2026, 11, 1, 3, 0)) is True
    assert _window(win, datetime(2026, 11, 1, 12, 0)) is False


def test_daily_window_overnight_wrap():
    win = {"mode": "daily", "start": "22:00", "end": "06:00"}
    assert _window(win, datetime(2026, 11, 1, 23, 0)) is True
    assert _window(win, datetime(2026, 11, 2, 5, 0)) is True
    assert _window(win, datetime(2026, 11, 2, 12, 0)) is False


def test_weekly_window_matches_isoweekday():
    win = {"mode": "weekly", "start": "00:00", "end": "23:59", "weekdays": [1]}
    monday = datetime(2026, 11, 2, 3, 0)   # isoweekday=1
    tuesday = datetime(2026, 11, 3, 3, 0)  # isoweekday=2
    assert monday.isoweekday() == 1 and tuesday.isoweekday() == 2  # 测试内置事实校验
    assert _window(win, monday) is True
    assert _window(win, tuesday) is False


def test_monthly_window_with_negative_days():
    win = {"mode": "monthly", "start": "00:00", "end": "23:59", "month_days": [1, -1]}
    # 2026 年 2 月有 28 天：-1 = 28 号
    assert _window(win, datetime(2026, 2, 1, 12, 0)) is True
    assert _window(win, datetime(2026, 2, 28, 12, 0)) is True
    assert _window(win, datetime(2026, 2, 27, 12, 0)) is False
    assert _window(win, datetime(2026, 3, 31, 12, 0)) is True   # 3 月的 -1 = 31 号


def test_window_combined_with_time_range():
    # monthly 命中当天但不在时间段内 → 不可下载
    win = {"mode": "monthly", "start": "00:00", "end": "08:00", "month_days": [1]}
    assert _window(win, datetime(2026, 11, 1, 3, 0)) is True
    assert _window(win, datetime(2026, 11, 1, 12, 0)) is False


def test_window_fail_open_on_bad_config():
    assert _window({"mode": "daily", "start": "不是时间", "end": "08:00"},
                   datetime(2026, 11, 1, 12, 0)) is True  # 非法配置放行
    assert _window({"mode": "monthly"}, datetime(2026, 11, 1, 12, 0)) is True  # 无 month_days 视为不命中？→ 放行由 mode 分支决定


# ---------- 调度周期配置化 ----------

def test_tick_reads_config_and_falls_back():
    ConfigManager.config_dict["download"] = {"site_scan_interval": 9}
    assert Downloader._tick("site_scan_interval", 5) == 9          # 配置覆盖
    assert Downloader._tick("window_check_interval", 60) == 60     # 键缺失回落默认
    ConfigManager.config_dict["download"]["site_scan_interval"] = 0
    assert Downloader._tick("site_scan_interval", 5) == 1          # 下限保护：最小 1 秒


def test_window_waits_use_configured_tick(db, cache_env, monkeypatch):
    """窗口外等待按配置的检查周期轮询（用小周期缩短验证时间）"""
    import time as _time
    ConfigManager.config_dict["download"] = {
        "do_download": True,
        "window_check_interval": 1,
        "site": {
            "default": {"use_cache": True, "download_path": str(cache_env["final"]),
                        "cache_path": str(cache_env["cache"]), "waiting_play": False,
                        "sleep_second": 0},
            "pixiv": {"do_download": True, "download_thread": 1,
                      "download_interval": 2,
                      "download_window": {"mode": "daily", "start": "03:00", "end": "04:00"}},
        },
    }
    _add(workNumber="W", website="pixiv", state="inQueue")
    d = Downloader()
    pool = ThreadPool(max_workers=1, name="t")
    # 窗口判定已有纯函数测试覆盖（test_daily_window_*），这里钉死为"永远在
    # 窗口外"——否则用真实时间构造窗口，跑到窗口内的时段必然翻车
    monkeypatch.setattr(Downloader, "_in_download_window",
                        classmethod(lambda cls, website, now=None: False))
    try:
        # 窗口外跑 2.5 秒：应出现"等待窗口开启"且作品未被认领
        runner = Thread(target=d._site_loop, args=("pixiv", pool), daemon=True)
        runner.start()
        deadline = _time.time() + 2.5
        saw_wait = False
        while _time.time() < deadline:
            saw_wait = saw_wait or _state("W") == "inQueue"
            _time.sleep(0.2)
        # 线程必须仍存活（防配置缺键导致线程静默死亡、断言碰巧通过）
        assert runner.is_alive(), "站点调度线程意外退出"
        pool.shutdown(wait=True, cancel_futures=True)
        d._stop_event.set()
        assert saw_wait and _state("W") == "inQueue"
    finally:
        d._stop_event.set()


# ---------- ThreadPool 提交失败回滚 ----------

def test_submit_rolls_back_on_executor_failure(monkeypatch):
    """super().submit 抛异常（典型：acquire 阻塞期间发生 shutdown）时，
    已占用的信号量与活跃计数必须回滚，否则 wait_for_completion 会永久等待"""
    from concurrent.futures import ThreadPoolExecutor

    pool = ThreadPool(max_workers=2, name="rollback")

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated shutdown race")

    monkeypatch.setattr(ThreadPoolExecutor, "submit", _boom)
    with pytest.raises(RuntimeError):
        pool.submit(lambda: None)

    stats = pool.get_stats()
    assert stats['active_tasks'] == 0
    assert stats['available_threads'] == 2  # 信号量已归还

    monkeypatch.undo()
    fut = pool.submit(lambda: 42)  # 回滚后池仍可用
    assert fut.result(timeout=5) == 42
    pool.shutdown(wait=True)
    assert pool.get_stats()['active_tasks'] == 0


def test_shutdown_cancel_futures_reclaims_active_count(monkeypatch):
    """被 cancel_futures 取消的排队任务不会执行 wrap_fn，计数须由回调补回收。

    信号量背压下正常提交流程不会产生排队任务，这里放宽信号量人为制造
    "已计数但尚未执行"的排队任务（真实场景来自 shutdown 竞态窗口）。
    """
    from threading import Event, Semaphore

    pool = ThreadPool(max_workers=1, name="cancel")
    monkeypatch.setattr(pool, '_sema', Semaphore(10))
    started, release = Event(), Event()
    try:
        pool.submit(lambda: (started.set(), release.wait(5)))
        pool.submit(lambda: None)  # worker 被占住，此任务已计数但排队未执行
        assert started.wait(5)
        assert pool.get_stats()['active_tasks'] == 2
        release.set()
        pool.shutdown(wait=True, cancel_futures=True)  # 排队任务被取消
        assert pool.get_stats()['active_tasks'] == 0
    finally:
        release.set()
        pool.shutdown(wait=True, cancel_futures=True)
