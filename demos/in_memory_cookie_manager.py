"""与 CookieManager 同接口的内存 cookie 载体。

框架默认把 CookieManager（文件传入，读写 BASEPATH/datas/cookies/<website>.json）
注入脚本的 cookie_manager 属性。当脚本被当库直接实例化、或宿主进程的 cookie
来自其他服务而不想落盘时，用本类顶替注入即可——get/get_header/exists/save/delete
接口与 CookieManager 完全一致，脚本代码零改动，cookie 全程只存在于内存。

用法（见 run_demo.py 场景三）：

    cm = InMemoryCookieManager({"demo": [{"name": "sid", "value": "m-1"}]})
    instance.cookie_manager = cm
"""


class CookieNotFoundError(Exception):
    """指定 website 还没有可用的 cookie（与 CookieManager 的行为一致）"""


class InMemoryCookieManager:
    """website -> cookie 列表 的内存字典，接口对齐 CookieManager。

    Cookie 条目沿用 Selenium 格式 {name, value, domain, path, ...}，因此
    get() 的结果可以直接逐条 add_cookie 给浏览器；get_header() 的结果可以
    直接作 requests 的 Cookie 请求头。与 CookieManager 的差别仅在于：
    CookieManager 以类方法集合读写磁盘文件，本类以实例方法读写内存字典，
    对脚本侧的调用写法没有影响（都是 cookie_manager.get_header(website)）。
    """

    def __init__(self, cookies: dict = None):
        """
        Args:
            cookies (dict): 预置数据 {website: [cookie 条目, ...]}，可省略，
                后续随时用 save() 补充。
        """
        self._store = {}
        for website, items in (cookies or {}).items():
            self.save(website, items)

    def exists(self, website: str) -> bool:
        """指定 website 是否已有可用的 cookie"""
        return bool(self._store.get(website))

    def save(self, website: str, cookies: list) -> int:
        """覆盖保存指定 website 的 cookie 列表，返回条数"""
        self._store[website] = list(cookies or [])
        return len(self._store[website])

    def get(self, website: str) -> list:
        """返回指定 website 的 cookie 列表；没有时抛 CookieNotFoundError"""
        cookies = self._store.get(website)
        if not cookies:
            raise CookieNotFoundError(f"内存 cookie 中没有 website={website!r} 的记录")
        return cookies

    def get_header(self, website: str) -> str:
        """把 cookie 拼成 "k1=v1; k2=v2"，可直接作 requests 的 Cookie 请求头"""
        return "; ".join(f"{c['name']}={c['value']}" for c in self.get(website))

    def delete(self, website: str) -> bool:
        """删除指定 website 的 cookie，返回是否存在过"""
        return self._store.pop(website, None) is not None
