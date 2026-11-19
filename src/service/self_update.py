"""在线自更新服务：运行时从 GitHub 拉取最新代码 + 优雅热重启（仅容器部署开放）。

拉取行为与 entrypoint.sh 启动期的 AUTO_UPDATE 完全一致：fetch 远端（GIT_BRANCH，
默认 main）并硬重置——容器里 /app 只由远端代码生成、无本地修改，硬重置即部署
镜像语义；再按 requirements.txt 的 md5 决定是否补装依赖。安全网：

- 仅容器环境开放（/.dockerenv 或 /run/.containerenv）：开发机的仓库带有本地
  提交，硬重置会毁掉未推送的工作，一律拒绝；
- 依赖装不上则回退到更新前的提交并清哈希（下次触发重试），杜绝
  "代码新、依赖旧"的半更新态；
- 任一步失败（断网、GitHub 不可达）代码保持可用状态，不影响服务运行。

热重启（trigger_restart）以 os.execv 自替换进程：优雅收尾在途任务与连接池
后，同一容器/端口载入磁盘上的新代码，等效"docker restart"但无 docker 依赖、
停机窗口最小。收尾顺序与 main.py 的 SIGINT 处理一致；exec 不换 PID，POSIX
文件锁随之保留，故必须先 dispose 数据库连接池释放 sqlite 文件锁。
"""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.utils.logging.logger import SpiderLogger as logger

APP_DIR = Path(__file__).resolve().parents[2]
REQ_HASH_FILE = APP_DIR / ".req_hash"
LAST_APPLIED_FILE = APP_DIR / ".last_update.json"
FETCH_TIMEOUT = 600    # 弱网下拉取最新提交的上限
RESET_TIMEOUT = 60
PIP_TIMEOUT = 1800     # requirements 变更时补装依赖的上限


def _in_container() -> bool:
    """容器环境探测：Docker（/.dockerenv）或 Podman（/run/.containerenv）。"""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _read_last_applied():
    """读取上次热重启生效的落盘标记（.last_update.json），无则返回 None。"""
    try:
        return json.loads(LAST_APPLIED_FILE.read_text())
    except (OSError, ValueError):
        return None


