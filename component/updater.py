#用于对现有用户更新
from abc import ABC
from component.assistant.BlockingThreadPoolExecutor import BlockingThreadPoolExecutor as ThreadPoolExecutor
import threading
import time
import sqlite3
import os
import logging

from component.assistant.database import Database as db
import component.assistant.data as conf
from component.template.update_a_user import UpdateUser
import component.downloader as downloader
class Updater(ABC):
    def __init__(self,update_one_item):
        self.update_one=update_one_item
        self.auto_update=threading.Event()
        if conf.get("auto_update"):
            self.auto_update.set()
        self.executor = ThreadPoolExecutor(max_workers=conf.get("update_thread"))
        self.update_count=0

        self.lock = threading.Lock()
        self.cut_down=0

        threading.Thread(target=self.daily_update).start()
        logging.info("Updater initialized")

    def daily_update(self):
        while True:
            while self.cut_down>0:
                with self.lock:
                    self.cut_down-=1
                time.sleep(1)
            with self.lock:
                self.cut_down=conf.get("update_interval")

            if not self.auto_update.wait(timeout=10):
                logging.info("自动更新未启动，等待中")
                continue
            self.update_count+=1
            logging.info(f"第{self.update_count}次自动更新已启动")
            
            conn=sqlite3.connect(db.db_path)
            cursor=conn.cursor()
            conn.execute("BEGIN EXCLUSIVE")
            users=cursor.execute("SELECT * FROM user").fetchall()
            conn.commit()
            conn.close()
            for user in users:
                logging.info(f"{user[0]}正在更新")
                self.executor.submit(self.update_a_user,user[0])

            logging.info(f"第{self.update_count}次自动更新已完成")
            
    def update_a_user(self,user_id):
        update_handle=self.update_one(user_id)
        conn=sqlite3.connect(db.db_path)
        for work in update_handle:
            if work is None:
                break
            try:
                cursor = conn.cursor()
                # 开启事务
                conn.execute("BEGIN EXCLUSIVE")

                # 插入 works 表，主键冲突时跳过（使用 INSERT OR IGNORE）
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO works 
                    (upTime, workNumber, title, kind, state, downloadDate, downloadPriority) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, 
                    work
                )

                # 插入 uploads 表，主键冲突将抛出异常（默认行为）
                cursor.execute(
                    """
                    INSERT INTO upload 
                    (userId, workNumber) 
                    VALUES (?, ?)
                    """, 
                    (user_id, work[1])
                )

                conn.commit()
            except sqlite3.IntegrityError as e:
                conn.rollback()
                break

        conn.close()
        logging.info(f"更新用户 {user_id} 的作品成功")
        downloader.Downloader.something_to_download_event.set()  # 设置事件，表示有新任务可下载

    def auto_update_start(self):
        logging.info("自动更新正在启动")
        self.auto_update.set()
        logging.info("自动更新已经启动")

    def auto_update_stop(self):
        logging.info("自动更新正在停止")
        self.auto_update.clear()
        logging.info("自动更新已经停止")

    def update_immediate(self):
        logging.info("立即更新正在启动")
        with self.lock:
            self.cut_down=0
        logging.info(f"第{self.update_count}次立即更新已启动")
        