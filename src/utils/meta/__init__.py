"""站点 meta 子包：通用 meta 文件基座与 cookie 高级封装。

- MetaManager（meta_manager.py）：字节级的按站点文件存取基座——路径约定
  （BASEPATH/datas/meta/<website>/，扁平无子目录）、白名单校验、原子读写
  与通配删除，不解释内容格式；
- CookieManager（cookie_manager.py）：基座之上的 cookie 常用封装
  （cookie.json 约定 + Selenium/requests/Netscape 语义）。

调用方统一从本包导入：`from src.utils.meta import CookieManager, MetaManager`。
"""

from src.utils.meta.cookie_manager import CookieManager, CookieNotFoundError
from src.utils.meta.meta_manager import MetaManager, MetaFileError

__all__ = ["MetaManager", "MetaFileError", "CookieManager", "CookieNotFoundError"]
