"""
按 website 存取登录 cookie（MetaManager 之上的常用封装）。

存储位置：BASEPATH/datas/meta/<website>/cookie.json，JSON 数组，每条
cookie 形如 {name, value, domain, path, expires, secure, ...}——与 Selenium
get_cookies() 输出兼容，可直接逐条 add_cookie 给浏览器；requests 场景用
get_header() 拼 Cookie 头。

Netscape 导出：you-get / yt-dlp 等命令行工具只认 Netscape cookies.txt
（--cookies 参数），netscape_file() 把 JSON 存储按需导出为站点 meta 目录
下的 cookies.txt（删除模式 "cookie*" 可把两个产物一并删掉），源 JSON 更新
后（按 mtime 判断）自动重新导出。脚本直接引用路径，无需自己转格式、造
临时文件；netscape_lines() 另提供任意 Selenium 格式列表到 Netscape 文本行
的纯转换（内存传入 cookie 的临时导出用）。

cookie 的产生走登录代理（src/server/apis/cookie_api.py）：cookie 不存在时
由用户在代理出的登录页里手动登录，代理捕获整个登录过程的 Set-Cookie 后
落盘。meta 目录里 cookie 之外的文件（session 等）归 MetaManager 与 meta
上传 API（src/server/apis/meta_api.py）管。
"""

import json
import os
from datetime import datetime

from src.config.paths import meta_path
from src.utils.logging.logger import SpiderLogger as logger
from src.utils.meta.meta_manager import MetaManager


class CookieNotFoundError(Exception):
    """指定 website 还没有已保存的登录 cookie。"""


