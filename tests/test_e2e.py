"""端到端功能测试：内嵌虚拟站点 + 真实调度全链路。

与单元测试的区别：这里拉起一个真实的 HTTP 虚拟站点（内嵌 ThreadingHTTPServer），
用真实的 ScriptDispatcher / Downloader / Updater / CookieManager / 数据库会话
跑完整管线，脚本文件经 tmp_path 落盘后由分发器动态加载——与生产部署的加载
路径完全一致。

覆盖断言：
- 更新链路：updater 调度线程把虚拟站点 2 页 × 2 条作品入库（works + upload）；
- 增量语义：位点已同步后再次同步，第一条即命中 upload 关联，0 新增；
- 下载链路：downloader 调度线程把 4 个作品下载为 done，产物内容正确；
- cookie 链路：脚本经 CookieManager 注入登录态，虚拟站点回显验证；
- 请求审计：对虚拟站点的请求数恰好等于需求（不多抓）。
"""

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.config.config import ConfigManager
from src.service.dispatcher import ScriptDispatcher
from src.service.downloader import Downloader
from src.service.updater import Updater
from src.utils.cookie_manager import CookieManager
from src.utils.database import database as db_module
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Base, PublishPos, Upload, Works


# ---------------- 虚拟站点 ----------------

class _FakeSiteHandler(BaseHTTPRequestHandler):
    """虚拟站点路由：
    GET /works/<id>/data          → 下载产物文本，回显收到的 Cookie 头
    GET /author/<uid>/list?page=N → 作品列表（每页 2 条，共 2 页，从新到旧）
    """

    def do_GET(self):
        parsed = urlparse(self.path)
        self.server.hits.append(parsed.path)
        match = re.match(r"^/works/([^/]+)/data$", parsed.path)
        if match:
            work_id = match.group(1)
            body = f"payload-of-{work_id}".encode("utf-8")
            received_cookie = self.headers.get("Cookie") or ""
            self.server.received_cookies.append(received_cookie)
            self._send(200, body, {"X-Received-Cookie": received_cookie})
        elif parsed.path.startswith("/author/") and parsed.path.endswith("/list"):
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            works = [{"workid": f"BV{(page - 1) * 2 + i}",
                      "title": f"video {(page - 1) * 2 + i}", "kind": "normal"}
                     for i in range(2)]
            body = json.dumps({"works": works, "hasMore": page < 2}).encode("utf-8")
            self._send(200, body)
        else:
            self._send(404, b"not found")

    def _send(self, code, body, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静音默认请求日志


class _FakeSite(ThreadingHTTPServer):
    """带请求审计的虚拟站点（随机端口，守护线程运行）"""

    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _FakeSiteHandler)
        self.hits = []
        self.received_cookies = []


@pytest.fixture()
def fake_site():
    """启动虚拟站点守护线程并在测试结束后关闭。"""
    site = _FakeSite()
    thread = threading.Thread(target=site.serve_forever, daemon=True)
    thread.start()
    yield site
    site.shutdown()
    site.server_close()


# ---------------- 站点脚本（与生产单文件部署同构，落盘后由分发器加载） ----------------

UPDATE_SCRIPT = '''
# requirements: requests
"""e2e 虚拟站点更新脚本：按页拉取作者作品流，从新到旧产出。"""
import os
import requests


class E2EUpdateUser:
    website = "e2e"
    cookie_manager = None

    def __init__(self, usr: dict, logging):
        self.author_id = usr.get("authorId")
        self.website = usr.get("website") or self.website
        self.log = logging
        self.page = 1
        self.works = []
        self._has_more = True

    def get_one_page(self):
        resp = requests.get(os.environ["E2E_SITE_URL"] + f"/author/{self.author_id}/list",
                            params={"page": self.page}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self.works = list(data.get("works") or [])
        self._has_more = bool(data.get("hasMore"))

    def __iter__(self):
        self.page = 1
        self.works = []
        self._has_more = True
        return self

    def __next__(self):
        if not self.works:
            if not self._has_more:
                raise StopIteration
            self.get_one_page()
            self.page += 1
        if not self.works:
            raise StopIteration
        return self.works.pop(0)
'''

DOWNLOAD_SCRIPT = '''
# requirements: requests
"""e2e 虚拟站点下载脚本：带登录 cookie 拉取产物写入本任务目录。"""
import os
import requests


class E2EDownloadWork:
    website = "e2e"
    logger = None
    config_manager = None
    cookie_manager = None

    def __init__(self, work_info, download_path, download_info=None):
        self.work_number = work_info.get("workNumber")
        self.website = work_info.get("website") or self.website
        self.download_path = download_path
        self.download_info = download_info or {}

    def download_it(self):
        headers = {}
        cm = self.cookie_manager
        if cm is not None and cm.exists(self.website):
            headers["Cookie"] = cm.get_header(self.website)
        resp = requests.get(os.environ["E2E_SITE_URL"] + f"/works/{self.work_number}/data",
                            headers=headers, timeout=10)
        resp.raise_for_status()
        # 站点下载根下自建作品子目录（新契约：download_path 是 <根>/<website>/）
        work_dir = os.path.join(self.download_path, self.work_number)
        os.makedirs(work_dir, exist_ok=True)
        target = os.path.join(work_dir, f"{self.work_number}.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write(resp.text)
        tools = getattr(self, "tools", None)
        if tools is not None:
            tools.log("info", f"[e2e downloader] {self.work_number} 完成")
        return target
'''


# ---------------- 测试环境 ----------------

