"""demo 驱动：本地起一个 "demo 站点"，用三种方式跑通 updater + downloader。

运行（任意目录均可，建议项目根目录）：
    python demos/run_demo.py

三个场景的 cookie 来源互不相同，每个场景结束后都会断言 demo 站点确实
收到了对应 cookie（站点把收到的 Cookie 回显在响应头/正文里）：

    [一] 文件传入 —— CookieManager.save() 把 cookie 落盘到
                    <临时 base_path>/datas/cookies/demo.json（等价于前端
                    Cookie 页登录代理的产物），脚本经框架注入的
                    cookie_manager 读取。实例化与注入方式完全照抄框架：
                    src/service/updater.py:276 / src/service/downloader.py:473。
    [二] 内存传入 —— 不读写任何 cookie 文件：updater 经 usr["cookies"]、
                    downloader 经 download_info["cookies"] 直接拿到 cookie。
    [三] 内存注入 —— 用 InMemoryCookieManager 顶替 CookieManager 注入
                    cookie_manager 属性，脚本代码零改动。

每个场景使用独立的临时目录，互不共享状态，便于单独理解每条 cookie 链路。
"""

import json
import logging
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 保证 src.*（项目根）与 demo 模块（demos/）都可直接 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_site_downloader import DemoDownloadWork
from demo_site_updater import DemoUpdateUser
from in_memory_cookie_manager import InMemoryCookieManager

# 与 CookieManager 文件存储同构的 Selenium 格式 cookie；三个场景用不同
# 的 value，服务端回显后即可区分 cookie 到底从哪条链路送达
DEMO_COOKIE = {"name": "sid", "value": "demo-secret-123", "domain": "127.0.0.1",
               "path": "/", "expires": None, "secure": False}

# demo 站点记录每个路径收到的 Cookie 头，供场景内断言使用
received_cookies = {}


class DemoSiteHandler(BaseHTTPRequestHandler):
    """最小假站点：作者作品列表 + 作品数据，把收到的 Cookie 原样回显。

    端点：
    - /author/<authorId>/list?page=N：返回该作者一页作品列表
      （{"works": [...], "hasMore": ...}，共 2 页）；
    - /works/<workNumber>：返回作品数据（{"work": ..., "cookieSeen": ...}）；
    - 其余路径返回 404。
    每个响应均带 X-Received-Cookie 头回显实际收到的 Cookie，供场景断言与
    脚本日志核对。
    """

    def _send(self, payload, status=200, extra_headers=None):
        """以 JSON 响应当前请求，可附加额外响应头。

        Args:
            payload: 序列化为 JSON 的响应正文对象。
            status: HTTP 状态码，默认 200。
            extra_headers: 附加响应头（如 X-Received-Cookie 回显），可省略。
        """
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """记录并回显 Cookie，然后按路径分流到作者列表、作品数据或 404。"""
        cookie = self.headers.get("Cookie", "")
        received_cookies[self.path] = cookie
        echo = {"X-Received-Cookie": cookie or "(none)"}

        if self.path.startswith("/author/"):
            author = self.path.split("/author/")[1].split("/")[0]
            page = 1
            if "page=" in self.path:
                try:
                    page = int(self.path.rsplit("page=", 1)[1])
                except ValueError:
                    pass
            works = [
                {"workid": f"demo-{author}-{page}-{i}",
                 "title": f"demo 作品 p{page}#{i}",
                 "upTime": f"2026-11-{page:02d} {i:02d}:00:00",
                 "kind": "image",
                 "state": None}
                for i in range(1, 3)
            ]
            self._send({"works": works, "hasMore": page < 2}, extra_headers=echo)
        elif self.path.startswith("/works/"):
            work = self.path.split("/works/")[1].split("/")[0]
            self._send({"work": work, "cookieSeen": cookie or "(none)"},
                       extra_headers=echo)
        else:
            self._send({"error": "not found"}, status=404)

    def log_message(self, *args):
        pass  # 静默 http.server 访问日志，demo 输出更清爽


# ---------------- 框架行为的等价复刻 ----------------

