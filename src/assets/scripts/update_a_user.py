from abc import ABC, abstractmethod

class UpdateUser:
    def __init__(self, usr: dict,logging):
        # 基础框架：仅保存必要状态，具体逻辑由子类实现
        self.uid = usr.get('userId') if isinstance(usr, dict) else None
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