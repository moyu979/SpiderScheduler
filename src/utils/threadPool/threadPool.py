from concurrent.futures import ThreadPoolExecutor, Future
from threading import Semaphore, Lock, Event
import time
import threading
from src.utils.logging.logger import SpiderLogger as logger

class ThreadPool(ThreadPoolExecutor):
    """
    阻塞式线程池执行器
    维持指定数量的线程运行，当所有线程都在工作时，新的任务会阻塞等待
    """
    
    def __init__(self, max_workers, name="BlockingThreadPool"):
        super().__init__(max_workers=max_workers)
        self._sema = Semaphore(max_workers)
        self._name = name
        self._lock = Lock()
        self._active_tasks = 0
        self._completed_tasks = 0
        self._failed_tasks = 0
        self._shutdown_event = Event()
        self._max_workers = max_workers
        self._resizing = False
        self._target_workers = None
        
        logger.info(f"创建线程池: {name}, 最大线程数: {max_workers}")
    
    def submit(self, fn, *args, **kwargs):
        """
        提交任务到线程池
        如果所有线程都在工作，会阻塞等待直到有线程空闲
        """
        if self._shutdown_event.is_set():
            raise RuntimeError("线程池已关闭")
        
        # 阻塞直到有一个线程空闲
        logger.debug(f"等待可用线程... (当前活跃任务: {self._active_tasks})")
        self._sema.acquire()
        
        with self._lock:
            self._active_tasks += 1
            logger.debug(f"获取到线程，开始执行任务 (活跃任务: {self._active_tasks})")
        
        def wrap_fn(*args, **kwargs):
            task_id = threading.current_thread().ident
            start_time = time.time()
            
            try:
                logger.debug(f"线程 {task_id} 开始执行任务")
                result = fn(*args, **kwargs)
                logger.debug(f"线程 {task_id} 任务执行成功，耗时: {time.time() - start_time:.2f}秒")
                return result
            except Exception as e:
                with self._lock:
                    self._failed_tasks += 1
                logger.error(f"线程 {task_id} 任务执行失败: {e}")
                raise
            finally:
                with self._lock:
                    self._active_tasks -= 1
                    self._completed_tasks += 1
                self._sema.release()
                logger.debug(f"线程 {task_id} 释放，当前活跃任务: {self._active_tasks}")
        
        return super().submit(wrap_fn, *args, **kwargs)
    

    
    def get_stats(self):
        """获取线程池统计信息"""
        with self._lock:
            return {
                'name': self._name,
                'max_workers': self._max_workers,
                'active_tasks': self._active_tasks,
                'completed_tasks': self._completed_tasks,
                'failed_tasks': self._failed_tasks,
                'available_threads': self._sema._value,
                'is_shutdown': self._shutdown_event.is_set(),
                'is_resizing': self._resizing,
                'target_workers': self._target_workers
            }
    
    def log_stats(self):
        """记录线程池统计信息"""
        stats = self.get_stats()
        logger.info(f"线程池统计 - {stats['name']}: "
                   f"活跃任务={stats['active_tasks']}, "
                   f"已完成={stats['completed_tasks']}, "
                   f"失败={stats['failed_tasks']}, "
                   f"可用线程={stats['available_threads']}")
    
    def shutdown(self, wait=True, *, cancel_futures=False):
        """关闭线程池"""
        logger.info(f"开始关闭线程池: {self._name}")
        self._shutdown_event.set()
        
        # 记录最终统计信息
        self.log_stats()
        
        super().shutdown(wait=wait, cancel_futures=cancel_futures)
        logger.info(f"线程池已关闭: {self._name}")
    
    def wait_for_completion(self, timeout=None):
        """
        等待所有任务完成
        """
        logger.info(f"等待所有任务完成...")
        start_time = time.time()
        
        while True:
            with self._lock:
                if self._active_tasks == 0:
                    logger.info(f"所有任务已完成，总耗时: {time.time() - start_time:.2f}秒")
                    return True
            
            if timeout and (time.time() - start_time) > timeout:
                logger.warning(f"等待超时 ({timeout}秒)")
                return False
            
            time.sleep(0.1)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)
        return False
    
    def get_max_workers(self):
        """获取当前最大线程数"""
        return self._max_workers

if __name__ == "__main__":
    # 示例用法
    def task(n):
        logger.info(f"任务 {n} 开始执行")
        time.sleep(2)
        logger.info(f"任务 {n} 执行完成")
        return f"任务 {n} 的结果"
    
    # 直接使用线程池
    pool = BlockingThreadPoolExecutor(max_workers=2, name="测试池")
    
    # 提交任务
    futures = []
    for i in range(5):
        logger.info(f"提交任务 {i}")
        future = pool.submit(task, i)
        futures.append(future)
    
    # 等待所有任务完成
    pool.wait_for_completion()
    
    # 获取结果
    for i, future in enumerate(futures):
        try:
            result = future.result()
            logger.info(f"任务 {i} 结果: {result}")
        except Exception as e:
            logger.error(f"任务 {i} 执行失败: {e}")
    
    # 演示线程数调整
    logger.info("演示线程数调整功能")
    
    # 增加线程数
    pool.resize(4)
    logger.info(f"当前最大线程数: {pool.get_max_workers()}")
    
    # 检查是否可以减少线程数
    if pool.can_reduce_workers():
        pool.resize(1)
        logger.info("成功减少线程数")
    else:
        logger.info("当前有活跃任务，无法减少线程数")
    
    # 强制调整线程数
    pool.force_resize(2)
    logger.info(f"强制调整后的线程数: {pool.get_max_workers()}")
    
    # 关闭线程池
    pool.shutdown()
