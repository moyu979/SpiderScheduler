import signal
import time
import sys
import os

#from src.core.backendManager import BackendManager
#from src.initer.init_backend import init_backend

from src.core.initialization import init
from src.server.rest_api import rest_api

def signal_handler(sig, frame):
    """处理 Ctrl+C 信号"""
    print('\n收到中断信号，正在安全退出...')
    
    # 停止 REST API 服务
    if rest_api:
        try:
            rest_api.stop()
        except Exception as e:
            print(f"停止 REST API 服务时出错: {e}")
    
    # 退出程序
    sys.exit(0)

def main():
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 初始化后端
    
    #backendManager = BackendManager()
    init()
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