@pytest.fixture()
def db(tmp_path):
    """把 DatabaseManager 指到临时库（带生产同款 PRAGMA，容忍多线程并发写）"""
    engine = create_engine(f"sqlite:///{tmp_path / 'e2e.db'}",
                           connect_args={"check_same_thread": False})
    event.listens_for(engine, "connect")(db_module._set_sqlite_pragma)
    Base.metadata.create_all(engine)
    DatabaseManager.engine = engine
    DatabaseManager.SessionLocal = sessionmaker(bind=engine)
    yield engine
    DatabaseManager.engine = None
    DatabaseManager.SessionLocal = None
    engine.dispose()


@pytest.fixture()
def runtime(tmp_path, monkeypatch, fake_site):
    """隔离全局配置、工作目录与站点地址；预存 e2e 登录 cookie；落盘站点脚本"""
    saved = dict(ConfigManager.config_dict)
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    base_url = f"http://127.0.0.1:{fake_site.server_address[1]}"
    monkeypatch.setenv("E2E_SITE_URL", base_url)

    ConfigManager.config_dict.clear()
    ConfigManager.config_dict.update({
        "download": {
            "do_download": True,
            "site_scan_interval": 5, "window_check_interval": 60,
            "site": {
                "default": {"once_download_number": -1, "download_interval": 60,
                            "waiting_play": False, "sleep_second": 0,
                            "use_cache": False, "download_path": str(tmp_path / "dl"),
                            "cache_path": str(tmp_path / "cache")},
                "e2e": {"download_thread": 1},
            },
        },
        "update": {
            "do_update": True,
            "site": {
                "default": {"update_thread": 1, "commit_interval": 0,
                            "update_interval": 60},
                "e2e": {},
            },
        },
        "websites": {"e2e": base_url},
        "system": {"console_log_level": "WARNING", "file_log_level": "WARNING"},
    })
    CookieManager.save("e2e", [{"name": "session", "value": "secret-e2e",
                                "domain": "127.0.0.1", "path": "/"}])

    (tmp_path / "update_e2e.py").write_text(UPDATE_SCRIPT, encoding="utf-8")
    (tmp_path / "download_e2e.py").write_text(DOWNLOAD_SCRIPT, encoding="utf-8")
    yield tmp_path

    ConfigManager.config_dict.clear()
    ConfigManager.config_dict.update(saved)


def _wait_until(predicate, timeout=20, interval=0.2):
    """轮询等待条件成立（默认 20 秒超时），避免硬编码 sleep 造成 flaky"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------------- 端到端用例 ----------------

def test_full_pipeline_update_then_download(fake_site, db, runtime):
    """虚拟站点全链路：updater 入库 → 增量停止 → downloader 下载 → 产物与审计"""
    # 位点入库（与 API/REPL 相同的写路径）
    with DatabaseManager.get_db_session() as session:
        session.add(PublishPos(authorId="alice", website="e2e",
                               addTime="2026-11-08T00:00:00", state="inQueue"))

    # --- 更新链路：真实 updater 调度线程 ---
    updater = Updater()
    updater.dispatcher = ScriptDispatcher(sources=[str(runtime / "update_e2e.py")],
                                          fallback_class_name="NoSuchClass")
    runner = threading.Thread(target=updater._site_runner, args=("e2e",), daemon=True)
    runner.start()

    def update_finished():
        with DatabaseManager.get_db_session() as session:
            uploads = session.query(Upload).filter_by(website="e2e").count()
            works = session.query(Works).filter_by(website="e2e").count()
            return uploads == 4 and works == 4

    assert _wait_until(update_finished), "updater 未在超时内完成位点同步"

    # 增量语义：位点已同步，再次同步应在第一条即命中 upload 关联，0 新增
    # （注意：迭代器会先取第一页再判断，因此虚拟站点会被请求 3 次 /author/）
    processed = updater._update_position(
        {"authorId": "alice", "website": "e2e", "addTime": "2026-11-08T00:00:00"})
    assert processed == 0

    updater._stop_event.set()
    runner.join(timeout=10)
    assert not runner.is_alive()

    # --- 下载链路：真实 downloader 调度线程 ---
    downloader = Downloader()
    downloader.dispatcher = ScriptDispatcher(sources=[str(runtime / "download_e2e.py")],
                                             fallback_class_name="NoSuchClass")
    runner2 = threading.Thread(target=downloader._site_runner, args=("e2e",), daemon=True)
    runner2.start()

    def download_finished():
        with DatabaseManager.get_db_session() as session:
            done = session.query(Works).filter_by(website="e2e", state="done").count()
            return done == 4

    assert _wait_until(download_finished), "downloader 未在超时内完成下载"

    # 产物内容正确（use_cache=False：脚本直写最终目录 dl/e2e/<work>/）
    for i in range(4):
        artifact = runtime / "dl" / "e2e" / f"BV{i}" / f"BV{i}.txt"
        assert artifact.exists(), f"缺少产物 {artifact}"
        assert artifact.read_text(encoding="utf-8") == f"payload-of-BV{i}"

    # cookie 链路：脚本经 CookieManager 注入登录态，虚拟站点收到正确 Cookie 头
    assert fake_site.received_cookies, "虚拟站点未收到任何 Cookie 头"
    assert all("session=secret-e2e" in header for header in fake_site.received_cookies)

    downloader._stop_event.set()
    runner2.join(timeout=10)
    assert not runner2.is_alive()

    # --- 请求审计：请求数恰好等于需求（首次同步 2 页 + 增量检查 1 页，4 个作品） ---
    author_hits = sum(1 for hit in fake_site.hits if hit.startswith("/author/"))
    works_hits = sum(1 for hit in fake_site.hits if hit.startswith("/works/"))
    assert author_hits == 3
    assert works_hits == 4
