"""
下载管理器
负责管理下载任务，控制下载线程，处理下载间隔
"""

import threading
import time
import datetime
from typing import Any, Optional
from ..utils.logger import logger
from ..utils.config import get_download_setting
from ..utils.BlockingThreadPoolExecutor import BlockingThreadPoolExecutor
from ..utils.database import Database


class Downloader:
    """
    下载管理器
    管理下载任务，控制下载线程，处理下载间隔
    """
    def __init__(self):
        logger.info("Downloader初始化")
        pass
    
    def init__(self, downloader_class):
        """
        初始化下载管理器
        
        Args:
            downloader_class: 下载器类，需要实现download_it方法
        """
        self.downloader_class = downloader_class
        
        # 事件控制
        
        self.start_event = threading.Event()
        self.start_event.set()  # 默认启动
        
        self.something_to_download_event = threading.Event()
        self.something_to_download_event.set()  # 默认有任务可下载
        
        # 信号量控制下载启动
        self.download_semaphore = threading.Semaphore(1)
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 配置参数
        self.download_thread = get_download_setting('download_thread')
        self.once_download = get_download_setting('once_download')
        self.download_interval = get_download_setting('download_interval')
        
        # 统计信息
        self._already_downloaded = 0
        self._total_download_time = 0
        
        # 启动主循环
        self._main_thread = threading.Thread(target=self._main_loop, daemon=True)
        self._main_thread.start()
        
        logger.info(f"下载管理器初始化完成，线程数: {self.download_thread}, 下载间隔: {self.download_interval}秒")
    
    def stop_download(self):
        """停止下载器"""
        logger.info("停止下载器...")
        self.start_event.clear()
        self.something_to_download_event.clear()
    
    def start_download(self):
        """启动下载器"""
        logger.info("启动下载器...")
        self.start_event.set()
        self.something_to_download_event.set()
    
    def add_download_task(self):
        """添加下载任务"""
        logger.info("添加下载任务...")
        self.something_to_download_event.set()
    
    def adjust_thread_pool(self, new_max_threads: int):
        """
        动态调整线程池大小
        
        Args:
            new_max_threads: 新的最大线程数
        """
        if new_max_threads != get_download_setting('download_thread'):
            logger.info(f"调整线程池大小从 {get_download_setting('download_thread')} 到 {new_max_threads}")
            self.executor.resize(new_max_threads)
    
    def _main_loop(self):
        """主循环"""
        logger.info("下载管理器主循环启动")
        
        # 记录批次开始时间
        batch_start_time = time.time()
        batch_downloaded_count = 0
        
        while True:
            try:
                # 等待启动事件
                if not self.start_event.wait(timeout=10):
                    continue
                
                # 等待有任务可下载
                if not self.something_to_download_event.wait(timeout=10):
                    continue
                
                # 检查是否需要开始新的批次
                current_time = time.time()
                elapsed_since_batch_start = current_time - batch_start_time
                
                # 如果once_download > 0 且已下载数量达到限制
                if get_download_setting('once_download') > 0 and batch_downloaded_count >= get_download_setting('once_download'):
                    # 计算需要等待的时间，确保两次开始下载的间隔严格等于download_interval
                    sleep_time = get_download_setting('download_interval') - elapsed_since_batch_start
                    
                    if sleep_time > 0:
                        logger.info(f"已下载指定数量 {get_download_setting('once_download')} 个作品，等待 {sleep_time:.2f} 秒后开始下一批")
                        time.sleep(sleep_time)
                    
                    # 重置批次状态
                    batch_start_time = time.time()
                    batch_downloaded_count = 0
                    logger.info("开始新批次下载")
                    continue
                
                # 获取下载任务
                work_id = self._get_next_download_task()
                if work_id is None:
                    logger.debug("没有找到可下载的任务")
                    self.something_to_download_event.clear()
                    time.sleep(10)
                    continue
                
                # 提交下载任务到线程池
                self.executor.submit(self._download_one_work, work_id)
                
                # 增加批次下载计数
                batch_downloaded_count += 1
                
            except Exception as e:
                logger.error(f"下载管理器主循环异常: {e}")
                time.sleep(5)
    
    def _get_next_download_task(self) -> Optional[str]:
        """
        从数据库获取下一个下载任务
        
        Returns:
            str: 作品ID，如果没有任务则返回None
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # 查询优先级最高的待下载任务
                cursor.execute("""
                    SELECT workNumber, downloadPriority, state
                    FROM works
                    WHERE state = 'inQueue'
                    ORDER BY downloadPriority ASC
                    LIMIT 1;
                """)
                row = cursor.fetchone()
                
                if row:
                    work_id = row[0]
                    # 更新状态为下载中
                    cursor.execute("""
                        UPDATE works
                        SET state = 'downloading'
                        WHERE workNumber = ?;
                    """, (work_id,))
                    conn.commit()
                    logger.debug(f"任务 {work_id} 状态更新为下载中")
                    return work_id
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"获取下载任务失败: {e}")
            return None
    
    def _download_one_work(self, work_id: str):
        """
        下载一个作品
        
        Args:
            work_id: 作品ID
        """
        start_time = time.time()
        logger.info(f"开始下载作品 {work_id}")
        
        try:
            # 创建下载器实例
            downloader = self.downloader_class(work_id)
            
            # 执行下载
            result = downloader.download_it()
            
            # 计算下载时间
            download_time = time.time() - start_time
            
            # 处理下载结果
            self._handle_download_result(work_id, result, download_time)
            
            # 更新总统计信息
            with self._lock:
                self._already_downloaded += 1
                self._total_download_time += download_time
            
            logger.info(f"作品 {work_id} 下载完成，耗时: {download_time:.2f}秒")
            
        except Exception as e:
            logger.error(f"下载作品 {work_id} 失败: {e}")
            self._handle_download_result(work_id, "failed", time.time() - start_time)
    
    def _handle_download_result(self, work_id: str, result: Any, download_time: float):
        """
        处理下载结果
        
        Args:
            work_id: 作品ID
            result: 下载结果
            download_time: 下载耗时
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # 获取当前时间
                finished_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if result.get('status') == 'success':
                    # 下载成功
                    cursor.execute("""
                        UPDATE works
                        SET state = 'finished', downloadDate = ?, downloadTime = ?
                        WHERE workNumber = ?;
                    """, (finished_time, download_time, work_id))
                    logger.info(f"作品 {work_id} 标记为完成")
                    
                elif result.get('status') == 'failed':
                    # 下载失败
                    cursor.execute("""
                        UPDATE works
                        SET state = 'failed', downloadDate = ?, downloadTime = ?
                        WHERE workNumber = ?;
                    """, (finished_time, download_time, work_id))
                    logger.warning(f"作品 {work_id} 标记为失败")
                    
                else:
                    # 其他状态
                    cursor.execute("""
                        UPDATE works
                        SET state = 'failed', downloadDate = ?, downloadTime = ?
                        WHERE workNumber = ?;
                    """, (finished_time, download_time, work_id))
                    logger.warning(f"作品 {work_id} 未知状态，标记为失败")
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"处理下载结果失败: {e}")
    
    def get_stats(self) -> dict:
        """
        获取下载器统计信息
        
        Returns:
            dict: 统计信息
        """
        with self._lock:
            return {
                'started': self.start_event.is_set(),
                'has_tasks': self.something_to_download_event.is_set(),
                'download_thread': get_download_setting('download_thread'),
                'once_download': get_download_setting('once_download'),
                'download_interval': get_download_setting('download_interval'),
                'already_downloaded': self._already_downloaded,
                'total_download_time': self._total_download_time,
                'thread_pool_stats': self.executor.get_stats()
            }
    
    def log_stats(self):
        """记录统计信息"""
        stats = self.get_stats()
        logger.info(f"下载器统计 - 已下载: {stats['already_downloaded']}, "
                   f"总耗时: {stats['total_download_time']:.2f}秒, "
                   f"线程池: {stats['thread_pool_stats']['active_tasks']}活跃/{stats['thread_pool_stats']['completed_tasks']}完成")
    
    def shutdown(self):
        """关闭下载器"""
        logger.info("关闭下载器...")
        self.stop_download()
        self.executor.shutdown(wait=True)
        logger.info("下载器已关闭")
