"""
按 website 存取登录 cookie。

存储位置：BASEPATH/datas/cookies/<website>.json，JSON 数组，每条 cookie 形如
{name, value, domain, path, expires, secure, ...}——与 Selenium get_cookies() 输出
兼容，可直接逐条 add_cookie 给浏览器；requests 场景用 get_header() 拼_COOKIE 头。

cookie 的产生走登录代理（src/server/apis/cookie_api.py）：cookie 不存在时由用户
在代理出的登录页里手动登录，代理捕获整个登录过程的 Set-Cookie 后落盘。
"""

import json
import os
from datetime import datetime

from src.config.paths import cookies_path
from src.utils.logging.logger import SpiderLogger as logger


class CookieNotFoundError(Exception):
    """指定 website 还没有已保存的登录 cookie。"""


class CookieManager:
    """按 website 读写 cookie 文件（静态方法集合，无实例状态）。

    存储为 JSON 数组，每条 cookie 与 Selenium get_cookies() 输出兼容，
    因此既能逐条 add_cookie 给浏览器，也能经 get_header() 拼成 requests 的
    Cookie 请求头。
    """

    @classmethod
    def _cookie_file(cls, website: str) -> str:
        """返回指定 website 的 cookie 文件路径。"""
        return os.path.join(cookies_path(), f"{website}.json")

    @classmethod
    def exists(cls, website: str) -> bool:
        """指定 website 是否已有可用的 cookie 文件。

        Args:
            website: 站点名。

        Returns:
            bool: cookie 文件存在为 True。
        """
        return os.path.exists(cls._cookie_file(website))

    @classmethod
    def save(cls, website: str, cookies: list) -> int:
        """覆盖保存指定 website 的 cookie 列表。

        先写临时文件再原子替换，调度线程并发读取（get/get_header）不会看到半截 JSON。

        Args:
            website: 站点名。
            cookies: cookie 列表（None 按空列表处理）。

        Returns:
            int: 实际写入的 cookie 条数。
        """
        os.makedirs(cookies_path(), exist_ok=True)
        path = cls._cookie_file(website)
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(list(cookies or []), f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        logger.info(f"已保存 {website} 的 cookie 共 {len(cookies or [])} 条: {path}")
        return len(cookies or [])

    @classmethod
    def get(cls, website: str) -> list:
        """返回指定 website 的 cookie 列表。

        Args:
            website: 站点名。

        Returns:
            list: cookie 字典列表（与 Selenium get_cookies() 输出兼容）。

        Raises:
            CookieNotFoundError: 未保存 cookie 或 cookie 文件为空。
        """
        path = cls._cookie_file(website)
        if not os.path.exists(path):
            raise CookieNotFoundError(
                f"website={website!r} 还没有登录 cookie；请在前端 Cookie 页完成手动登录，"
                f"或确认 {path} 存在"
            )
        with open(path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        if not cookies:
            raise CookieNotFoundError(f"website={website!r} 的 cookie 文件为空: {path}")
        return cookies

    @classmethod
    def get_header(cls, website: str) -> str:
        """把 cookie 拼成 'k1=v1; k2=v2' 形式，可直接作 requests 的 Cookie 请求头。

        Args:
            website: 站点名。

        Returns:
            str: Cookie 请求头字符串。
        """
        return '; '.join(f"{c['name']}={c['value']}" for c in cls.get(website))

    @classmethod
    def delete(cls, website: str) -> bool:
        """删除指定 website 的 cookie 文件。

        Args:
            website: 站点名。

        Returns:
            bool: 文件是否存在过（存在并已删除为 True）。
        """
        path = cls._cookie_file(website)
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"已删除 {website} 的 cookie: {path}")
            return True
        return False

    @classmethod
    def status(cls) -> list:
        """所有已保存 cookie 的概览。

        Returns:
            list[dict]: 每项形如 {website, cookieCount, updateTime}；文件损坏时
            cookieCount 为 -1（不静默吞掉）。
        """
        result = []
        directory = cookies_path()
        if not os.path.isdir(directory):
            return result
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith('.json'):
                continue
            path = os.path.join(directory, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    count = len(json.load(f) or [])
            except (OSError, ValueError):
                count = -1  # 文件损坏也暴露出来，别静默
            result.append({
                'website': filename[:-len('.json')],
                'cookieCount': count,
                'updateTime': datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec='seconds'),
            })
        return result
