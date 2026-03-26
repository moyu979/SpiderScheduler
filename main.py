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
from src.cli.repl import run_repl
from src.utils.logging.logger import SpiderLogger as logger

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
        # 无限循环，直到收到中断信号（默认模式）
        while True:
            time.sleep(1)  # Windows 下替代 signal.pause()
    except KeyboardInterrupt:
        print('\n程序被用户中断')
    finally:
        print("程序已安全退出")

def main_with_repl(base_path: str | None = None) -> None:
    # 复用 main 的启动流程，但把“阻塞 loop”替换成 REPL
    signal.signal(signal.SIGINT, signal_handler)
    if base_path:
        config_manager.base_path = base_path

    init()
    # REPL 模式下，仅在运行时把“控制台输出”的日志等级抬高到 WARNING（不写回配置文件）。
    try:
        if logger.getLogger() is not None:
            import logging as _logging

            for handler in logger.getLogger().handlers:
                if isinstance(handler, _logging.StreamHandler):
                    handler.setLevel(_logging.WARNING)
    except Exception:
        # REPL 不应因为调整日志等级失败而启动失败
        pass
    print("程序已启动，输入 help 查看命令，Ctrl+C 退出...")
    run_repl()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SpiderScheduler 启动参数")
    parser.add_argument(
        "--basepath",
        dest="basepath",
        default=None,
        help="工作目录（默认读取环境变量 BASEPATH；未提供则使用代码默认值）",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="启动后进入内置命令行（cmd REPL）",
    )
    args = parser.parse_args()

    # 覆盖优先级：环境变量 BASEPATH < 命令行 --basepath
    basepath = os.environ.get("BASEPATH")
    if args.basepath:
        basepath = args.basepath

    if args.repl:
        main_with_repl(basepath)
    else:
        main(basepath)