class CookieManager:
    """按 website 读写登录 cookie（MetaManager 之上的常用封装，静态方法集合）。

    存储为 JSON 数组，每条 cookie 与 Selenium get_cookies() 输出兼容，
    因此既能逐条 add_cookie 给浏览器，也能经 get_header() 拼成 requests 的
    Cookie 请求头；netscape_file() 再提供面向 you-get 等 CLI 工具的
    Netscape cookies.txt 导出路径。文件机制（路径约定/原子写/删除）全部
    委托 MetaManager，本类只保留 cookie 域语义。

    Attributes:
        COOKIE_FILENAME: cookie 主存储的约定文件名（站点 meta 目录内）。
        NETSCAPE_FILENAME: Netscape 导出的约定文件名（同目录，删除模式
            "cookie*" 可把两者一并删掉）。
    """

    # cookie 主存储与 Netscape 导出的约定文件名（站点 meta 目录内）
    COOKIE_FILENAME = "cookie.json"
    NETSCAPE_FILENAME = "cookies.txt"

    # 会话 cookie 没有 expires，Netscape 导出时给的远期时间（2^31-1 内，
    # 兼容各 cookie 解析器）
    FAR_FUTURE_EXPIRY = 2147483647

    @classmethod
    def cookie_file(cls, website: str) -> str:
        """返回指定 website 的 cookie 存储文件路径（Selenium JSON 格式）。

        供需要感知原始文件的调用方使用；常规取值用 get() / get_header()。

        Args:
            website: 站点名。

        Returns:
            str: cookie 文件路径（BASEPATH/datas/meta/<website>/cookie.json）。
        """
        return MetaManager.file_path(website, cls.COOKIE_FILENAME)

    @classmethod
    def netscape_lines(cls, cookies: list) -> list:
        """把 Selenium 格式 cookie 列表转为 Netscape cookies.txt 行（纯转换）。

        每行：domain \\t include_subdomains \\t path \\t secure \\t expires \\t
        name \\t value；会话 cookie 无 expires 时填远期时间。缺 name 或 domain
        的条目无法在 Netscape 格式中表达，跳过并告警（不静默吞掉）。

        供两类调用方使用：netscape_file() 的按需导出，以及内存传入 cookie 的
        脚本侧临时导出（内存 cookie 不经框架存储，临时文件由脚本自管）。

        Args:
            cookies: Selenium 格式 cookie 字典列表。

        Returns:
            list[str]: 文本行列表（首行为 Netscape 文件头注释）。
        """
        lines = ["# Netscape HTTP Cookie File"]
        for c in cookies:
            name, domain = c.get("name"), (c.get("domain") or "").strip()
            if not name or not domain:
                logger.warning(f"导出 Netscape cookie 跳过无效条目: {c}")
                continue
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path") or "/"
            secure = "TRUE" if c.get("secure") else "FALSE"
            try:
                expires = int(float(c.get("expires") or cls.FAR_FUTURE_EXPIRY))
            except (TypeError, ValueError):
                expires = cls.FAR_FUTURE_EXPIRY
            lines.append("\t".join([domain, include_subdomains, path,
                                    secure, str(expires), name,
                                    str(c.get("value", ""))]))
        return lines

    @classmethod
    def netscape_file(cls, website: str) -> str:
        """返回 website 的 Netscape 格式 cookies.txt 路径（按需生成并跟随刷新）。

        you-get / yt-dlp 等命令行工具的 --cookies 参数只认 Netscape 格式；
        本方法把 Selenium JSON 存储导出为站点 meta 目录下的 cookies.txt：
        文件缺失或早于源 JSON 时自动重新导出（临时文件原子替换，调度线程
        并发调用安全）。返回的是框架管理的持久文件，脚本直接把路径拼进
        命令行即可，无需自行清理。

        Args:
            website: 站点名。

        Returns:
            str: 可直接传给 CLI 工具 --cookies 的 cookies.txt 路径。

        Raises:
            CookieNotFoundError: 未保存 cookie 或 cookie 文件为空（与 get 一致）。
        """
        source = cls.cookie_file(website)
        cookies = cls.get(website)  # 复用 get：统一处理缺失/空文件的报错
        target = MetaManager.file_path(website, cls.NETSCAPE_FILENAME)
        if (os.path.exists(target)
                and os.path.getmtime(target) >= os.path.getmtime(source)):
            return target
        MetaManager.save_file(website, cls.NETSCAPE_FILENAME,
                              ("\n".join(cls.netscape_lines(cookies)) + "\n").encode("utf-8"))
        return target

    @classmethod
    def exists(cls, website: str) -> bool:
        """指定 website 是否已有可用的 cookie 文件。

        Args:
            website: 站点名。

        Returns:
            bool: cookie 文件存在为 True。
        """
        return MetaManager.exists(website, cls.COOKIE_FILENAME)

    @classmethod
    def save(cls, website: str, cookies: list) -> int:
        """覆盖保存指定 website 的 cookie 列表。

        经 MetaManager 原子写（临时文件 + 替换），调度线程并发读取
        （get/get_header）不会看到半截 JSON。

        Args:
            website: 站点名。
            cookies: cookie 列表（None 按空列表处理）。

        Returns:
            int: 实际写入的 cookie 条数。
        """
        data = json.dumps(list(cookies or []), ensure_ascii=False, indent=2).encode("utf-8")
        MetaManager.save_file(website, cls.COOKIE_FILENAME, data)
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
        path = cls.cookie_file(website)
        if not os.path.exists(path):
            raise CookieNotFoundError(
                f"website={website!r} 还没有登录 cookie；请在前端 Cookie 页完成手动登录，"
                f"或确认 {path} 存在"
            )
        cookies = json.loads(MetaManager.read_file(website, cls.COOKIE_FILENAME).decode("utf-8"))
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
    def delete(cls, website: str, pattern: str = "cookie*") -> bool:
        """删除指定 website 的 cookie 相关文件（默认覆盖全部 cookie 产物）。

        Args:
            website: 站点名。
            pattern: meta 文件名通配模式（fnmatch 语义），默认 "cookie*"——
                cookie.json 与 Netscape 导出 cookies.txt 一并删除，站点
                meta 目录内的其他文件（session 等）不受影响。

        Returns:
            bool: 是否实际删除了文件。

        Raises:
            MetaFileError: 站点名或模式含路径分隔符等非法字符。
        """
        return bool(MetaManager.delete(website, pattern))

    @classmethod
    def status(cls) -> list:
        """所有已保存 cookie 的概览。

        扫描 meta 根下各站点目录的 cookie.json；meta 目录里的其他文件与
        非目录项不计入。

        Returns:
            list[dict]: 每项形如 {website, cookieCount, updateTime}；文件损坏时
            cookieCount 为 -1（不静默吞掉）。
        """
        result = []
        directory = meta_path()
        if not os.path.isdir(directory):
            return result
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name, cls.COOKIE_FILENAME)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    count = len(json.load(f) or [])
            except (OSError, ValueError):
                count = -1  # 文件损坏也暴露出来，别静默
            result.append({
                'website': name,
                'cookieCount': count,
                'updateTime': datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec='seconds'),
            })
        return result