def make_work_info(item):
    """把 updater 产出的作品字典转成框架认领任务时的 work_info 快照。

    真实框架里这一步由数据库与认领查询完成（downloader.py:_claim_next_work）。
    """
    return {
        "workNumber": item.get("workid") or item.get("workNumber"),
        "website": "demo",
        "upTime": item.get("upTime"),
        "title": item.get("title"),
        "kind": item.get("kind"),
        "state": "downloading",
        "downloadDate": None,
        "downloadPriority": 0,
        "downloadInfo": None,
    }


def run_updater(author_id, cookies=None, cookie_manager=None, log=None):
    """按框架的方式实例化并消费一个 updater（updater.py:_update_position 等价）。"""
    usr = {"authorId": author_id, "website": "demo", "addTime": "2026-11-02 10:00:00"}
    if cookies is not None:
        usr["cookies"] = cookies  # 内存传入入口：框架快照无此键，仅直接实例化时有效
    updater = DemoUpdateUser(usr, log)
    if cookie_manager is not None:
        updater.cookie_manager = cookie_manager  # ← 框架注入点（updater.py:276）
    return list(updater)


def run_downloader(work_info, download_root, download_info=None, cookie_manager=None, log=None):
    """按框架的方式实例化并执行一个 downloader（downloader.py:_run_download_task 等价）。"""
    work_dir = os.path.join(download_root, str(work_info["workNumber"]))
    os.makedirs(work_dir, exist_ok=True)  # 框架会先建好本任务专属目录
    dl = DemoDownloadWork(work_info=work_info, download_path=work_dir,
                          download_info=download_info)
    dl.logger = log                       # ← 框架注入点（downloader.py:471-473）
    dl.config_manager = None
    if cookie_manager is not None:
        dl.cookie_manager = cookie_manager  # ← 框架注入点（downloader.py:473）
    return dl.download_it()


def cookie_reached(prefix, marker):
    """demo 站点是否在 prefix 开头的路径上收到过含 marker 的 Cookie 头。

    Args:
        prefix: 路径前缀，如 "/author/alice/list"。
        marker: 应出现在 Cookie 头中的片段，如 "sid=demo-secret-123"。

    Returns:
        bool: 收到过返回 True，否则 False。
    """
    return any(marker in cookie for path, cookie in received_cookies.items()
               if path.startswith(prefix))


# ---------------- 三个场景 ----------------

def scenario_1_file(base_url, log):
    """文件传入：cookie 落盘为 <base_path>/datas/cookies/demo.json，
    脚本通过框架注入的 CookieManager 读取。"""
    from src.config.config import ConfigManager
    from src.config.paths import cookies_path
    from src.utils.cookie_manager import CookieManager

    # 独立临时工作目录，等价于一次干净的部署（与 tests 的做法一致）
    work_root = Path(tempfile.mkdtemp(prefix="spider_demo_file_"))
    ConfigManager.base_path = str(work_root)

    # ① cookie 落盘 —— 正式部署里这一步由前端 Cookie 页的登录代理完成，
    #    产物是 BASEPATH/datas/cookies/<website>.json（Selenium 格式）
    cookie_file = os.path.join(cookies_path(), "demo.json")
    CookieManager.save("demo", [DEMO_COOKIE])
    log.info("cookie 文件已生成: %s", cookie_file)
    log.info("文件内容等价请求头: %s", CookieManager.get_header("demo"))

    # ② updater：注入 CookieManager（文件传入），迭代产出该位点的作品
    works = run_updater("alice", cookie_manager=CookieManager, log=log)
    assert works, "updater 未产出任何作品"
    assert cookie_reached("/author/alice/list", "sid=demo-secret-123"), \
        "站点未从文件传入链路收到 cookie"
    log.info("updater 产出 %d 个作品，cookie 经文件链路送达站点", len(works))

    # ③ downloader：同样的注入方式，逐个作品下载
    for item in works:
        artifact = run_downloader(make_work_info(item), str(work_root / "download"),
                                  cookie_manager=CookieManager, log=log)
        assert artifact and Path(artifact).exists(), f"产物缺失: {artifact}"
    assert cookie_reached("/works/demo-alice", "sid=demo-secret-123"), \
        "站点未从文件传入链路收到 cookie"
    log.info("downloader 完成 %d 个作品，产物位于 %s", len(works), work_root / "download")


