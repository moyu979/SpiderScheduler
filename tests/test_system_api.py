import pytest
from flask import Flask

from src.config.config import ConfigManager
from src.server.apis.script_api import ScriptApi
from src.server.apis.config_api import ConfigApi
from src.service.dispatcher import ScriptDispatcher
from src.service.downloader import downloader
from src.service.updater import updater


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
    app = Flask(__name__)
    app.register_blueprint(ScriptApi().blueprint)
    app.register_blueprint(ConfigApi().blueprint)
    return app.test_client()


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
    resp = _upload(client, "download", "def broken(:\n", name="pixiv")
    assert resp.status_code == 400
    assert "语法错误" in resp.get_json()["error"]


def test_upload_saved_but_reload_fails_keeps_old_routes(client, monkeypatch):
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
    resp = _upload(client, "ghost", "x = 1\n", name="a")
    assert resp.status_code == 400

    import io
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "file": (io.BytesIO(b"x = 1\n"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400  # 缺 name

    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "name": "a b", "file": (io.BytesIO(b"x=1\n"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400  # 非法文件名

    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "name": "a", "file": (io.BytesIO(b"\xff\xfe\x00"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "UTF-8" in resp.get_json()["error"]
