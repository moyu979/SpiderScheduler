#用来下载的
from abc import ABC, abstractmethod
from component.tools.BlockingThreadPoolExecutor import BlockingThreadPoolExecutor as ThreadPoolExecutor
import datetime
from time import sleep
from typing import Any
import threading
import sqlite3
import os
import logging

import component.template as template
from component.assistant.database import Database as db
import component.assistant.data as conf

class Downloader:
    start_event = threading.Event()
    start_event.set()

    something_to_download_event = threading.Event()
    something_to_download_event.set()  # 设置事件，表示有东西可以下载

    def __init__(self,downloader):
        self.downloader=downloader

        self._lock = threading.Lock()

        self.executor = ThreadPoolExecutor(max_workers=conf.get("download_thread"))
        
        self._already_downloaded = 0
        
        threading.Thread(target=self.start).start()
        logging.info("Downloader initialized")

    def stop_down(self):
        """停止下载器"""
        logging.info("Stopping the downloader...")
        self.start_event.clear()  # 重置 start_event，停止下载器
    def start_down(self):
        """启动下载器"""
        logging.info("Starting the downloader...")
        self.start_event.set()  # 设置 start_event，启动下载器
    def add_sth(self):
        """设置 something_to_download_event 为触发状态"""
        logging.info("Setting something_to_download_event to triggered.")
        self.something_to_download_event.set()

    def adjust_thread_pool(self, new_max_threads):
        """动态调整线程池大小，迁移未完成任务"""
        if new_max_threads != self.max_threads:
            logging.info(f"Adjusting thread pool size from {self.max_threads} to {new_max_threads}")
            self.max_threads = new_max_threads
    
            # 获取旧线程池中的未完成任务
            pending_tasks = []
            for task in self.executor._work_queue.queue:
                pending_tasks.append(task)
    
            # 关闭旧线程池
            self.executor.shutdown(wait=True)
    
            # 创建新的线程池
            self.executor = ThreadPoolExecutor(max_workers=self.max_threads)
    
            # 将未完成任务提交到新线程池
            for task in pending_tasks:
                self.executor.submit(task)

    def start(self) -> None:
        """启动下载器"""
        while True:
            print(12345)
            # 等待 start_event 被触发
            if not self.start_event.wait(timeout=1):  # 每秒检查一次
                continue  # 如果事件未触发，继续等待

            if not self.something_to_download_event.wait(timeout=1):  # 每秒检查一次
                continue  # 如果事件未触发，继续等待

            with self._lock:
                if conf.get("once_download")>0 and self._already_downloaded >= conf.get("once_download"):
                    self.start_event.clear()  # 重置 start_event，停止下载器
                    self._already_downloaded=0
                    logging.info("已下载指定数量的作品，停止下载器")
                    continue
            print(123456)
            # 提交任务到线程池
            self.executor.submit(self.download_one)

    def download_one(self):
        print(111)
        conn=sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        try:
            # 开始事务
            conn.execute("BEGIN IMMEDIATE")

            # 查询 priority 最小的记录
            cursor.execute("""
                SELECT workNumber, downloadPriority, state
                FROM works
                WHERE state = 'inQueue'
                ORDER BY downloadPriority ASC
                LIMIT 1;
            """)
            row = cursor.fetchone()

            if row:
                record_id = row[0]
                # 更新记录状态为 'downloading'
                cursor.execute("""
                    UPDATE works
                    SET state = 'downloading'
                    WHERE workNumber = ?;
                """, (record_id,))
                conn.commit()
                logging.debug(f"Record {record_id} is now downloading.")
            else:
                Downloader.something_to_download_event.clear()  # 设置事件，表示没有更多任务
                logging.info("No records found with state 'inQueue'.")
                sleep(10)

        except sqlite3.Error as e:
            print(f"SQLite error: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

        # 下载
        down=self.downloader(record_id)
        result=down.download_it()
        # 处理下载结果
        if result=="success":#success
            try:
                # 开启一个新的事务
                conn = sqlite3.connect(db.db_path)
                cursor = conn.cursor()
                conn.execute("BEGIN IMMEDIATE")

                # 获取当前时间作为完成时间
                finished_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 更新数据库，将 state 设置为 'finished'，并记录完成时间
                cursor.execute("""
                    UPDATE works
                    SET state = 'finished', downloadDate = ?
                    WHERE workNumber = ?;
                """, (finished_time, record_id))
                conn.commit()
                logging.info(f"Record {record_id} marked as finished at {finished_time}.")
            except sqlite3.Error as e:
                logging.error(f"Failed to update record {record_id} to finished: {e}")
                conn.rollback()
            finally:
                cursor.close()
                conn.close()
            with self._lock:
                self._already_downloaded += 1
        elif result=="failed":
            try:
                # 开启一个新的事务
                conn = sqlite3.connect(db.db_path)
                cursor = conn.cursor()
                conn.execute("BEGIN IMMEDIATE")

                # 获取当前时间作为完成时间
                finished_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 更新数据库，将 state 设置为 'finished'，并记录完成时间
                cursor.execute("""
                    UPDATE works
                    SET state = 'failed'
                    WHERE workNumber = ?;
                """, (record_id))
                conn.commit()
                logging.info(f"Record {record_id} marked as failed at {finished_time}.")
            except sqlite3.Error as e:
                logging.error(f"Failed to update record {record_id} to finished: {e}")
                conn.rollback()
            finally:
                cursor.close()
                conn.close()

        elif result=="skip":
            pass
            #更新数据库

        else:
            try:
                # 开启一个新的事务
                conn = sqlite3.connect(db.db_path)
                cursor = conn.cursor()
                conn.execute("BEGIN IMMEDIATE")

                # 获取当前时间作为完成时间
                finished_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 更新数据库，将 state 设置为 'finished'，并记录完成时间
                cursor.execute("""
                    UPDATE works
                    SET state = 'failed'
                    WHERE workNumber = ?;
                """, (record_id))
                conn.commit()
                logging.info(f"Record {record_id} marked as failed at {finished_time}.")
            except sqlite3.Error as e:
                logging.error(f"Failed to update record {record_id} to finished: {e}")
                conn.rollback()
            finally:
                cursor.close()
                conn.close()

        with self._lock:
            self._thread_count -= 1