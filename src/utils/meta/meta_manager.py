"""站点 meta 文件基座：每个 website 一个独立目录的通用文件存取（字节级）。

存储位置：BASEPATH/datas/meta/<website>/，目录内文件名扁平、无子目录。
cookie 只是其中一种约定文件（cookie.json，见 CookieManager）；登录态
session、storageState、API token 等任意站点运行态文件都可直接放入，经
MetaManager 或 meta 上传 API（src/server/apis/meta_api.py）读写。

安全约定：站点名与文件名一律白名单校验（website ^[A-Za-z0-9_-]+$、文件名
^[A-Za-z0-9][A-Za-z0-9._-]*$，天然拒绝路径分隔符与 ..），杜绝路径穿越；
写入一律"临时文件 + 原子替换"，并发读写不会看到半截文件。
"""

import fnmatch
import os
import re
from datetime import datetime

from src.config.paths import meta_path
from src.utils.logging.logger import SpiderLogger as logger

# 站点名白名单：与 script_api / website_api 的 _NAME_RE 保持一致
_WEBSITE_RE = re.compile(r'^[A-Za-z0-9_\-]+$')
# meta 文件名白名单：字母/数字开头，仅含字母/数字/点/下划线/连字符
_FILENAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]*$')


class MetaFileError(Exception):
    """站点名、文件名或删除模式不满足白名单（防路径穿越）。"""


class MetaManager:
    """按 website 存取任意 meta 文件（静态方法集合，无实例状态）。

    字节级原语：只管路径约定、原子读写与删除，不解释内容格式。
    CookieManager 是其上的常用封装（cookie.json 约定 + Selenium/requests/
    Netscape 语义）；脚本与 meta 上传 API 直接使用本类管理任意 meta 文件。
    """

    @staticmethod
    def _check_website(website: str) -> None:
        """校验站点名白名单，不合法抛 MetaFileError。"""
        if not _WEBSITE_RE.match(website or ''):
            raise MetaFileError(f"非法站点名: {website!r}（仅允许字母/数字/下划线/连字符）")

    @classmethod
    def file_path(cls, website: str, filename: str) -> str:
        """返回站点 meta 目录内某文件的安全路径（不创建目录）。

        Args:
            website: 站点名。
            filename: meta 文件名（如 cookie.json、session.json）。

        Returns:
            str: 文件绝对路径（BASEPATH/datas/meta/<website>/<filename>）。

        Raises:
            MetaFileError: 站点名或文件名不满足白名单。
        """
        cls._check_website(website)
        if not _FILENAME_RE.match(filename or ''):
            raise MetaFileError(
                f"非法 meta 文件名: {filename!r}（须以字母/数字开头，仅含字母/数字/点/下划线/连字符）")
        return os.path.join(meta_path(), website, filename)

    @classmethod
    def dir(cls, website: str) -> str:
        """返回站点 meta 目录（不存在则创建）。

        Args:
            website: 站点名。

        Returns:
            str: 站点 meta 目录路径。

        Raises:
            MetaFileError: 站点名不满足白名单。
        """
        cls._check_website(website)
        directory = os.path.join(meta_path(), website)
        os.makedirs(directory, exist_ok=True)
        return directory

    @classmethod
    def exists(cls, website: str, filename: str) -> bool:
        """站点 meta 目录内某文件是否存在。

        Args:
            website: 站点名。
            filename: meta 文件名。

        Returns:
            bool: 文件存在为 True。

        Raises:
            MetaFileError: 站点名或文件名不满足白名单。
        """
        return os.path.exists(cls.file_path(website, filename))

    @classmethod
    def save_file(cls, website: str, filename: str, data: bytes) -> None:
        """原子保存 meta 文件（先写临时文件再替换，并发读不会看到半截内容）。

        Args:
            website: 站点名。
            filename: meta 文件名。
            data: 文件字节内容（任意格式，本层不解释）。

        Raises:
            MetaFileError: 站点名或文件名不满足白名单。
        """
        path = cls.file_path(website, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(data)
        os.replace(tmp_path, path)
        logger.info(f"已保存 {website} 的 meta 文件 {filename}: {path}（{len(data)} 字节）")

    @classmethod
    def read_file(cls, website: str, filename: str) -> bytes:
        """读取 meta 文件的字节内容。

        Args:
            website: 站点名。
            filename: meta 文件名。

        Returns:
            bytes: 文件字节内容。

        Raises:
            MetaFileError: 站点名或文件名不满足白名单。
            FileNotFoundError: 文件不存在（由调用方决定如何呈现）。
        """
        with open(cls.file_path(website, filename), 'rb') as f:
            return f.read()

    @classmethod
    def list_files(cls, website: str) -> list:
        """列出站点 meta 目录内的全部文件概览。

        Args:
            website: 站点名。

        Returns:
            list[dict]: 每项形如 {name, size, updateTime}，按文件名排序；
            目录不存在时为空列表（不报错，未上传过即无文件）。

        Raises:
            MetaFileError: 站点名不满足白名单。
        """
        cls._check_website(website)
        directory = os.path.join(meta_path(), website)
        if not os.path.isdir(directory):
            return []
        result = []
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            result.append({
                'name': name,
                'size': os.path.getsize(path),
                'updateTime': datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec='seconds'),
            })
        return result

    @classmethod
    def delete(cls, website: str, pattern: str) -> list:
        """按通配模式删除站点 meta 目录内的文件。

        模式只作用于该站点目录下的文件名（fnmatch 语义，如 "cookie*"）；
        目录结构约定扁平，子目录一律不动。

        Args:
            website: 站点名。
            pattern: 文件名通配模式。

        Returns:
            list[str]: 实际删除的文件名（按名字排序）；目录不存在时为空列表。

        Raises:
            MetaFileError: 站点名或模式含路径分隔符等非法字符。
        """
        cls._check_website(website)
        if os.sep in pattern or (os.altsep and os.altsep in pattern):
            raise MetaFileError(f"非法删除模式（不允许路径分隔符）: {pattern!r}")
        directory = os.path.join(meta_path(), website)
        if not os.path.isdir(directory):
            return []
        removed = []
        for name in sorted(os.listdir(directory)):
            if not fnmatch.fnmatchcase(name, pattern):
                continue
            path = os.path.join(directory, name)
            if os.path.isdir(path):
                continue
            os.remove(path)
            removed.append(name)
        if removed:
            logger.info(f"已删除 {website} 的 meta 文件 {len(removed)} 个: {', '.join(removed)}")
        return removed
