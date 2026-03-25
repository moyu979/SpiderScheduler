import signal
import time
import sys
import os
import argparse

#from src.core.backendManager import BackendManager
#from src.initer.init_backend import init_backend
from src.config.config import config_manager

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

def main(base_path: str=None):
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)

    # 只在 main 里配置一次：BASEPATH / --basepath -> 写入 config_manager.base_path
    if base_path:
        config_manager.base_path = base_path

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
    parser = argparse.ArgumentParser(description="SpiderScheduler 启动参数")
    parser.add_argument(
        "--basepath",
        dest="basepath",
        default=None,
        help="工作目录（默认读取环境变量 BASEPATH；未提供则使用代码默认值）",
    )
    args = parser.parse_args()

    # 覆盖优先级：环境变量 BASEPATH < 命令行 --basepath
    basepath = os.environ.get("BASEPATH")
    if args.basepath:
        basepath = args.basepath

    main(basepath)