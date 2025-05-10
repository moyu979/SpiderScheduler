#用于对现有用户更新
from abc import ABC
from component.assistant.BlockingThreadPoolExecutor import BlockingThreadPoolExecutor as ThreadPoolExecutor
import datetime
import threading
import time
import sqlite3
import os
import logging

from component.assistant.database import Database as db
import component.assistant.data as conf
from component.template.update_a_user import UpdateUser
import component.downloader as downloader

class Register:
    def __init__(self,update_one_item:UpdateUser):
        self.update_one=update_one_item

    def add_a_user(self, user_id):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        try:
            # 开始事务
            conn.execute("BEGIN")
            now_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO user (userId, addTime) VALUES (?, ?)",
                (user_id, now_time)
            )
            # 提交事务
            conn.commit()
        except sqlite3.IntegrityError:
            # 捕获用户已存在的异常
            logging.warning("用户已经存在，什么都不做")
            conn.rollback()  # 回滚事务
        except Exception as e:
            # 捕获其他异常
            logging.error(f"添加用户时发生错误: {e}")
            conn.rollback()  # 回滚事务
        finally:
            conn.close()  # 确保连接被关闭
        logging.error(f"成功添加用户 {user_id}")   
        self.update_a_user(user_id)

    def change_work_priority(self, video_number, priority=0):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        try:
            # 开始事务
            conn.execute("BEGIN")
            cursor.execute(
                "UPDATE works SET downloadPriority=? WHERE workNumber=?",
                (priority, video_number)
            )
            # 提交事务
            conn.commit()
            logging.info(f"成功更新作品 {video_number} 的优先级为 {priority}")
        except sqlite3.Error as e:
            # 捕获数据库相关的异常
            logging.info(f"更新作品优先级时发生错误: {e}")
            conn.rollback()  # 回滚事务
        except Exception as e:
            # 捕获其他异常
            logging.error(f"未知错误: {e}")
            conn.rollback()  # 回滚事务
        finally:
            conn.close()  # 确保连接被关闭

    def add_work(self, work_number):
        conn = sqlite3.connect(os.path.join(conf.conf["data_path"], f"{conf.conf['db_name']}"))
        cursor = conn.cursor()
        try:
            # 开始事务
            conn.execute("BEGIN")
            cursor.execute(
                """
                INSERT INTO works (upTime, workNumber, title, kind, state, downloadDate, downloadPriority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("", work_number, "", "", "inQueue", "", 0)
            )
            # 提交事务
            conn.commit()
            logging.info(f"成功添加作品 {work_number}")
        except sqlite3.IntegrityError:
            # 捕获作品已存在的异常
            logging.warning(f"作品 {work_number} 已经存在，什么都不做")
            conn.rollback()  # 回滚事务
        except Exception as e:
            # 捕获其他异常
            logging.error(f"添加作品时发生错误: {e}")
            conn.rollback()  # 回滚事务
        finally:
            conn.close()  # 确保连接被关闭
        downloader.Downloader(work_number).something_to_download_event.set()  # 设置事件，表示有新任务可下载

    def update_a_user(self,user_id):
        count=0
        update_handle=self.update_one(user_id)
        conn=sqlite3.connect(db.db_path)
        for work in update_handle:
            logging.debug(f"正在更新用户 {user_id} 的作品 {work}")
            if work is None:
                break
            try:
                cursor = conn.cursor()
                # 开启事务
                conn.execute("BEGIN")

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
                count+=1
            except sqlite3.IntegrityError as e:
                count-=1
                conn.rollback()
                break

        conn.close()
        logging.info(f"更新用户 {user_id} 的作品成功,共更新 {count} 个作品")
        downloader.Downloader(work_number).something_to_download_event.set()  # 设置事件，表示有新任务可下载
