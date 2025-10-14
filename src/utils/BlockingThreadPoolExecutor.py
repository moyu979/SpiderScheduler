from concurrent.futures import ThreadPoolExecutor, Future
from threading import Semaphore, Lock, Event
import time
import threading
from src.utils.logging.logger import SpiderLogger as logger

class BlockingThreadPoolExecutor(ThreadPoolExecutor):
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
        
        # 检查是否正在调整线程数
        if self._resizing:
            logger.warning(f"线程池正在调整大小到 {self._target_workers}，任务提交被阻塞")
            # 等待调整完成
            while self._resizing:
                time.sleep(0.1)
        
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
    
    def resize(self, new_max_workers):
        """
        动态调整线程池大小
        注意：只能增加线程数，不能减少（因为可能有正在执行的任务）
        """
        if self._shutdown_event.is_set():
            raise RuntimeError("线程池已关闭，无法调整大小")
        
        if new_max_workers <= 0:
            raise ValueError("线程数必须大于0")
        
        with self._lock:
            old_max_workers = self._max_workers
            
            if new_max_workers < old_max_workers:
                logger.warning(f"尝试减少线程数从 {old_max_workers} 到 {new_max_workers}，"
                             f"但当前有 {self._active_tasks} 个活跃任务，"
                             f"建议等待任务完成后再减少线程数")
                return False
            
            # 更新线程池大小
            self._max_workers = new_max_workers
            
            # 更新信号量（增加可用线程数）
            additional_threads = new_max_workers - old_max_workers
            for _ in range(additional_threads):
                self._sema.release()
            
            logger.info(f"线程池 {self._name} 线程数从 {old_max_workers} 调整到 {new_max_workers}")
            return True
    
    def get_max_workers(self):
        """获取当前最大线程数"""
        return self._max_workers
    
    def can_reduce_workers(self):
        """检查是否可以安全地减少线程数"""
        with self._lock:
            return self._active_tasks == 0
    
    def force_resize(self, new_max_workers):
        """
        强制调整线程池大小（包括减少线程数）
        注意：减少线程数时，新的任务提交会阻塞直到活跃任务数减少
        """
        if self._shutdown_event.is_set():
            raise RuntimeError("线程池已关闭，无法调整大小")
        
        if new_max_workers <= 0:
            raise ValueError("线程数必须大于0")
        
        with self._lock:
            old_max_workers = self._max_workers
            
            if new_max_workers < old_max_workers:
                # 减少线程数时，需要等待活跃任务完成
                logger.warning(f"强制减少线程数从 {old_max_workers} 到 {new_max_workers}，"
                             f"当前有 {self._active_tasks} 个活跃任务")
                
                # 设置调整标志，阻止新任务提交
                self._resizing = True
                self._target_workers = new_max_workers
                
                # 等待活跃任务数减少到新线程数以下
                while self._active_tasks >= new_max_workers:
                    logger.debug(f"等待活跃任务数减少，当前: {self._active_tasks}, 目标: {new_max_workers}")
                    time.sleep(1)
                
                # 清除调整标志
                self._resizing = False
                self._target_workers = None
            
            # 更新线程池大小
            self._max_workers = new_max_workers
            
            if new_max_workers > old_max_workers:
                # 增加线程数
                additional_threads = new_max_workers - old_max_workers
                for _ in range(additional_threads):
                    self._sema.release()
            else:
                # 减少线程数，需要重新创建信号量
                # 先释放当前信号量
                for _ in range(self._sema._value):
                    self._sema.release()
                # 重新创建信号量
                self._sema = Semaphore(new_max_workers)
            
            logger.info(f"线程池 {self._name} 线程数强制调整到 {new_max_workers}")
            return True

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
