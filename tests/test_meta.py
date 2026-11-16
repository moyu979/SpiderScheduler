"""MetaManager 与 meta 文件端点测试：原子存取、白名单校验、通配删除、上传 API。
"""
import io
import os

import pytest
from flask import Flask

from src.config.config import ConfigManager
from src.server.apis.meta_api import MetaApi
from src.utils.meta import MetaFileError, MetaManager


@pytest.fixture(autouse=True)
def meta_env(monkeypatch, tmp_path):
    """base_path 指向临时目录，隔离 meta 文件存储。"""
    monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))
    yield tmp_path


@pytest.fixture()
def client():
    """构建只注册 MetaApi 蓝图的 Flask test_client。"""
    app = Flask(__name__)
    app.register_blueprint(MetaApi().blueprint)
    return app.test_client()


def _meta_dir(tmp_path, website="pixiv"):
    return os.path.join(str(tmp_path), "datas", "meta", website)


# ---------------- MetaManager 基座 ----------------

def test_save_read_exists_roundtrip(meta_env):
    """测试 save_file/read_file/exists/file_path 的路径约定与读写往返。"""
    assert MetaManager.exists("pixiv", "session.json") is False
    assert MetaManager.list_files("pixiv") == []

    MetaManager.save_file("pixiv", "session.json", b"\x00bin-ary")
    assert MetaManager.exists("pixiv", "session.json") is True
    assert MetaManager.read_file("pixiv", "session.json") == b"\x00bin-ary"
    assert MetaManager.file_path("pixiv", "session.json") \
        == os.path.join(_meta_dir(meta_env), "session.json")


def test_save_file_atomic_replacement(meta_env):
    """测试写入不留临时文件（.tmp 原子替换）。"""
    MetaManager.save_file("pixiv", "a.json", b"v1")
    MetaManager.save_file("pixiv", "a.json", b"v2")
    assert MetaManager.read_file("pixiv", "a.json") == b"v2"
    assert os.listdir(_meta_dir(meta_env)) == ["a.json"]


def test_list_files_reports_name_size_mtime(meta_env):
    """测试列表返回 name/size/updateTime 且按文件名排序、忽略子目录。"""
    MetaManager.save_file("pixiv", "b.txt", b"123")
    MetaManager.save_file("pixiv", "a.txt", b"12345")
    os.makedirs(_meta_dir(meta_env, "pixiv") + "/subdir")  # 目录结构扁平约定：目录不列出

    files = MetaManager.list_files("pixiv")
    assert [f["name"] for f in files] == ["a.txt", "b.txt"]
    assert [f["size"] for f in files] == [5, 3]
    assert all(f["updateTime"] for f in files)


def test_name_whitelist_blocks_path_traversal():
    """测试站点名/文件名/删除模式白名单：路径分隔符与 .. 一律拒绝。"""
    for website in ("../evil", "a/b", "", "白", None):
        with pytest.raises(MetaFileError):
            MetaManager.file_path(website, "x.json")
    for filename in ("../x", "a/b.json", ".hidden", "", None):
        with pytest.raises(MetaFileError):
            MetaManager.file_path("pixiv", filename)
    with pytest.raises(MetaFileError):
        MetaManager.delete("pixiv", "../evil*")
    with pytest.raises(MetaFileError):
        MetaManager.delete("pixiv", "a/b*")


def test_delete_pattern_and_missing_dir(meta_env):
    """测试通配删除：只中匹配的文件、目录不存在返回空、重复删除返回空。"""
    MetaManager.save_file("pixiv", "cookie.json", b"{}")
    MetaManager.save_file("pixiv", "cookies.txt", b"# Netscape")
    MetaManager.save_file("pixiv", "session.json", b"keep")

    assert MetaManager.delete("pixiv", "cookie*") == ["cookie.json", "cookies.txt"]
    assert MetaManager.exists("pixiv", "session.json") is True
    assert MetaManager.delete("pixiv", "cookie*") == []

    assert MetaManager.delete("ghost", "*") == []  # 目录不存在：空列表不报错


# ---------------- meta 文件端点 ----------------

def test_api_upload_read_list_delete_roundtrip(client):
    """测试上传（raw body）→ 列表 → 读取 → 通配删除的端点全流程。"""
    resp = client.post("/api/meta/pixiv/file/session.json", data=b"sess-1")
    assert resp.get_json() == {"success": True, "name": "session.json", "size": 6}

    files = client.get("/api/meta/pixiv").get_json()
    assert files["success"] and [f["name"] for f in files["files"]] == ["session.json"]

    assert client.get("/api/meta/pixiv/file/session.json").data == b"sess-1"

    removed = client.delete("/api/meta/pixiv/session*").get_json()
    assert removed == {"success": True, "removed": True, "files": ["session.json"]}
    assert client.get("/api/meta/pixiv/file/session.json").status_code == 404


def test_api_upload_multipart_and_overwrite(client):
    """测试 multipart 上传（前端形态）与同名覆盖。"""
    resp = client.post("/api/meta/pixiv/file/state.json",
                       data={"file": (io.BytesIO(b"v1"), "state.json")})
    assert resp.get_json() == {"success": True, "name": "state.json", "size": 2}
    resp = client.post("/api/meta/pixiv/file/state.json",
                       data={"file": (io.BytesIO(b"v2-longer"), "state.json")})
    assert resp.get_json() == {"success": True, "name": "state.json", "size": 9}
    assert client.get("/api/meta/pixiv/file/state.json").data == b"v2-longer"


def test_api_rejects_invalid_name_and_empty_body(client):
    """测试非法文件名 400、空请求体 400、非法站点名 400。

    含路径分隔符的名字在 werkzeug 路由层就 404（到不了端点）；白名单对
    分隔符/.. 的校验逻辑在 MetaManager 层用例（test_name_whitelist_*）覆盖。
    """
    assert client.post("/api/meta/pixiv/file/.hidden", data=b"x").status_code == 400
    assert client.post("/api/meta/pixiv/file/ok.json", data=b"").status_code == 400
    assert client.get("/api/meta/BAD~NAME").status_code == 400
