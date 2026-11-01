"""SpiderScheduler 入口。

职责只有三件事：
1. 注册信号处理（SIGINT/SIGTERM 均走优雅退出：停调度服务 → 停 API → 停配置守护线程）；
2. 解析启动参数（--basepath 工作目录、--repl 命令行模式）并写入全局配置；
3. 调用 src/core/initialization.init() 完成全部初始化，然后阻塞等待退出信号。

所有真正的初始化与业务逻辑都在 src/ 内，本文件不承载业务。
"""

import argparse
import os
import signal
import sys
import time

from src.config.config import ConfigManager, config_manager

from src.core.initialization import init
from src.server.rest_api import rest_api
from src.cli.repl import run_repl
from src.service.updater import updater
from src.service.downloader import downloader
from src.utils.logging.logger import SpiderLogger as logger


def signal_handler(sig, frame):
    """处理退出信号（SIGINT/SIGTERM）：按依赖顺序优雅停止全部服务。

    顺序：调度服务（等线程池收尾）→ REST API → 配置热重载守护线程。
    任一环节失败只记录并继续，保证退出流程完整。
    """
    logger.info("收到中断信号，正在安全退出")
    print('\n收到中断信号，正在安全退出...')

    # 停止调度服务（等待进行中的任务收尾）
    for service in (downloader, updater):
        try:
            service.stop()
        except Exception as e:
            print(f"停止 {type(service).__name__} 时出错: {e}")

    # 停止 REST API 服务
    if rest_api:
        try:
            rest_api.stop()
        except Exception as e:
            print(f"停止 REST API 服务时出错: {e}")

    # 停止配置热重载守护线程
    try:
        ConfigManager.stop_daemon()
    except Exception as e:
        print(f"停止配置守护线程时出错: {e}")

    # 退出程序
    sys.exit(0)

def main(base_path: str = None):
    """默认启动模式：完成初始化后阻塞等待退出信号。

    Args:
        base_path: 工作目录覆盖（None 时使用 ./docker 或 BASEPATH 环境变量）。
    """
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 只在 main 里配置一次：BASEPATH / --basepath -> 写入 config_manager.base_path
    if base_path:
        config_manager.base_path = base_path

    init()
    logger.info("程序已启动（BASEPATH=%s，API=%s:%s）",
                config_manager.base_path,
                ConfigManager.get('network', 'rest_api_host'),
                ConfigManager.get('network', 'rest_api_port'))
    
    try:
        # 无限循环，直到收到中断信号（默认模式）
        while True:
            time.sleep(1)  # Windows 下替代 signal.pause()
    except KeyboardInterrupt:
        print('\n程序被用户中断')
    finally:
        print("程序已安全退出")

def main_with_repl(base_path: str | None = None) -> None:
    """REPL 启动模式：初始化后进入内置命令行（供交互式管理）。

    Args:
        base_path: 工作目录覆盖（None 时使用 ./docker 或 BASEPATH 环境变量）。
    """
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
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