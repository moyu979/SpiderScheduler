import threading
import time
import sqlite3
from abc import ABC, abstractmethod
from typing import Callable, Type
from src.logger import logger
import src.configs.config as config

from src.database import db_manager


class Updater(ABC):
    """
    用户更新器
    每隔配置中的check_interval时间，检查数据库中所有用户的uid，
    为每个用户创建对应的update_a_user类实例，使用迭代器方式检查更新
    """
    def __init__(self):
        logger.info("Updater初始化")
        pass

    def init__(self, update_user_class):
        """
        初始化更新器
        
        Args:
            update_user_class: UpdateUser的子类，用于处理特定用户的更新
        """
        self.auto_update = threading.Event()
        self.auto_update.set()
        
        

        # 统计信息
        self.update_count = 0
        self.lock = threading.Lock()
        self.countdown = 0
        
        # 启动自动更新线程
        self.update_thread_obj = threading.Thread(
            target=self._daily_update, 
            daemon=True,
            name="AutoUpdateThread"
        )
        self.update_thread_obj.start()
        
        logger.info(f"用户更新器初始化完成，更新线程数: {self.update_thread}, 检查间隔: {self.check_interval}秒")
    
    def _daily_update(self):
        """自动更新主循环"""
        logger.info("自动更新线程已启动")
        
        while True:
            try:
                # 等待倒计时结束
                while self.countdown > 0:
                    with self.lock:
                        self.countdown -= 1
                    time.sleep(1)
                
                # 重置倒计时
                with self.lock:
                    self.countdown = self.check_interval
                
                # 检查是否启用自动更新
                if not self.auto_update.wait(timeout=10):
                    logger.info("自动更新未启动，等待中...")
                    continue
                
                # 执行更新
                self.update_count += 1
                logger.info(f"第 {self.update_count} 次自动更新已启动")
                
                # 获取所有用户
                users = self._get_all_users()
                if not users:
                    logger.info("数据库中没有用户，跳过本次更新")
                    continue
                
                logger.info(f"找到 {len(users)} 个用户，开始更新")
                
                # 为每个用户提交更新任务
                for user_id in users:
                    logger.info(f"提交用户 {user_id} 的更新任务")
                    self.executor.submit(self._update_a_user, user_id)
                
                logger.info(f"第 {self.update_count} 次自动更新任务已提交完成")
                
            except Exception as e:
                logger.error(f"自动更新循环发生错误: {e}")
                time.sleep(60)  # 发生错误时等待1分钟再继续
    
    def _get_all_users(self) -> list:
        """
        从数据库获取所有用户的uid
        
        Returns:
            list: 用户uid列表
        """
        try:
            conn = db_manager.get_connection()
            if not conn:
                logger.error("无法获取数据库连接")
                return []
            
            cursor = conn.cursor()
            
            # 获取所有用户uid
            cursor.execute("SELECT uid FROM user")
            users = cursor.fetchall()
            
            # 提取uid
            user_ids = [user[0] for user in users]
            
            cursor.close()
            db_manager.close_connection()
            
            logger.debug(f"从数据库获取到 {len(user_ids)} 个用户")
            return user_ids
            
        except Exception as e:
            logger.error(f"获取用户列表失败: {e}")
            return []
    
    def _update_a_user(self, user_id: str):
        """
        更新单个用户的作品
        
        Args:
            user_id: 用户ID
        """
        logger.info(f"开始更新用户 {user_id} 的作品")
        
        try:
            # 创建用户更新器实例
            update_handler = self.update_user_class(user_id)
            
            # 获取数据库连接
            conn = db_manager.get_connection()
            if not conn:
                logger.error(f"用户 {user_id} 更新失败：无法获取数据库连接")
                return
            
            cursor = conn.cursor()
            
            # 使用迭代器遍历用户作品
            for work in update_handler:
                if work is None:
                    logger.warning(f"用户 {user_id} 获取到空作品，跳过")
                    continue
                
                try:
                    # 开启事务
                    conn.execute("BEGIN EXCLUSIVE")
                    
                    # 检查作品是否已存在
                    work_id = work.get('id')
                    if not work_id:
                        logger.warning(f"作品缺少ID字段，跳过: {work}")
                        continue
                    
                    # 检查works表中是否已存在该作品
                    cursor.execute(
                        "SELECT workNumber FROM works WHERE workNumber = ?",
                        (work_id,)
                    )
                    
                    if cursor.fetchone():
                        logger.info(f"用户 {user_id} 的作品 {work_id} 已存在，停止更新")
                        conn.commit()
                        break
                    
                    # 插入新作品到works表
                    # 假设work的格式为: [upTime, workNumber, title, kind, state, downloadDate, downloadPriority]
                    work_data = [
                        work.get('upTime', ''),
                        work.get('id', ''),
                        work.get('title', ''),
                        work.get('kind', ''),
                        work.get('state', ''),
                        work.get('downloadDate', ''),
                        work.get('downloadPriority', 0)
                    ]
                    
                    cursor.execute(
                        """
                        INSERT INTO works 
                        (upTime, workNumber, title, kind, state, downloadDate, downloadPriority) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        work_data
                    )
                    
                    # 插入用户-作品关联到upload表
                    cursor.execute(
                        """
                        INSERT INTO upload 
                        (userId, workNumber) 
                        VALUES (?, ?)
                        """,
                        (user_id, work_id)
                    )
                    
                    conn.commit()
                    logger.debug(f"用户 {user_id} 作品 {work_id} 已添加到数据库")
                    
                except sqlite3.IntegrityError as e:
                    # 主键冲突，说明作品已存在
                    conn.rollback()
                    logger.info(f"用户 {user_id} 的作品 {work_id} 已存在（主键冲突），停止更新")
                    break
                    
                except Exception as e:
                    conn.rollback()
                    logger.error(f"用户 {user_id} 作品 {work_id} 插入失败: {e}")
                    continue
            
            cursor.close()
            db_manager.close_connection()
            
            logger.info(f"用户 {user_id} 的作品更新完成")
            
            # 通知下载器有新任务可下载
            self._notify_new_downloads()
            
        except Exception as e:
            logger.error(f"更新用户 {user_id} 失败: {e}")
    
    def _notify_new_downloads(self):
        """通知下载器有新任务可下载"""
        try:
            # 这里可以设置一个事件来通知下载器
            # 暂时使用日志记录
            logger.info("有新作品添加到数据库，可以触发下载任务")
        except Exception as e:
            logger.error(f"通知下载器失败: {e}")
    
    def auto_update_start(self):
        """启动自动更新"""
        logger.info("自动更新正在启动")
        self.auto_update.set()
        logger.info("自动更新已经启动")
    
    def auto_update_stop(self):
        """停止自动更新"""
        logger.info("自动更新正在停止")
        self.auto_update.clear()
        logger.info("自动更新已经停止")
    
    def update_immediate(self):
        """立即执行一次更新"""
        logger.info("立即更新正在启动")
        with self.lock:
            self.countdown = 0
        logger.info("立即更新已触发")
    
    def get_stats(self):
        """获取更新器统计信息"""
        executor_stats = self.executor.get_stats()
        return {
            'update_count': self.update_count,
            'auto_update_enabled': self.auto_update.is_set(),
            'countdown': self.countdown,
            'check_interval': self.check_interval,
            'executor_stats': executor_stats
        }
    
    def shutdown(self):
        """关闭更新器"""
        logger.info("正在关闭用户更新器")
        self.auto_update_stop()
        self.executor.shutdown(wait=True)
        logger.info("用户更新器已关闭")
