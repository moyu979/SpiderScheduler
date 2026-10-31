import pytest
from flask import Flask

from src.config.config import ConfigManager
from src.server.apis.system_api import SystemApi
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
    app.register_blueprint(SystemApi().blueprint)
    return app.test_client()


def _install_dispatcher(monkeypatch, tmp_path, target, name):
    script = tmp_path / f"script_{name}.py"
    script.write_text(f'''
class {name.capitalize()}Work:
    website = "{name}"
''', encoding="utf-8")
    d = ScriptDispatcher(str(script), fallback_class_name="Fallback")
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
    d.script_path = "/nonexistent/ghost.py"
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


# ---------- 脚本上传 ----------

def _upload(client, kind, content, filename="script.py"):
    import io
    return client.post("/api/system/scripts/upload",
                       data={"kind": kind, "file": (io.BytesIO(content.encode()), filename)},
                       content_type="multipart/form-data")


def test_script_source_404_then_content(client, monkeypatch, tmp_path):
    monkeypatch.setattr("src.server.apis.system_api.download_script_path",
                        lambda: str(tmp_path / "scripts" / "download_a_work.py"))
    assert client.get("/api/system/scripts/download/source").status_code == 404

    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "download_a_work.py").write_text("class DownloadWork:\n    pass\n", encoding="utf-8")
    data = client.get("/api/system/scripts/download/source").get_json()
    assert data["filename"] == "download_a_work.py"
    assert "DownloadWork" in data["content"]

    assert client.get("/api/system/scripts/ghost/source").status_code == 400


def test_upload_saves_and_reloads(client, monkeypatch, tmp_path):
    script_path = tmp_path / "scripts" / "update_a_user.py"
    (tmp_path / "scripts").mkdir()
    script_path.write_text("class UpdateUser:\n    pass\n", encoding="utf-8")
    d = ScriptDispatcher(str(script_path), fallback_class_name="UpdateUser")
    monkeypatch.setattr(updater, "dispatcher", d)

    content = '''
class UpdateUser:
    website = "danbooru"
'''
    resp = _upload(client, "update", content)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["saved_path"].endswith("update_a_user.py")
    assert body["reload"]["ok"] is True
    assert body["reload"]["snapshot"]["websites"] == {"danbooru": "UpdateUser"}

    # 已落盘且路由已切换（无需再手动重载）
    assert script_path.read_text(encoding="utf-8") == content
    assert d.get("danbooru").__name__ == "UpdateUser"


def test_upload_syntax_error_rejected(client, monkeypatch, tmp_path):
    script_path = tmp_path / "scripts" / "download_a_work.py"
    (tmp_path / "scripts").mkdir()
    script_path.write_text("class DownloadWork:\n    pass\n", encoding="utf-8")
    d = ScriptDispatcher(str(script_path), fallback_class_name="DownloadWork")
    monkeypatch.setattr(downloader, "dispatcher", d)

    resp = _upload(client, "download", "def broken(:\n")
    assert resp.status_code == 400
    assert "语法错误" in resp.get_json()["error"]
    # 原文件未被覆盖
    assert "class DownloadWork" in script_path.read_text(encoding="utf-8")


def test_upload_saved_but_reload_fails_keeps_old_routes(client, monkeypatch, tmp_path):
    script_path = tmp_path / "scripts" / "download_a_work.py"
    (tmp_path / "scripts").mkdir()
    script_path.write_text("class DownloadWork:\n    pass\n", encoding="utf-8")
    d = ScriptDispatcher(str(script_path), fallback_class_name="DownloadWork")
    monkeypatch.setattr(downloader, "dispatcher", d)

    # 语法合法但缺兜底类 → 保存成功、重载失败、旧路由生效
    resp = _upload(client, "download", "X = 1\n")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["reload"]["ok"] is False
    assert body["reload"]["snapshot"] == {"websites": {}, "fallback": "DownloadWork"}
    assert d.get("pixiv").__name__ == "DownloadWork"


def test_upload_rejects_bad_input(client):
    resp = _upload(client, "ghost", "x = 1\n")
    assert resp.status_code == 400

    import io
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download"}, content_type="multipart/form-data")
    assert resp.status_code == 400

    # 非 UTF-8
    resp = client.post("/api/system/scripts/upload",
                       data={"kind": "download", "file": (io.BytesIO(b"\xff\xfe\x00"), "s.py")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "UTF-8" in resp.get_json()["error"]
