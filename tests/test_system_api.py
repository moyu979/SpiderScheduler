"""系统管理 API 测试：配置段读写、脚本上传/冲突检测/删除。
"""
import pytest
from flask import Flask

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.config import ConfigManager
from src.server.apis.script_api import ScriptApi
from src.server.apis.config_api import ConfigApi
from src.server.apis.website_api import WebsitesApi
from src.server.apis.update_api import UpdateApi
from src.service.dispatcher import ScriptDispatcher
from src.service.downloader import downloader
from src.service.updater import updater
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Base, Works


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, tmp_path):
    """base_path 指向临时目录（供配置写盘），隔离单例上的分发器"""
    confs = tmp_path / "confs"
    confs.mkdir()
    (confs / "demo.yaml").write_text("k: v1\n", encoding="utf-8")
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    ConfigManager.load_all_configs()

    saved = (updater.dispatcher, downloader.dispatcher)
    yield
    updater.dispatcher, downloader.dispatcher = saved


@pytest.fixture()
def client():
    """注册系统管理四个蓝图的 Flask test_client。"""
    app = Flask(__name__)
    app.register_blueprint(ScriptApi().blueprint)
    app.register_blueprint(ConfigApi().blueprint)
    app.register_blueprint(WebsitesApi().blueprint)
    app.register_blueprint(UpdateApi().blueprint)
    return app.test_client()


@pytest.fixture()
def db(tmp_path):
    """把 DatabaseManager 指到临时库（占用统计要用）"""
    engine = create_engine(f"sqlite:///{tmp_path / 'web.db'}")
    Base.metadata.create_all(engine)
    DatabaseManager.engine = engine
    DatabaseManager.SessionLocal = sessionmaker(bind=engine)
    yield engine
    DatabaseManager.engine = None
    DatabaseManager.SessionLocal = None
    engine.dispose()


def _install_dispatcher(monkeypatch, tmp_path, target, name):
    import pathlib
    script = pathlib.Path(tmp_path) / f"script_{name}.py"
    script.write_text(f'''
class {name.capitalize()}Work:
    website = "{name}"
''', encoding="utf-8")
    d = ScriptDispatcher(lambda: [str(script)], fallback_class_name="Fallback")
    monkeypatch.setattr(target, "dispatcher", d)
    return d


def test_scripts_info(client, monkeypatch, tmp_path):
    """测试脚本路由信息端点：未初始化与已初始化（含兜底判定）。"""
    # 未初始化时
    updater.dispatcher = None
    data = client.get("/api/system/scripts").get_json()
    assert data["routes"]["update"] == {"initialized": False}

    _install_dispatcher(monkeypatch, tmp_path, updater, "update")
    _install_dispatcher(monkeypatch, tmp_path, downloader, "download")
    data = client.get("/api/system/scripts").get_json()
    assert data["routes"]["update"]["websites"] == {"update": "UpdateWork"}
    # 有 website 声明时不存在兜底
    assert data["routes"]["download"]["fallback"] is None


def test_scripts_reload(client, monkeypatch, tmp_path):
    """测试重载端点成功，以及写坏脚本时返回 400 且旧路由保留。"""
    d = _install_dispatcher(monkeypatch, tmp_path, downloader, "download")
    resp = client.post("/api/system/scripts/reload")
    assert resp.status_code == 200
    assert resp.get_json()["routes"]["download"]["websites"] == {"download": "DownloadWork"}

    # 脚本写坏 → 重载返回 400，旧路由保留
    d.sources = lambda: ["/nonexistent/ghost.py"]
    resp = client.post("/api/system/scripts/reload")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "download" in body["error"]
    assert body["routes"]["download"]["websites"] == {"download": "DownloadWork"}


def test_config_list_and_raw_roundtrip(client):
    """测试配置段列表、raw 读写回环与写盘验证。"""
    sections = client.get("/api/system/config").get_json()["sections"]
    assert "demo" in sections

    raw = client.get("/api/system/config/demo/raw").get_json()
    assert "k: v1" in raw["content"]

    resp = client.put("/api/system/config/demo/raw",
                      json={"content": "k: v2\nnew_key:\n  - a\n  - b\n"})
    assert resp.status_code == 200
    assert ConfigManager.get("demo", "k") == "v2"
    assert ConfigManager.get("demo", "new_key") == ["a", "b"]

    # 写盘验证
    import pathlib
    confs = pathlib.Path(ConfigManager.base_path) / "confs"
    assert "k: v2" in (confs / "demo.yaml").read_text(encoding="utf-8")


