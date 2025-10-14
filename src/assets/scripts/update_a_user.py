
# 旧实现保留（已注释，仅供参考）
# 需要重写，用来更新某个用户信息，需要重写get_one_page方法，内容为一次获取若干内容，并使用page计数，然后存到self.works中
# from abc import ABC, abstractmethod
# import time
# import random
# from typing import List, Dict, Any, Optional
#
#
# class UpdateUser(ABC):
#     def __init__(self, usr: dict,logger):
#         #self.uid = uid
#         #self.page = 1
#         #self.works = []
#         #logger.info(f"初始化用户作品迭代器，用户ID: {self.uid}")
#
#     @abstractmethod
#     def get_one_page(self) -> None:
#         """
#         获取一页用户作品并添加到self.works中
#         
#         实现时应该将获取到的作品列表添加到self.works中
#         示例：self.works.extend([{\"id\": \"work1\"}, {\"id\": \"work2\"}])
#         """
#         logger.info(f"获取用户 {self.uid} 第 {self.page} 页作品")
#         
#         # 随机睡眠时间，模拟网络请求
#         sleep_time = random.uniform(1, 3)
#         logger.debug(f"模拟网络请求，耗时 {sleep_time:.1f} 秒")
#         time.sleep(sleep_time)
#         
#         # 随机生成3-5个作品数据
#         works_count = random.randint(3, 5)
#         mock_works = []
#         
#         for i in range(works_count):
#             # 随机生成work_id，范围在10000-99999之间
#             work_id = str(random.randint(10000, 99999))
#             mock_work = {
#                 "id": work_id,
#                 "title": f"作品 {work_id}",
#                 "page": self.page,
#                 "index": i + 1
#             }
#             mock_works.append(mock_work)
#         
#         # 将生成的作品添加到self.works中
#         self.works.extend(mock_works)
#         logger.info(f"获取到 {works_count} 个作品，当前页作品总数: {len(self.works)}")
#
#     def __iter__(self):
#         """重置迭代器状态"""
#         self.page = 1
#         self.works = []
#         return self
#
#     def __next__(self):
#         """获取下一个作品"""
#         # 如果当前页没有作品，获取下一页
#         if len(self.works) == 0:
#             try:
#                 self.get_one_page()
#                 self.page += 1
#             except Exception as e:
#                 logger.error(f"获取用户 {self.uid} 第 {self.page} 页失败: {e}")
#                 raise StopIteration
#         
#         # 如果获取后仍然没有作品，说明已到最后一页
#         if len(self.works) == 0:
#             logger.info(f"用户 {self.uid} 的所有作品已遍历完成")
#             raise StopIteration
#         
#         # 返回一个作品并从列表中移除
#         work = self.works.pop(0)
#         logger.debug(f"返回作品: {work.get('id', 'unknown')}")
#         return work


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