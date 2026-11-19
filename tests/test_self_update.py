"""在线自更新服务与端点测试：环境拒绝、并发受理保护、更新/无变化/依赖失败回滚、
热重启收尾与 exec 自替换。

用真实 git + 本地 file:// bare 仓当 origin，全程离线验证 fetch/reset/回滚语义；
热重启只 mock 服务停止与 os.execv（真实调用会替换进程本身）。
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from flask import Flask

from src.service import self_update as su
from src.service.self_update import SelfUpdater
from src.server.apis import selfupdate_api
from src.server.apis.selfupdate_api import SelfUpdateApi

GIT_ENV = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=GIT_ENV)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """本地 origin bare 仓（file:// 走 smart 协议，支持 --depth）+ 工作仓 clone。"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    builder = tmp_path / "builder"
    _git(tmp_path, "clone", f"file://{origin}", str(builder))
    (builder / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (builder / "main.py").write_text("print('a')\n", encoding="utf-8")
    _git(builder, "add", ".")
    _git(builder, "commit", "-m", "a")
    _git(builder, "push", "origin", "main")

    work = tmp_path / "app"
    _git(tmp_path, "clone", f"file://{origin}", str(work))

    monkeypatch.setattr(su, "APP_DIR", work)
    monkeypatch.setattr(su, "REQ_HASH_FILE", work / ".req_hash")
    monkeypatch.setattr(su, "LAST_APPLIED_FILE", work / ".last_update.json")
    return {"work": work, "builder": builder}


def _push(repo, files, msg):
    """从 builder 提交并推送新版本（工作仓保持不动，模拟远端领先）。"""
    b = repo["builder"]
    _git(b, "pull", "origin", "main")
    for name, content in files.items():
        (b / name).write_text(content, encoding="utf-8")
    _git(b, "add", ".")
    _git(b, "commit", "-m", msg)
    _git(b, "push", "origin", "main")


def _head(repo):
    """工作仓当前提交短哈希。"""
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo["work"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _make_updater(**overrides):
    """全新 SelfUpdater（不碰全局单例），supported 可强制覆盖模拟容器环境。"""
    u = SelfUpdater()
    u._state["supported"] = overrides.get("supported", True)
    return u


def _wait(u, timeout=10):
    """轮询直到任务离开 running，返回最终状态快照。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = u.status()
        if st["state"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("更新任务超时未结束")


def _wait_for(pred, timeout=5):
    """轮询等待任意条件成立（用于重启线程的副作用断言）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.05)
    raise AssertionError("等待条件超时")


class _FakeSvc:
    """假服务/连接池：stop 与 dispose 把调用记录进共享列表。"""
    def __init__(self, name, calls=None):
        self.name = name
        self._calls = calls if calls is not None else []

    def stop(self):
        self._calls.append(f"stop:{self.name}")

    def dispose(self):
        self._calls.append(f"dispose:{self.name}")


# ---------- 服务层 ----------

def test_trigger_refused_when_unsupported():
    """非容器环境直接拒绝（保护开发目录不被硬重置）。"""
    u = _make_updater(supported=False)
    r = u.trigger()
    assert r["started"] is False and r["reason_code"] == "unsupported"
    st = u.status()
    assert st["state"] == "idle" and st["supported"] is False


def test_trigger_refused_when_no_git_repo(tmp_path, monkeypatch):
    """supported 但目录不是 git 仓库 → 拒绝并降级标记为不支持。"""
    monkeypatch.setattr(su, "APP_DIR", tmp_path)
    u = _make_updater()
    r = u.trigger()
    assert r["started"] is False and r["reason_code"] == "no_repo"
    assert u.status()["supported"] is False


def test_trigger_rejects_while_running(repo, monkeypatch):
    """更新进行中重复受理被拒；结束后恢复可受理。"""
    u = _make_updater()
    release = threading.Event()

    def slow_run():
        release.wait(timeout=10)
        u._set(state="done", updated=True, new_commit="x", message="ok")

    monkeypatch.setattr(u, "_run", slow_run)
    assert u.trigger()["started"] is True
    r = u.trigger()
    assert r["started"] is False and r["reason_code"] == "running"
    release.set()
    assert _wait(u)["state"] == "done"

    monkeypatch.setattr(u, "_run", lambda: u._set(state="done", updated=False))
    assert u.trigger()["started"] is True
    assert _wait(u)["updated"] is False


def test_update_flow_pulls_new_commit(repo, monkeypatch):
    """远端领先时：fetch+reset 到新提交、requirements 变更触发补装并记哈希。"""
    u = _make_updater()
    pip_calls = []
    monkeypatch.setattr(SelfUpdater, "_pip", lambda self: (pip_calls.append(1) or (True, "")))

    old = _head(repo)
    st0 = u.status()
    assert st0["current_commit"] == old and st0["branch"] == "main"

    _push(repo, {"requirements.txt": "flask\nrequests\n", "main.py": "print('b')\n"}, "b")
    r = u.trigger()
    assert r["started"] is True and r["old_commit"] == old

    st = _wait(u)
    assert st["state"] == "done" and st["updated"] is True
    assert st["new_commit"] == _head(repo) != old
    assert st["deps_installed"] is True and pip_calls == [1]
    assert su.REQ_HASH_FILE.read_text() == u._req_hash()
    assert "重启容器" in st["message"]


def test_update_flow_already_uptodate(repo, monkeypatch):
    """远端无新提交 → updated=False，依赖哈希落盘但不重复提示重启。"""
    u = _make_updater()
    monkeypatch.setattr(SelfUpdater, "_pip", lambda self: (True, ""))
    r = u.trigger()
    assert r["started"] is True
    st = _wait(u)
    assert st["state"] == "done" and st["updated"] is False
    assert st["new_commit"] == r["old_commit"]
    assert "已是最新" in st["message"]


def test_pip_failure_rolls_back(repo, monkeypatch):
    """依赖装不上：回退旧提交、清哈希（下次触发重试），代码保持可用。"""
    u = _make_updater()
    monkeypatch.setattr(SelfUpdater, "_pip", lambda self: (False, "pip boom"))
    _push(repo, {"requirements.txt": "flask\nrequests\n"}, "b")
    old = _head(repo)

    u.trigger()
    st = _wait(u)
    assert st["state"] == "failed" and "回退" in st["message"]
    assert _head(repo) == old and st["new_commit"] == old
    assert not su.REQ_HASH_FILE.exists()


def test_fetch_failure_keeps_code(repo):
    """远端不可达：更新失败但代码保持原样。"""
    u = _make_updater()
    old = _head(repo)
    _git(repo["work"], "remote", "remove", "origin")

    u.trigger()
    st = _wait(u)
    assert st["state"] == "failed" and "fetch" in st["message"].lower()
    assert _head(repo) == old


# ---------- 热重启 ----------

def test_restart_refused_when_unsupported():
    """非容器环境拒绝热重启。"""
    u = _make_updater(supported=False)
    r = u.trigger_restart()
    assert r["started"] is False and r["reason_code"] == "unsupported"


def test_restart_and_pull_mutually_exclusive(repo, monkeypatch):
    """拉取进行中拒绝重启；重启受理后拒绝拉取与重复重启。"""
    u = _make_updater()
    release = threading.Event()

    # 拉取挂起期间：重启被拒
    monkeypatch.setattr(u, "_run", lambda: (release.wait(timeout=10), u._set(state="done")))
    assert u.trigger()["started"] is True
    r = u.trigger_restart()
    assert r["started"] is False and r["reason_code"] == "running"
    release.set()
    _wait(u)

    # 重启收尾挂起期间：拉取与重复重启都被拒
    def slow_restart():
        release.wait(timeout=10)

    monkeypatch.setattr(u, "_restart_run", slow_restart)
    monkeypatch.setattr("src.config.config.ConfigManager.stop_daemon", lambda: None)
    assert u.trigger_restart()["started"] is True
    assert u.trigger_restart()["reason_code"] == "running"
    assert u.trigger()["reason_code"] == "running"
    release.set()


def test_restart_drains_services_and_execs(repo, monkeypatch):
    """热重启：按 SIGINT 同序收尾全部服务 → 写生效标记 → exec 自替换。"""
    u = _make_updater()
    calls = []

    monkeypatch.setattr("src.service.downloader.downloader", _FakeSvc("downloader", calls))
    monkeypatch.setattr("src.service.updater.updater", _FakeSvc("updater", calls))
    monkeypatch.setattr("src.server.rest_api.rest_api", _FakeSvc("rest_api", calls))
    monkeypatch.setattr("src.config.config.ConfigManager.stop_daemon",
                        lambda: calls.append("daemon"))
    monkeypatch.setattr("src.utils.database.database.DatabaseManager.engine",
                        _FakeSvc("db", calls))
    monkeypatch.setattr("os.chdir", lambda p: calls.append("chdir"))
    monkeypatch.setattr("os.execv", lambda exe, argv: calls.append(("exec", exe, tuple(argv))))

    assert u.trigger_restart()["started"] is True
    _wait_for(lambda: calls and calls[-1][0] == "exec")

    assert [c if isinstance(c, str) else "exec" for c in calls] == [
        "stop:downloader", "stop:updater", "stop:rest_api", "daemon", "dispose:db", "chdir", "exec"]
    # exec 参数：同一解释器重启 main.py
    assert calls[-1][1] == sys.executable and calls[-1][2][1] == "main.py"
    # 生效标记落盘，新进程（新 SelfUpdater 实例）能读到
    marker = json.loads(su.LAST_APPLIED_FILE.read_text())
    assert marker["commit"] == _head(repo)
    assert SelfUpdater().status()["last_applied"]["commit"] == _head(repo)
    assert u.status()["state"] == "restarting"


def test_last_applied_marker_roundtrip(repo):
    """生效标记持久化后可被新实例读取；坏文件安全降级为 None。"""
    su.LAST_APPLIED_FILE.write_text(json.dumps({"commit": "abc1234", "restarted_at": "t"}))
    assert _make_updater().status()["last_applied"]["commit"] == "abc1234"

    su.LAST_APPLIED_FILE.write_text("not-json")
    assert _make_updater().status()["last_applied"] is None


# ---------- API 层 ----------

@pytest.fixture()
def client():
    """只挂在线自更新蓝图的 Flask test_client。"""
    app = Flask(__name__)
    app.register_blueprint(SelfUpdateApi().blueprint)
    return app.test_client()


def test_api_run_unsupported(client, monkeypatch):
    """不支持环境的 /run 返回 400 与原因码。"""
    monkeypatch.setattr(selfupdate_api, "self_updater", _make_updater(supported=False))
    resp = client.post("/api/system/selfupdate/run")
    assert resp.status_code == 400
    assert resp.get_json()["reason_code"] == "unsupported"

    resp = client.post("/api/system/selfupdate/restart")
    assert resp.status_code == 400
    assert resp.get_json()["reason_code"] == "unsupported"


def test_api_run_and_status(client, repo, monkeypatch):
    """受理 → 进行中重复触发 409 → 轮询 status 到 done。"""
    u = _make_updater()
    monkeypatch.setattr(selfupdate_api, "self_updater", u)
    monkeypatch.setattr(SelfUpdater, "_pip", lambda self: (True, ""))

    data = client.get("/api/system/selfupdate/status").get_json()
    assert data["success"] is True and data["status"]["supported"] is True

    _push(repo, {"main.py": "print('c')\n"}, "c")
    release = threading.Event()

    def slow_run():
        release.wait(timeout=10)
        u._set(state="done", updated=True, new_commit=_head(repo), message="ok")

    monkeypatch.setattr(u, "_run", slow_run)
    resp = client.post("/api/system/selfupdate/run")
    assert resp.status_code == 200 and resp.get_json()["started"] is True

    resp2 = client.post("/api/system/selfupdate/run")
    assert resp2.status_code == 409 and resp2.get_json()["reason_code"] == "running"

    release.set()
    deadline = time.time() + 5
    st = {}
    while time.time() < deadline:
        st = client.get("/api/system/selfupdate/status").get_json()["status"]
        if st["state"] != "running":
            break
        time.sleep(0.05)
    assert st["state"] == "done" and st["updated"] is True


def test_api_restart_flow(client, repo, monkeypatch):
    """重启受理 → 进行中重复触发 409 → 状态含 last_applied 字段。"""
    u = _make_updater()
    monkeypatch.setattr(selfupdate_api, "self_updater", u)

    st = client.get("/api/system/selfupdate/status").get_json()["status"]
    assert st["last_applied"] is None

    release = threading.Event()

    def slow_restart():
        release.wait(timeout=10)

    monkeypatch.setattr(u, "_restart_run", slow_restart)
    resp = client.post("/api/system/selfupdate/restart")
    assert resp.status_code == 200 and resp.get_json()["started"] is True

    resp2 = client.post("/api/system/selfupdate/restart")
    assert resp2.status_code == 409 and resp2.get_json()["reason_code"] == "running"
    release.set()
