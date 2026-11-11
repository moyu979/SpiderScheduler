# requirements: requests
"""demo 站点更新器：对本地虚拟站点可运行的 UpdateUser 行为示例。

契约（注入属性、usr 快照、迭代协议、增量语义、cookie 两种传入方式、tools
能力）统一见基类模板 src/assets/scripts/update_a_user.py——本文件只演示
"怎么写"：website 声明、get_one_page/翻页、作品字典产出、cookie 解析优先级。

run_demo.py 会把 DEMO_BASE 改写为本地假站点地址；脚本按单文件动态加载，
因此与真实站点脚本一样各自携带工具函数（normalize_cookies），保证单文件
拷贝即可部署。
"""

import os
import time

import requests

from src.assets.scripts.update_a_user import UpdateUser


def normalize_cookies(cookies) -> str:
    """把三种常见 cookie 形态归一成 "k1=v1; k2=v2" 请求头字符串。

    Args:
        cookies: 支持以下三种形态，其余返回空串：
            - str: "k1=v1; k2=v2"（原样返回）
            - dict: {"name1": "value1", ...}，或单条 Selenium cookie
              （同时含 name/value 键）
            - list[dict]: Selenium 格式 [{"name": ..., "value": ...}, ...]，
              与 CookieManager 文件存储、浏览器 get_cookies()/add_cookie() 同构

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


class DemoUpdateUser(UpdateUser):
    """demo 站点更新脚本：可运行的 UpdateUser 行为示例。

    展示三类要点：website 路由声明、get_one_page 翻页与作品字典产出（从新
    到旧，翻页是否结束以站点的 hasMore 为准）、cookie 三级优先级解析（内存
    usr["cookies"] > 文件 cookie_manager > 匿名）。demo 站点会把收到的
    Cookie 回显在响应头，运行日志里可核对 cookie 来源链路。

    Attributes:
        website: 路由站点名，必须与 PublishPos.website 一致（此处固定 "demo"）。
        DEMO_BASE: demo 站点入口地址；run_demo.py 会改写本类属性指向本地
            假站点，真实站点脚本直接写死或用环境变量注入。
    """
    # 分发器按 website 路由：站点名必须与位点（PublishPos.website）一致
    website = "demo"

    # demo 站点地址：真实站点直接写死在这里，或用环境变量注入；
    # run_demo.py 会改写本类属性指向本地假站点
    DEMO_BASE = os.environ.get("DEMO_SITE_URL", "http://127.0.0.1:9377")

    def __init__(self, usr: dict, logging):
        """初始化 demo 更新器：调用基类后记录位点参数与内存 cookie 入口。

        Args:
            usr: 发布位点信息 {authorId, website, addTime}；
                内存传入方式额外约定 usr["cookies"] 携带 cookie（形态见
                normalize_cookies）。该键不是框架字段，仅供直接实例化时使用。
            logging: 框架日志对象（SpiderLogger），用法同 logger.info(...)。
        """
        super().__init__(usr, logging)
        usr = usr or {}
        self.usr = usr
        self.author_id = usr.get("authorId")
        self.website = usr.get("website") or self.website
        self.log = logging
        # 内存传入入口：位点参数里直接携带的 cookie
        self._payload_cookies = usr.get("cookies")
        self.page = 1
        self.works = []
        self._has_more = True

    # ---------------- cookie 解析 ----------------

    def _resolve_cookies(self):
        """按优先级解析 cookie，返回 (Cookie 请求头, 来源说明)。

        内存传入优先于文件传入：位点级显式参数覆盖站点全局登录态。
        """
        memory = normalize_cookies(self._payload_cookies)
        if memory:
            return memory, "内存传入 usr['cookies']"

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

    # ---------------- 翻页与迭代（框架调用面） ----------------

    def get_one_page(self) -> None:
        """请求一页作品列表（从新到旧），结果放进 self.works 并刷新 _has_more。"""
        header, source = self._resolve_cookies()
        url = f"{self.DEMO_BASE}/author/{self.author_id}/list"
        resp = requests.get(
            url,
            params={"page": self.page},
            # 文件/内存两种方式最终都归一成同一个 Cookie 请求头
            headers={"Cookie": header} if header else {},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # demo 站点把实际收到的 Cookie 回显在响应头里，运行时便于确认 cookie 生效
        self._log(
            f"[demo updater] author={self.author_id} page={self.page} "
            f"cookie来源={source} 站点收到Cookie={resp.headers.get('X-Received-Cookie') or '(无)'}"
        )

        self.works = list(data.get("works") or [])
        self._has_more = bool(data.get("hasMore"))

    def _log(self, message):
        """经框架日志对象输出日志；未注入时静默跳过。"""
        if self.log is not None:
            self.log.info(message)

    def __iter__(self):
        """重置翻页与迭代状态（框架对每个位点都重新迭代一次）。"""
        # 重置为初始状态（框架对每个位点都重新迭代一次）
        self.page = 1
        self.works = []
        self._has_more = True
        return self

    def __next__(self):
        """迭代协议：产出下一条作品；当前页消费完时按 page_interval 限速翻页。

        Returns:
            dict: 单条作品字典（至少含 workid）。

        Raises:
            StopIteration: 翻页后仍无数据或站点告知无更多页时结束迭代。
        """
        # 当前页消费完则翻下一页；翻页后仍无数据或站点告知无更多页即结束
        if not self.works:
            if not self._has_more:
                raise StopIteration
            # 翻页节奏：框架注入 page_interval 时在取下一页前等待
            # （演示站点为秒回，run_demo 不注入 → 不等待，不影响演示速度）
            interval = getattr(self, "page_interval", None)
            if interval and self.page > 1:
                time.sleep(max(0.0, float(interval)))
            self.get_one_page()
            self.page += 1
        if not self.works:
            raise StopIteration
        return self.works.pop(0)
