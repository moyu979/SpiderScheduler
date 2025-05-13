from concurrent.futures import ThreadPoolExecutor
from threading import Semaphore
import time

class BlockingThreadPoolExecutor(ThreadPoolExecutor):
    def __init__(self, max_workers):
        super().__init__(max_workers=max_workers)
        self._sema = Semaphore(max_workers)

    def submit(self, fn, *args, **kwargs):
        # 阻塞直到有一个线程空闲
        self._sema.acquire()

        def wrap_fn(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            finally:
                self._sema.release()

        return super().submit(wrap_fn, *args, **kwargs)
if __name__ == "__main__":
    # 示例用法
    def task(n):
        print(f"Task {n} started")
        time.sleep(2)
        print(f"Task {n} finished")

    executor = BlockingThreadPoolExecutor(max_workers=2)

    for i in range(5):
        print(f"Submitting task {i}")
        executor.submit(task, i)

    executor.shutdown()