def scenario_2_memory(base_url, log):
    """内存传入：不读写任何 cookie 文件。
    updater 走 usr["cookies"]（直接实例化时），downloader 走
    download_info["cookies"]（经框架调度流也有效，见下）。"""
    work_root = Path(tempfile.mkdtemp(prefix="spider_demo_mem_"))

    # 本场景刻意不注入 cookie_manager——cookie 只存在于任务参数里
    memory_cookies = [dict(DEMO_COOKIE, value="memory-payload-456")]

    # ① updater：位点参数直接携带 cookie（把脚本当库实例化的用法）
    works = run_updater("bob", cookies=memory_cookies, log=log)
    assert works, "updater 未产出任何作品"
    assert cookie_reached("/author/bob/list", "sid=memory-payload-456"), \
        "站点未从内存链路收到 cookie"
    log.info("updater 产出 %d 个作品，cookie 经任务参数送达站点（无任何文件读写）", len(works))

    # ② downloader：cookie 放进 download_info["cookies"]。
    #    真实调度流里，把这个字典序列化成 JSON 写进 works.downloadInfo 字段，
    #    框架下载时反序列化后原样传给脚本——cookie 随任务直达，全程不落盘。
    for idx, item in enumerate(works):
        # 演示两种等价形态：Selenium list[dict] 与 "k=v; k=v" 字符串
        payload = memory_cookies if idx == 0 else "sid=memory-payload-456"
        download_info = {"quality": "original", "cookies": payload}
        artifact = run_downloader(make_work_info(item), str(work_root / "download"),
                                  download_info=download_info, log=log)
        assert artifact and Path(artifact).exists(), f"产物缺失: {artifact}"
        # 站点把收到的 cookie 回显进正文，顺带验证请求头拼装正确
        assert "sid=memory-payload-456" in Path(artifact).read_text(encoding="utf-8"), \
            "产物中未见回显的 cookie"
    log.info("downloader 完成 %d 个作品，list 与字符串两种 cookie 形态均生效", len(works))


def scenario_3_inject(base_url, log):
    """内存注入：InMemoryCookieManager 顶替 CookieManager 注入 cookie_manager，
    脚本只认 get/get_header/exists 接口，实现零改动。"""
    work_root = Path(tempfile.mkdtemp(prefix="spider_demo_inject_"))

    cm = InMemoryCookieManager({"demo": [dict(DEMO_COOKIE, value="injected-789")]})

    works = run_updater("carol", cookie_manager=cm, log=log)
    assert works, "updater 未产出任何作品"
    assert cookie_reached("/author/carol/list", "sid=injected-789"), \
        "站点未从内存注入链路收到 cookie"

    for item in works:
        artifact = run_downloader(make_work_info(item), str(work_root / "download"),
                                  cookie_manager=cm, log=log)
        assert artifact and Path(artifact).exists(), f"产物缺失: {artifact}"
    assert cookie_reached("/works/demo-carol", "sid=injected-789"), \
        "站点未从内存注入链路收到 cookie"
    log.info("updater + downloader 共用一个内存 cookie 载体，脚本代码零改动")


SCENARIOS = [
    ("一、文件传入（CookieManager + cookie 文件）", scenario_1_file),
    ("二、内存传入（usr/download_info 任务参数携带）", scenario_2_memory),
    ("三、内存注入（InMemoryCookieManager 顶替）", scenario_3_inject),
]


def main():
    """启动本地 demo 站点，依次运行三个场景并输出 PASS/FAIL 汇总。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("demo.run")

    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoSiteHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    DemoUpdateUser.DEMO_BASE = base_url
    DemoDownloadWork.DEMO_BASE = base_url
    log.info("demo 站点已启动: %s", base_url)

    results = []
    for title, fn in SCENARIOS:
        log.info("=" * 72)
        log.info("场景%s", title)
        received_cookies.clear()
        try:
            fn(base_url, log)
            results.append((title, "PASS"))
        except Exception as exc:
            log.exception("场景失败: %s", exc)
            results.append((title, "FAIL"))

    server.shutdown()

    log.info("=" * 72)
    failed = [title for title, status in results if status == "FAIL"]
    for title, status in results:
        log.info("%s  %s", "PASS" if status == "PASS" else "FAIL", title)
    log.info("demo 结束：%d/%d 通过", len(results) - len(failed), len(results))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