def test_config_raw_rejects_bad_input(client):
    """测试 raw 写入对坏 YAML/非映射根/未知段/缺 content 的拒绝分支。"""
    resp = client.put("/api/system/config/demo/raw", json={"content": "k: [unclosed\n"})
    assert resp.status_code == 400
    assert "YAML" in resp.get_json()["error"]

    resp = client.put("/api/system/config/demo/raw", json={"content": "- 1\n- 2\n"})
    assert resp.status_code == 400

    resp = client.put("/api/system/config/ghost/raw", json={"content": "k: 1\n"})
    assert resp.status_code == 404

    resp = client.put("/api/system/config/demo/raw", json={})
    assert resp.status_code == 400


def test_config_reload_endpoint(client, monkeypatch, tmp_path):
    """测试 reload 端点从磁盘重读配置。"""
    confs = tmp_path / "confs"
    (confs / "demo.yaml").write_text("k: from-file\n", encoding="utf-8")
    resp = client.post("/api/system/config/reload")
    assert resp.status_code == 200
    assert ConfigManager.get("demo", "k") == "from-file"


# ---------- 脚本文件管理与多文件上传 ----------

def _upload(client, kind, content, name, force=False):
    import io
    data = {"kind": kind, "name": name, "file": (io.BytesIO(content.encode()), f"{name}.py")}
    if force:
        data["force"] = "true"
    return client.post("/api/system/scripts/upload",
                       data=data, content_type="multipart/form-data")


def test_script_files_listing(client):
    """测试脚本文件列表：传统单文件与目录式脚本的区分。"""
    files = client.get("/api/system/scripts/download/files").get_json()["files"]
    # env_setup 的 tmp 工作目录没有脚本，但 init_files 没跑；来源列表为空
    assert files == []

    import pathlib
    scripts = pathlib.Path(ConfigManager.base_path) / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "download_a_work.py").write_text("class DownloadWork:\n    pass\n", encoding="utf-8")
    ddir = scripts / "download"
    ddir.mkdir()
    (ddir / "pixiv.py").write_text('class DownloadWork:\n    website = "pixiv"\n', encoding="utf-8")

    files = client.get("/api/system/scripts/download/files").get_json()["files"]
    assert [f["name"] for f in files] == ["download_a_work.py", "pixiv"]
    assert files[0]["legacy"] is True and files[0]["websites"] == []
    assert files[1]["websites"] == ["pixiv"]


def test_script_source_by_name(client):
    """测试按名取脚本源码，及缺名/不存在/未知 kind 分支。"""
    import pathlib
    scripts = pathlib.Path(ConfigManager.base_path) / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "download_a_work.py").write_text("class DownloadWork:\n    pass\n", encoding="utf-8")

    data = client.get("/api/system/scripts/download/source?name=download_a_work").get_json()
    assert data["name"] == "download_a_work" and "DownloadWork" in data["content"]

    assert client.get("/api/system/scripts/download/source").status_code == 400
    assert client.get("/api/system/scripts/download/source?name=nope").status_code == 404
    assert client.get("/api/system/scripts/ghost/source?name=a").status_code == 400


def test_upload_saves_to_named_file_and_reloads(client, monkeypatch):
    """测试上传落盘为命名文件后自动重载，路由立即生效。"""
    import pathlib
    sdir = pathlib.Path(ConfigManager.base_path) / "scripts" / "update"
    sdir.mkdir(parents=True, exist_ok=True)
    legacy = sdir / "update_a_user.py"
    legacy.write_text("class UpdateUser:\n    pass\n", encoding="utf-8")
    d = ScriptDispatcher(lambda: sorted(str(p) for p in sdir.glob("*.py")),
                         fallback_class_name="UpdateUser")
    monkeypatch.setattr(updater, "dispatcher", d)

    content = 'class UpdateUser:\n    website = "danbooru"\n'
    resp = _upload(client, "update", content, name="danbooru")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["saved_path"].endswith(str(pathlib.Path("scripts") / "update" / "danbooru.py"))
    assert body["reload"]["ok"] is True
    assert body["reload"]["snapshot"]["websites"] == {"danbooru": "UpdateUser"}

    # 已落盘且重新扫描后路由生效（无需手动重载）
    assert (sdir / "danbooru.py").read_text(encoding="utf-8") == content
    assert d.get("danbooru").__name__ == "UpdateUser"
    # 来源 callable 在重扫时重新求值 → 新文件与 legacy 文件都被扫描
    by_file = {pathlib.Path(p).name: w for p, w in d.sites_by_file().items()}
    assert by_file == {"update_a_user.py": [], "danbooru.py": ["danbooru"]}


