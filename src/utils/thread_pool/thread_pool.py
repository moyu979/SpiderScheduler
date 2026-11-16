"""阻塞式线程池执行器。

在标准 ThreadPoolExecutor 之上叠加两层能力：
- 背压：submit 在信号量上阻塞，池满时提交方等待，而不是无界排队；
- 可观测：内置活跃/完成/失败计数与 wait_for_completion 轮询等待。

全部内部状态经 _lock 保护；信号量与计数在提交失败、任务被取消等路径上
都会回滚回收，保证 wait_for_completion 不会因计数泄漏而永久等待。
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Semaphore

from src.utils.logging.logger import SpiderLogger as logger


class ThreadPool(ThreadPoolExecutor):
    """阻塞式线程池执行器：池满时让提交方等待，形成天然背压。

    与标准 ThreadPoolExecutor 的差异：
    - submit 在信号量上阻塞，直到有工作线程空闲（而不是无界排队）；
    - 内置活跃/完成/失败计数与 wait_for_completion 轮询等待；
    - 全部内部状态经 _lock 保护。

    Attributes:
        _sema: 背压信号量，初始值 = max_workers，任务结束/提交失败/被取消时归还。
        _name: 池名称，仅用于日志展示。
        _lock: 保护计数结构的可重入入口（普通 Lock）。
        _active_tasks: 已提交且尚未收尾的任务数（含排队中）。
        _completed_tasks: 已收尾任务数（成功与失败都计）。
        _failed_tasks: 执行中抛异常的任务数。
        _shutdown_event: 关闭标志；置位后 submit 直接拒绝。
        _max_workers: 记录构造时的最大线程数（标准库属性为私有，此处留档）。
    """

    def __init__(self, max_workers, name="BlockingThreadPool"):
        """初始化线程池。

        Args:
            max_workers: 最大工作线程数，同时是背压信号量的容量。
            name: 池名称，仅用于日志展示。

        Raises:
            ValueError: max_workers 非正数（由标准库校验）。
        """
        super().__init__(max_workers=max_workers)
        self._sema = Semaphore(max_workers)
        self._name = name
        self._lock = Lock()
        self._active_tasks = 0
        self._completed_tasks = 0
        self._failed_tasks = 0
        self._shutdown_event = Event()
        self._max_workers = max_workers

        logger.info(f"创建线程池: {name}, 最大线程数: {max_workers}")

    def submit(self, fn, *args, **kwargs):
        """提交任务；池满时阻塞调用方直到有线程空闲（背压）。

        任务被 wrap_fn 包装：统计活跃/完成/失败计数并记录异常日志。
        已占用的信号量与活跃计数在两条异常路径上都会回收：
        - super().submit 本身抛异常（典型：阻塞在 acquire 期间发生了 shutdown）；
        - 任务被 shutdown(cancel_futures=True) 取消，wrap_fn 永不执行。

        Args:
            fn: 任务函数。
            *args: 透传给 fn 的位置参数。
            **kwargs: 透传给 fn 的关键字参数。

        Returns:
            Future: 任务 future；异常也在其中（wrap_fn 已记录日志）。

        Raises:
            RuntimeError: 线程池已关闭。
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
            """包装任务：收尾时回滚活跃计数、累加完成/失败计数并归还信号量。"""
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

        try:
            future = super().submit(wrap_fn, *args, **kwargs)
        except BaseException:
            # 提交失败（典型：阻塞在 acquire 期间发生了 shutdown）必须回滚
            # 已占用的信号量与活跃计数，否则 wait_for_completion 会永久等待
            with self._lock:
                self._active_tasks -= 1
            self._sema.release()
            raise

        # shutdown(cancel_futures=True) 取消的排队任务不会执行 wrap_fn，
        # 由回调补做回收；正常执行的任务 cancelled() 为 False，不会重复回收
        def _reclaim_cancelled(fut):
            """future 回调：任务被取消时补做计数回滚与信号量归还。"""
            if fut.cancelled():
                with self._lock:
                    self._active_tasks -= 1
                self._sema.release()

        future.add_done_callback(_reclaim_cancelled)
        return future

    def get_stats(self):
        """获取线程池统计信息快照。

        Returns:
            dict: 含 name / max_workers / active_tasks / completed_tasks /
            failed_tasks / available_threads / is_shutdown 七个键。
        """
        with self._lock:
            return {
                'name': self._name,
                'max_workers': self._max_workers,
                'active_tasks': self._active_tasks,
                'completed_tasks': self._completed_tasks,
                'failed_tasks': self._failed_tasks,
                'available_threads': self._sema._value,
                'is_shutdown': self._shutdown_event.is_set(),
            }

    def log_stats(self):
        """把当前统计信息以 INFO 级别写入日志。"""
        stats = self.get_stats()
        logger.info(f"线程池统计 - {stats['name']}: "
                    f"活跃任务={stats['active_tasks']}, "
                    f"已完成={stats['completed_tasks']}, "
                    f"失败={stats['failed_tasks']}, "
                    f"可用线程={stats['available_threads']}")

    def shutdown(self, wait=True, *, cancel_futures=False):
        """关闭线程池：置位关闭标志、记录最终统计后交由标准库收尾。

        Args:
            wait: 是否阻塞等待已提交任务全部收尾。
            cancel_futures: 是否取消尚未开始执行的排队任务（被取消的任务
                由 submit 里的 done-callback 补做计数回收）。
        """
        logger.info(f"开始关闭线程池: {self._name}")
        self._shutdown_event.set()

        # 记录最终统计信息
        self.log_stats()

        super().shutdown(wait=wait, cancel_futures=cancel_futures)
        logger.info(f"线程池已关闭: {self._name}")

    def wait_for_completion(self, timeout=None):
        """轮询等待所有已提交任务收尾（活跃计数归零）。

        Args:
            timeout: 最长等待秒数；None 表示无限等待。调用方若在 shutdown
                竞态下提交过任务，计数已由 submit 回滚，不会在此永久挂起。

        Returns:
            bool: 所有任务已完成返回 True；超时返回 False。
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