class SelfUpdater:
    """在线自更新：trigger() 受理后由后台线程执行，status() 供前端轮询。

    Attributes:
        state: 状态快照（state=idle/running/done/failed，及分支、前后提交、
            上次结果等字段）。
    """

    def __init__(self):
        """初始化状态快照并探测运行环境。"""
        self._lock = threading.Lock()
        self._state = {
            "state": "idle",
            "supported": _in_container(),
            "branch": os.environ.get("GIT_BRANCH") or "main",
            "old_commit": None,
            "new_commit": None,
            "updated": None,
            "deps_installed": False,
            "started_at": None,
            "finished_at": None,
            "message": "",
        }
        self._last_applied = _read_last_applied()

    def status(self):
        """返回状态快照；非运行中附带当前提交号（git 不可用时为 None）。"""
        with self._lock:
            snap = dict(self._state)
        if snap["state"] != "running" and snap["supported"]:
            snap["current_commit"] = self._git(["rev-parse", "--short", "HEAD"])[1] or None
        snap["last_applied"] = self._last_applied
        return snap

    def trigger_restart(self):
        """受理一次优雅热重启（后台收尾在途任务后 exec 自替换，立即返回）。

        Returns:
            dict：started=True 表示已受理；否则 started=False 并附 reason
            与 reason_code（unsupported=环境不支持，running=拉取/重启进行中）。
        """
        with self._lock:
            if not self._state["supported"]:
                return {"started": False, "reason": "当前非容器部署，热重启不可用",
                        "reason_code": "unsupported"}
            if self._state["state"] in ("running", "restarting"):
                return {"started": False, "reason": "已有更新或重启在进行中", "reason_code": "running"}

        self._set(state="restarting", message="正在收尾在途任务…", finished_at=None)
        logger.info("热重启已受理（优雅收尾后以磁盘当前代码重启）")
        threading.Thread(target=self._restart_run, name="SelfRestart", daemon=True).start()
        return {"started": True}

    def trigger(self):
        """受理一次在线更新（后台线程执行，立即返回）。

        Returns:
            dict：started=True 表示已受理；否则 started=False 并附 reason
            与 reason_code（unsupported=环境不支持，running=已有更新进行中，
            no_repo=代码目录不是 git 仓库）。
        """
        with self._lock:
            if not self._state["supported"]:
                return {"started": False, "reason": "当前非容器部署，在线更新不可用（避免硬重置破坏开发目录）",
                        "reason_code": "unsupported"}
            if self._state["state"] in ("running", "restarting"):
                return {"started": False, "reason": "已有更新或重启在进行中", "reason_code": "running"}

        ok, _, _ = self._git(["rev-parse", "--is-inside-work-tree"])
        if not ok:
            self._set(supported=False)
            return {"started": False, "reason": "代码目录不是 git 仓库，无法在线更新", "reason_code": "no_repo"}

        old = self._git(["rev-parse", "HEAD"])[1]
        old = (old or "")[:7] or "unknown"
        self._set(state="running", message="", started_at=_now(), old_commit=old,
                  new_commit=None, updated=None, deps_installed=False, finished_at=None)
        logger.info(f"在线更新已受理（分支 {self._state['branch']}，当前 {old}）")
        threading.Thread(target=self._run, name="SelfUpdate", daemon=True).start()
        return {"started": True, "old_commit": old}

    # ---------- 内部实现 ----------

    def _set(self, **fields):
        """带锁更新状态快照（worker 线程与 API 线程共用）。"""
        with self._lock:
            self._state.update(fields)

    def _git(self, args, timeout=RESET_TIMEOUT):
        """执行 git 命令，返回 (是否成功, stdout 去空白, stderr 去空白)。"""
        try:
            p = subprocess.run(["git", *args], cwd=APP_DIR, capture_output=True,
                               text=True, timeout=timeout)
            return p.returncode == 0, (p.stdout or "").strip(), (p.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, "", str(e)

    def _pip(self):
        """补装依赖（requirements.txt 变更时调用），返回 (是否成功, stderr)。"""
        try:
            p = subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir",
                                "-r", "requirements.txt"],
                               cwd=APP_DIR, capture_output=True, text=True, timeout=PIP_TIMEOUT)
            return p.returncode == 0, (p.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)

    @staticmethod
    def _req_hash():
        """requirements.txt 的 md5（与 entrypoint 的 md5sum 口径一致）。"""
        return hashlib.md5((APP_DIR / "requirements.txt").read_bytes()).hexdigest()

    @staticmethod
    def _stored_hash():
        """上一次装依赖时的 requirements 哈希（.req_hash），从未记录过返回 None。"""
        try:
            return REQ_HASH_FILE.read_text().strip()
        except OSError:
            return None

    def _run(self):
        """执行拉取：fetch → 硬重置 → 按需补装依赖；依赖失败回滚旧提交。"""
        old = self._state["old_commit"]
        branch = self._state["branch"]
        try:
            ok, _, err = self._git(["fetch", "--depth", "1", "origin", branch], FETCH_TIMEOUT)
            if not ok:
                raise RuntimeError(f"git fetch 失败（远端 {branch} 不可达）：{err or '未知错误'}")

            ok, _, err = self._git(["reset", "--hard", "FETCH_HEAD"])
            if not ok:
                raise RuntimeError(f"git reset 失败（代码未变动）：{err or '未知错误'}")

            new = self._git(["rev-parse", "--short", "HEAD"])[1] or "unknown"
            updated = new != old
            deps_installed = False

            hash_now = self._req_hash()
            if hash_now != self._stored_hash():
                ok, err = self._pip()
                if not ok:
                    # 回滚到更新前提交并清哈希，下次触发重试
                    self._git(["reset", "--hard", old])
                    try:
                        REQ_HASH_FILE.unlink()
                    except OSError:
                        pass
                    raise RuntimeError(f"依赖安装失败，已回退到 {old}，下次触发重试：{err or '未知错误'}")
                REQ_HASH_FILE.write_text(hash_now)
                deps_installed = True

            self._set(state="done", new_commit=new, updated=updated, deps_installed=deps_installed,
                      finished_at=_now(),
                      message=(f"代码已更新 {old} → {new}，重启容器后生效" if updated else f"已是最新（{new}）"))
            logger.info(f"在线更新完成：{old} → {new}（依赖{'已补装' if deps_installed else '无变化'}）")
        except Exception as e:
            cur = self._git(["rev-parse", "--short", "HEAD"])[1] or old
            self._set(state="failed", new_commit=cur, updated=False, finished_at=_now(), message=str(e))
            logger.error(f"在线更新失败：{e}")

    def _restart_run(self):
        """优雅收尾全部服务后 exec 自替换：同一容器/PID 载入磁盘新代码。

        收尾顺序与 main.py 的 SIGINT 处理一致（调度服务 → REST API → 配置
        守护线程），额外 dispose 数据库连接池——exec 不换 PID，POSIX 文件锁
        随进程保留，不清会卡住新进程写库。任一环节失败只记录并继续。
        """
        from src.service.downloader import downloader
        from src.service.updater import updater
        from src.server.rest_api import rest_api
        from src.config.config import ConfigManager
        from src.utils.database.database import DatabaseManager

        for service in (downloader, updater):
            try:
                service.stop()
            except Exception as e:
                logger.warning(f"热重启停止 {type(service).__name__} 时出错: {e}")
        if rest_api:
            try:
                rest_api.stop()
            except Exception as e:
                logger.warning(f"热重启停止 REST API 服务时出错: {e}")
        try:
            ConfigManager.stop_daemon()
        except Exception as e:
            logger.warning(f"热重启停止配置守护线程时出错: {e}")
        if DatabaseManager.engine:
            try:
                DatabaseManager.engine.dispose()
            except Exception as e:
                logger.warning(f"热重启释放数据库连接池时出错: {e}")

        try:
            commit = self._git(["rev-parse", "--short", "HEAD"])[1] or None
            LAST_APPLIED_FILE.write_text(json.dumps(
                {"commit": commit, "restarted_at": _now()}, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"热重启写生效标记失败（不影响重启本身）: {e}")

        logger.info("优雅收尾完成，正在以磁盘当前代码重启进程")
        os.chdir(APP_DIR)
        os.execv(sys.executable, [sys.executable, "main.py"])


def _now():
    """本地时间戳（秒级），用于 started_at / finished_at。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ==================== 全局实例 ====================

self_updater = SelfUpdater()
