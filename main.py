import signal
import time
import sys

from src.core.backendManager import BackendManager
from src.initer.init_backend import init_backend

def signal_handler(sig, frame):
    """处理 Ctrl+C 信号"""
    print('\n收到中断信号，正在安全退出...')
    sys.exit(0)

def main():
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 初始化后端
    init_backend()
    backendManager = BackendManager()
    
    print("程序已启动，按 Ctrl+C 退出...")
    
    try:
        # 无限循环，直到收到中断信号
        while True:
            time.sleep(1)  # Windows 下替代 signal.pause()
    except KeyboardInterrupt:
        print('\n程序被用户中断')
    finally:
        print("程序已安全退出")

if __name__ == "__main__":
    main()