def test_upload_file_conflict_then_force(client, monkeypatch):
    """测试同名文件冲突返回 409，force 确认后覆盖成功。"""
    import pathlib
    ddir = pathlib.Path(ConfigManager.base_path) / "scripts" / "download"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "pixiv.py").write_text('class DownloadWork:\n    website = "pixiv"\n', encoding="utf-8")
    d = ScriptDispatcher(lambda: [str(ddir / "pixiv.py")], fallback_class_name="DownloadWork")
    monkeypatch.setattr(downloader, "dispatcher", d)

    # 同名文件 → 409 fileExists；用户确认覆盖（force）→ 成功
    resp = _upload(client, "download", 'class DownloadWork:\n    website = "pixiv"\n', name="pixiv")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["conflict"]["fileExists"] is True and body["conflict"]["websites"] == []

    resp = _upload(client, "download", 'class DownloadWork:\n    website = "pixiv"\n', name="pixiv", force=True)
    assert resp.status_code == 200
    assert resp.get_json()["reload"]["ok"] is True


def test_upload_website_conflict_then_force(client, monkeypatch):
    """测试 website 被其他文件占用返回 409，force 后新文件接管路由。"""
    import pathlib
    ddir = pathlib.Path(ConfigManager.base_path) / "scripts" / "download"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "pixiv.py").write_text('class DownloadWork:\n    website = "pixiv"\n', encoding="utf-8")
    d = ScriptDispatcher(lambda: sorted(str(p) for p in ddir.glob("*.py")),
                         fallback_class_name="DownloadWork")
    monkeypatch.setattr(downloader, "dispatcher", d)

    # 新文件名，但声明了已被其他文件占用的 website → 409 websites
    resp = _upload(client, "download", 'class DownloadWork:\n    website = ["pixiv", "gelbooru"]\n', name="other")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["conflict"]["fileExists"] is False
    assert body["conflict"]["websites"] == ["pixiv"]

    # force 覆盖后 pixiv 路由被新文件接管
    resp = _upload(client, "download", 'class DownloadWork:\n    website = ["pixiv", "gelbooru"]\n', name="other", force=True)
    assert resp.status_code == 200
    assert resp.get_json()["reload"]["snapshot"]["websites"] == {"gelbooru": "DownloadWork", "pixiv": "DownloadWork"}


def test_upload_syntax_error_rejected(client):
    """测试语法错误的脚本被拒绝上传。"""
    resp = _upload(client, "download", "def broken(:\n", name="pixiv")
    assert resp.status_code == 400
    assert "语法错误" in resp.get_json()["error"]


def test_upload_saved_but_reload_fails_keeps_old_routes(client, monkeypatch):
    """测试保存成功但重扫失败时返回 ok=false 且旧路由生效。"""
    import pathlib
    legacy = pathlib.Path(ConfigManager.base_path) / "scripts" / "download_a_work.py"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("class DownloadWork:\n    pass\n", encoding="utf-8")
    d = ScriptDispatcher(lambda: [str(legacy)], fallback_class_name="DownloadWork")
    monkeypatch.setattr(downloader, "dispatcher", d)

    # 覆盖传统单文件为"既无 website 也无兜底类"的内容 → 保存成功、重扫失败、旧路由生效
    resp = _upload(client, "download", "X = 1\n", name="download_a_work", force=True)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["reload"]["ok"] is False
    assert body["reload"]["snapshot"] == {"websites": {}, "fallback": "DownloadWork"}
    assert d.get("pixiv").__name__ == "DownloadWork"


