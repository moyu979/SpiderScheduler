# requirements: requests
"""demo 站点下载器：对本地虚拟站点可运行的 DownloadWork 行为示例。

契约（注入属性、cookie 两种传入方式、返回值约定、tools 能力、依赖声明）
统一见基类模板 src/assets/scripts/download_a_work.py——本文件只演示"怎么写"：
website 声明、cookie 解析优先级（内存 downloadInfo["cookies"] > 文件
cookie_manager > 匿名）、产物写本任务目录并返回路径。

run_demo.py 会把 DEMO_BASE 改写为本地假站点地址；脚本按单文件动态加载，
因此与真实站点脚本一样各自携带工具函数（normalize_cookies），保证单文件
拷贝即可部署。
"""

import os

import requests

from src.assets.scripts.download_a_work import DownloadWork


def normalize_cookies(cookies) -> str:
    """把三种常见 cookie 形态归一成 "k1=v1; k2=v2" 请求头字符串。

    Args:
        cookies: 支持 str（"k1=v1; k2=v2" 原样返回）、{name: value} dict
            （或单条 Selenium cookie）、Selenium 格式 list[dict]，其余返回 ""。

    Returns:
        str: 可直接作 requests 的 Cookie 请求头的字符串，无 cookie 时为 ""。
    """
    if not cookies:
        return ""
    if isinstance(cookies, str):
        return cookies
    if isinstance(cookies, dict):
        if "name" in cookies and "value" in cookies:
            return f"{cookies['name']}={cookies['value']}"
        return "; ".join(f"{k}={v}" for k, v in cookies.items())
    if isinstance(cookies, (list, tuple)):
        parts = []
        for c in cookies:
            if isinstance(c, dict):
                if "name" in c:
                    parts.append(f"{c['name']}={c.get('value', '')}")
                else:
                    parts.extend(f"{k}={v}" for k, v in c.items())
            elif isinstance(c, str):
                parts.append(c)
        return "; ".join(parts)
    return ""


class DemoDownloadWork(DownloadWork):
    # 分发器按 website 路由：站点名必须与作品（Works.website）一致
    website = "demo"

    # demo 站点地址：真实站点直接写死在这里，或用环境变量注入；
    # run_demo.py 会改写本类属性指向本地假站点
    DEMO_BASE = os.environ.get("DEMO_SITE_URL", "http://127.0.0.1:9377")

    def __init__(self, work_info, download_path, download_info=None):
        """
        Args:
            work_info (dict): 作品快照，关键键 workNumber / website。
            download_path (str): 本任务专属目录，产物写在这里并返回路径。
            download_info (dict | None): downloadInfo 反序列化后的统一下载参数；
                内存传入方式约定其 "cookies" 键携带 cookie（形态见
                normalize_cookies），其余键按站点需要自由定义。
        """
        super().__init__(work_info, download_path, download_info)
        self.work_info = work_info or {}
        self.work_number = self.work_info.get("workNumber")
        self.website = self.work_info.get("website") or self.website
        self.download_path = download_path
        self.download_info = download_info or {}
        # 内存传入入口：统一下载参数里直接携带的 cookie
        self._payload_cookies = self.download_info.get("cookies")

    # ---------------- cookie 解析 ----------------

    def _resolve_cookies(self):
        """按优先级解析 cookie，返回 (Cookie 请求头, 来源说明)。

        内存传入优先于文件传入：任务级显式参数覆盖站点全局登录态。
        """
        memory = normalize_cookies(self._payload_cookies)
        if memory:
            return memory, "内存传入 download_info['cookies']"

        cm = getattr(self, "cookie_manager", None)
        if cm is not None and cm.exists(self.website):
            # 文件传入：读 BASEPATH/datas/cookies/<website>.json
            # 来源标注按注入的实现区分：框架默认注入 CookieManager 类（文件），
            # 嵌入式用法可注入同接口的内存实现（见 in_memory_cookie_manager.py）
            cm_name = cm.__name__ if isinstance(cm, type) else type(cm).__name__
            source = ("文件传入 cookie_manager" if cm_name == "CookieManager"
                      else f"cookie_manager[{cm_name}]")
            return cm.get_header(self.website), source

        return "", "无 cookie（未登录状态请求）"

    def _log(self, message):
        if self.logger is not None:
            self.logger.info(message)

    # ---------------- 下载（框架调用面） ----------------

    def download_it(self):
        """下载入口：拉取作品数据写入本任务目录，返回产物路径。"""
        header, source = self._resolve_cookies()
        url = f"{self.DEMO_BASE}/works/{self.work_number}/data"
        resp = requests.get(
            url,
            # 文件/内存两种方式最终都归一成同一个 Cookie 请求头
            headers={"Cookie": header} if header else {},
            timeout=30,
        )
        resp.raise_for_status()

        # demo 站点把实际收到的 Cookie 回显在响应头里，运行时便于核对
        self._log(
            f"[demo downloader] {self.work_number}@{self.website} "
            f"cookie来源={source} 站点收到Cookie={resp.headers.get('X-Received-Cookie') or '(无)'}"
        )

        target = os.path.join(self.download_path, f"{self.work_number}.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write(resp.text)

        # 返回产物路径（绝对或相对 download_path）；
        # 视频类站点可返回 {"path": target, "duration": 3.0} 供 waiting_play 使用
        return target
