from abc import ABC, abstractmethod

class UpdateUser:
    # 声明本类适用的站点，如 "pixiv"，也可以给列表 ["pixiv", "danbooru"]。
    # 同一文件可放多个站点的类；全部类都不声明时，本文件作为传统单站点脚本兜底。
    website = None

    # 框架注入：按 website 取登录 cookie。
    # cookie_manager.get(website) → [{name,value,domain,path,...}]（Selenium 兼容格式）
    # cookie_manager.get_header(website) → "k1=v1; k2=v2"（可直接作 requests 的 Cookie 头）
    cookie_manager = None

    def __init__(self, usr: dict, logging):
        # usr 是发布位点信息：{authorId, website, addTime}
        # 基础框架：仅保存必要状态，具体逻辑由子类实现
        self.author_id = usr.get('authorId') if isinstance(usr, dict) else None
        self.website = usr.get('website') if isinstance(usr, dict) else None
        self.page = 1
        self.works = []

    def get_one_page(self) -> None:
        pass

    def __iter__(self):
        # 重置为初始状态
        self.page = 1
        self.works = []
        return self

    def __next__(self):
        # 若当前无数据，请求下一页
        if len(self.works) == 0:
            self.get_one_page()
            self.page += 1
        # 若仍无数据，则视为迭代结束
        if len(self.works) == 0:
            raise StopIteration
        # 返回一个条目（应为字典，以适配上游处理）
        return self.works.pop(0)