def test_delete_script_rescans(client, monkeypatch):
    """测试删除脚本后重扫生效，及重复删除 404 与非法名 400 分支。"""
    import pathlib
    ddir = pathlib.Path(ConfigManager.base_path) / "scripts" / "download"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "pixiv.py").write_text('class DownloadWork:\n    website = "pixiv"\n', encoding="utf-8")
    d = ScriptDispatcher(lambda: [str(ddir / "pixiv.py")], fallback_class_name="DownloadWork")
    monkeypatch.setattr(downloader, "dispatcher", d)

    resp = client.delete("/api/system/scripts/download/pixiv")
    assert resp.status_code == 200
    assert resp.get_json()["removed"] == "pixiv"
    assert not (ddir / "pixiv.py").exists()

    assert client.delete("/api/system/scripts/download/pixiv").status_code == 404
    assert client.delete("/api/system/scripts/download/BAD~NAME").status_code == 400


def test_upload_rejects_bad_input(client):
    """测试上传非法 kind/文件名/非 UTF-8 编码被拒，name 留空可从文件名派生。"""
    resp = _upload(client, "ghost", "x = 1\n", name="a")
    assert resp.status_code == 400

    import io
    # name 留空 → 从上传文件名派生（新语义：合法文件名即可上传）
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "file": (io.BytesIO(b"x = 1\n"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["saved_path"].endswith("scripts/download/s.py")

    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "name": "a b", "file": (io.BytesIO(b"x=1\n"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400  # 非法文件名

    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "name": "a", "file": (io.BytesIO(b"\xff\xfe\x00"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "UTF-8" in resp.get_json()["error"]


# ---------- 站点入口管理（websites.yaml 线上配置） ----------

def _seed_sites(**sites):
    ConfigManager.config_dict["websites"] = dict(sites)


def test_websites_list_and_usage(client, db, monkeypatch, tmp_path):
    """测试站点列表与占用统计（DB 作品占用 + 显式脚本路由）。"""
    _seed_sites(pixiv="https://www.pixiv.net", ghost="https://ghost.example.com")
    _install_dispatcher(monkeypatch, tmp_path, downloader, "ghost")
    with DatabaseManager.get_db_session() as session:
        session.add(Works(workNumber="W1", website="pixiv", state="inQueue"))

    data = client.get("/api/system/websites").get_json()
    assert data["success"] and data["sites"]["pixiv"] == "https://www.pixiv.net"
    # 占用统计：DB 占用 + 显式脚本路由（兜底不计）
    assert data["usage"]["pixiv"]["works"] == 1
    assert data["usage"]["ghost"]["routes"] == ["download"]


def test_website_put_creates_and_updates(client):
    """测试站点入口新增与更新（同一入口为修改）并落盘。"""
    _seed_sites()
    # 新增
    resp = client.put("/api/system/websites/bilibili",
                      json={"url": "https://www.bilibili.com"})
    body = resp.get_json()
    assert resp.status_code == 200 and body["created"] is True
    assert ConfigManager.config_dict["websites"]["bilibili"] == "https://www.bilibili.com"
    # 落盘校验（_save_config 保持既有格式：无预置文件时写 json，有模板时写回 yaml）
    import pathlib
    confs = pathlib.Path(ConfigManager.base_path) / "confs"
    saved = confs / "websites.yaml"
    if not saved.exists():
        saved = confs / "websites.json"
    assert "bilibili" in saved.read_text(encoding="utf-8")
    # 更新（同一入口是修改而非新增）
    resp = client.put("/api/system/websites/bilibili",
                      json={"url": "https://m.bilibili.com"})
    assert resp.get_json()["created"] is False
    assert ConfigManager.config_dict["websites"]["bilibili"] == "https://m.bilibili.com"


def test_website_put_validates_name_and_url(client):
    """测试非法站点名与 URL 被校验拒绝，且不写入配置。"""
    _seed_sites()
    # 空名与含斜杠名无法经路由到达（Werkzeug 不匹配空段/编码斜杠），
    # 其余非法名经 percent-encoding 到达，由 API 校验拒绝
    for name in ("bad name", "站点", "a.b"):
        from urllib.parse import quote
        resp = client.put(f"/api/system/websites/{quote(name, safe='')}", json={"url": "https://x.com"})
        assert resp.status_code == 400, name
    resp = client.put("/api/system/websites/ok", json={"url": "ftp://x.com"})
    assert resp.status_code == 400
    resp = client.put("/api/system/websites/ok", json={"url": ""})
    assert resp.status_code == 400
    # 非法输入不得写入
    assert ConfigManager.config_dict["websites"] == {}


def test_website_delete_with_usage_guard(client, db, monkeypatch, tmp_path):
    """测试删除被作品引用的站点返回 409 占用明细，force 后才可删。"""
    _seed_sites(pixiv="https://www.pixiv.net")
    with DatabaseManager.get_db_session() as session:
        session.add(Works(workNumber="W1", website="pixiv", state="inQueue"))

    # 被作品引用 → 409 + 占用明细
    resp = client.delete("/api/system/websites/pixiv")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["usage"]["works"] == 1
    assert ConfigManager.config_dict["websites"]["pixiv"]  # 未被删除

    # force=true → 删除成功
    resp = client.delete("/api/system/websites/pixiv?force=true")
    assert resp.status_code == 200
    assert "pixiv" not in ConfigManager.config_dict["websites"]


def test_website_delete_unused_and_missing(client, db):
    """测试未引用站点直接删除，不存在站点返回 404。"""
    _seed_sites(empty="https://empty.example.com")
    # 未被引用 → 直接删除
    resp = client.delete("/api/system/websites/empty")
    assert resp.status_code == 200
    # 不存在的站点 → 404
    resp = client.delete("/api/system/websites/ghost")
    assert resp.status_code == 404


# ---------- 上传保存名派生 ----------

def test_upload_derives_name_from_filename(client, monkeypatch):
    """name 留空时从上传文件名派生保存名（空格折叠为下划线，去 .py）"""
    import io
    import pathlib
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "update",
                             "file": (io.BytesIO(b'class X:\n    website = "d"\n'),
                                      "my script.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["saved_path"].endswith("scripts/update/my_script.py")
    assert pathlib.Path(body["saved_path"]).exists()


def test_upload_undeliverable_filename_requires_manual_name(client):
    """上传文件名含非 ASCII 且未指定 name → 400 并给出手动指定指引"""
    import io
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "update",
                             "file": (io.BytesIO(b'class X:\n    pass\n'), "我的脚本.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "手动指定保存名" in resp.get_json()["error"]


def test_upload_explicit_name_overrides_filename(client):
    """显式 name 优先于上传文件名派生"""
    import io
    import pathlib
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "update", "name": "explicit",
                             "file": (io.BytesIO(b'class X:\n    website = "e"\n'),
                                      "whatever name.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["saved_path"].endswith("scripts/update/explicit.py")


# ---------- 立即更新 API ----------

def test_update_now_api(client, db, monkeypatch, tmp_path):
    """测试立即更新端点：404 分支、受理、状态轮询到 done 与数据落库。"""
    import io
    import pathlib
    import time

    from src.utils.database.models import PublishPos

    with DatabaseManager.get_db_session() as session:
        session.add(PublishPos(authorId="a", website="pixiv", state="inQueue"))

    script = tmp_path / "api_now_updater.py"
    script.write_text('''
class ApiNowUpdater:
    website = "pixiv"
    cookie_manager = None

    def __init__(self, usr, logging):
        self.website = usr.get("website")
        self.author_id = usr.get("authorId")

    def __iter__(self):
        return iter([{"workid": "APINOW1", "title": "t", "kind": "normal",
                      "upTime": "", "state": None, "downloadPriority": 0}])
''', encoding='utf-8')
    d = ScriptDispatcher(lambda: [str(script)], fallback_class_name="Fallback")
    monkeypatch.setattr(updater, "dispatcher", d)

    # 不存在的位点 → 404
    resp = client.post("/api/update/update_now", json={"authorId": "ghost", "website": "pixiv"})
    assert resp.status_code == 404

    # 受理 → 轮询状态端点直到 done
    resp = client.post("/api/update/update_now", json={"authorId": "a", "website": "pixiv"})
    assert resp.status_code == 200 and resp.get_json()["started"] is True

    deadline = time.time() + 5
    statuses = {}
    while time.time() < deadline:
        statuses = client.get("/api/update/update_now/status").get_json()["statuses"]
        st = statuses.get("pixiv|a")
        if st and st["state"] != "running":
            break
        time.sleep(0.05)
    assert statuses["pixiv|a"]["state"] == "done" and statuses["pixiv|a"]["added"] == 1

    with DatabaseManager.get_db_session() as session:
        assert session.get(Works, ("APINOW1", "pixiv")) is not None
