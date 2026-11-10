"""统一日志门面。

控制台 INFO + 文件 DEBUG（按月轮转）的组合输出：
- 类方法式调用（logger.info(...)），内部经 _log_with_class 自动归属调用方类名；
- 初始化前的日志进入缓存，init_log() 后统一重放，避免丢早期日志；
- 五个级别方法均支持标准 %-args 惰性格式化；
- 全部实际写日志的动作经 _lock 串行（含跨月切换 handler），多线程安全。
"""

import inspect
import logging
import os
import threading
from datetime import datetime

from src.config.paths import log_path as _global_log_path


class SpiderLogger:
    """统一日志门面：控制台 INFO + 文件 DEBUG（按月轮转）。

    类方法式调用（logger.info(...)），内部经 _log_with_class 自动归属调用方
    类名；初始化前的日志进入缓存，init_log() 后统一重放。五个级别方法均
    支持标准 %-args 惰性格式化。

    Attributes:
        name: 底层 logging.Logger 的名称。
        _logger: 底层 logging.Logger 实例，init_log() 后非 None。
        _log_cache: 初始化前的日志缓存，每项为 {level, message, classname}。
        _logger_initialized: 是否已完成初始化。
        _lock: 串行化缓存读写与实际写日志动作（含跨月重置 handler）；
               用 RLock——_log_with_class 持锁内经 _check_month_change 重入
               _setup_logger，其失败分支会再次加锁，非重入锁会自死锁。
    """

    name = 'SpiderScheduler'
    _logger = None
    _log_cache = []
    _logger_initialized = False
    _lock = threading.RLock()

    @classmethod
    def init_log(cls):
        """初始化日志系统并重放初始化前缓存的日志。

        读取 logging 配置段（console_log_level / file_log_level），按当前月份
        建立文件 handler；应在配置系统就绪后调用（initialization.init 第 3 步）。
        """
        cls._setup_logger()
        cls._flush_cache()

    @classmethod
    def _setup_logger(cls):
        """按当前月份重建 handler（控制台 + 文件），读取 logging 配置段。

        任何失败只缓存一条 ERROR 日志，不抛出——日志系统不应拖垮启动。
        """
        try:
            # 延迟导入，避免与 src.config.config 形成循环依赖
            from src.config.config import config_manager

            logging_conf = config_manager.config_dict.get("system", {}) or {}
            console_level_name = str(logging_conf.get("console_log_level", "INFO")).upper()
            file_level_name = str(logging_conf.get("file_log_level", "DEBUG")).upper()

            console_level = logging._nameToLevel.get(console_level_name, logging.INFO)
            file_level = logging._nameToLevel.get(file_level_name, logging.DEBUG)

            log_path = _global_log_path()
            if not os.path.exists(log_path):
                os.makedirs(log_path, exist_ok=True)
            cls._logger = logging.getLogger(cls.name)
            cls._logger.setLevel(logging.DEBUG)
            cls._logger.propagate = False  # 禁用传播，避免重复输出
            # 先关闭旧 handler 再重建（跨月轮转）：FileHandler 不 close 会泄漏文件句柄
            for old_handler in cls._logger.handlers[:]:
                old_handler.close()
            cls._logger.handlers.clear()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(classname)s] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            current_month = datetime.now().strftime('%Y_%m')
            log_file = os.path.join(log_path, f'{current_month}.log')
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(file_level)
            file_handler.setFormatter(formatter)
            console_handler = logging.StreamHandler()
            console_handler.setLevel(console_level)
            console_handler.setFormatter(formatter)
            cls._logger.addHandler(file_handler)
            cls._logger.addHandler(console_handler)
            cls._logger_initialized = True
        except Exception as e:
            with cls._lock:
                cls._log_cache.append({
                    'level': 'ERROR',
                    'message': f'日志系统初始化失败: {e}',
                    'classname': 'SpiderLogger'
                })

    @classmethod
    def _flush_cache(cls):
        """把初始化前缓存的日志按原级别重放（消息加 "(cached)" 前缀）。"""
        if not cls._logger_initialized:
            return
        with cls._lock:
            if not cls._log_cache:
                return
            pending = cls._log_cache[:]
            cls._log_cache.clear()
        for cached_log in pending:
            level = cached_log.get('level', logging.INFO)
            if isinstance(level, str):
                level = logging._nameToLevel.get(level.upper(), logging.INFO)
            cls._log_with_class(level, "(cached)" + cached_log['message'], cached_log['classname'])

    @classmethod
    def _cache_log(cls, level, message, classname='Unknown'):
        """把未初始化期间的日志消息缓存起来，待 init_log 后重放。

        Args:
            level: 日志级别（int 或级别名字符串）。
            message: 日志消息。
            classname: 归属类名，缺省 'Unknown'。
        """
        normalized_level = level
        if isinstance(normalized_level, str):
            normalized_level = logging._nameToLevel.get(normalized_level.upper(), logging.INFO)
        with cls._lock:
            cls._log_cache.append({
                'level': normalized_level,
                'message': message,
                'classname': classname
            })

    @staticmethod
    def _get_calling_class():
        """获取调用日志的类名（跳过 SpiderLogger 门面自身的帧）。

        回溯调用栈，跳过门面自身的 classmethod 帧（其局部 cls 是
        SpiderLogger），按序归因：实例方法→类名，类方法→类名，普通函数→
        模块名。__main__ 与不可判定场景返回 'Unknown'。

        Returns:
            str: 归属类名或模块名。
        """
        try:
            frame = inspect.currentframe()
            while frame:
                frame = frame.f_back
                if frame is None:
                    break
                if 'self' in frame.f_locals and frame.f_locals['self'] is not None:
                    return frame.f_locals['self'].__class__.__name__
                elif 'cls' in frame.f_locals:
                    # 门面自身的帧（info/_log_with_class 等 classmethod）跳过，
                    # 继续向外找真实调用方；用户的 classmethod 正常返回
                    if frame.f_locals['cls'] is SpiderLogger:
                        continue
                    return frame.f_locals['cls'].__name__
                else:
                    module_name = frame.f_globals.get('__name__', '')
                    if module_name and module_name != '__main__':
                        return module_name.split('.')[-1]
            return 'Unknown'
        except Exception:
            return 'Unknown'

    @classmethod
    def _check_month_change(cls):
        """检查文件 handler 是否落后于当前月份，落后则重建 handler 切换日志文件。

        在每次写日志时调用；比较当前月份与现有 FileHandler 的 baseFilename，
        不一致即整体重建（_setup_logger）。异常静默，不影响本次写日志。
        """
        if not cls._logger_initialized:
            return
        current_month = datetime.now().strftime('%Y_%m')
        try:
            log_path = _global_log_path()
            expected_log_file = os.path.join(log_path, f'{current_month}.log')
            for handler in cls._logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    if handler.baseFilename != expected_log_file:
                        cls._setup_logger()
                        break
        except Exception:
            pass

    @classmethod
    def _log_with_class(cls, level, message, classname=None):
        """实际写日志的统一入口：跨月检查 + 归属类名 + 构造 LogRecord。

        Args:
            level: 数字日志级别。
            message: 已格式化的日志消息。
            classname: 归属类名；None 时经 _get_calling_class 自动归因。
        """
        if not cls._logger_initialized:
            if classname is None:
                classname = cls._get_calling_class()
            cls._cache_log(level, message, classname)
            return
        # 序列化所有"实际写日志"的动作（包含跨月重置 handler）
        with cls._lock:
            cls._check_month_change()
            if classname is None:
                classname = cls._get_calling_class()
            record = logging.LogRecord(
                name=cls._logger.name,
                level=level,
                pathname='',
                lineno=0,
                msg=message,
                args=(),
                exc_info=None
            )
            record.classname = classname
            cls._logger.handle(record)

    @classmethod
    def debug(cls, message, *args):
        """记录 DEBUG 级别日志（支持 %-args 惰性格式化，格式化失败保留原消息）。

        Args:
            message: 日志消息或 %-格式串。
            *args: 格式化参数。
        """
        if args:
            try:
                message = str(message) % args
            except (TypeError, ValueError):
                pass  # 格式化失败保留原消息，避免吞日志
        cls._log_with_class(logging.DEBUG, message)

    @classmethod
    def info(cls, message, *args):
        """记录 INFO 级别日志（支持 %-args 惰性格式化，格式化失败保留原消息）。

        Args:
            message: 日志消息或 %-格式串。
            *args: 格式化参数。
        """
        if args:
            try:
                message = str(message) % args
            except (TypeError, ValueError):
                pass  # 格式化失败保留原消息，避免吞日志
        cls._log_with_class(logging.INFO, message)

    @classmethod
    def warning(cls, message, *args):
        """记录 WARNING 级别日志（支持 %-args 惰性格式化，格式化失败保留原消息）。

        Args:
            message: 日志消息或 %-格式串。
            *args: 格式化参数。
        """
        if args:
            try:
                message = str(message) % args
            except (TypeError, ValueError):
                pass  # 格式化失败保留原消息，避免吞日志
        cls._log_with_class(logging.WARNING, message)

    @classmethod
    def error(cls, message, *args):
        """记录 ERROR 级别日志（支持 %-args 惰性格式化，格式化失败保留原消息）。

        Args:
            message: 日志消息或 %-格式串。
            *args: 格式化参数。
        """
        if args:
            try:
                message = str(message) % args
            except (TypeError, ValueError):
                pass  # 格式化失败保留原消息，避免吞日志
        cls._log_with_class(logging.ERROR, message)

    @classmethod
    def critical(cls, message, *args):
        """记录 CRITICAL 级别日志（支持 %-args 惰性格式化，格式化失败保留原消息）。

        Args:
            message: 日志消息或 %-格式串。
            *args: 格式化参数。
        """
        if args:
            try:
                message = str(message) % args
            except (TypeError, ValueError):
                pass  # 格式化失败保留原消息，避免吞日志
        cls._log_with_class(logging.CRITICAL, message)

    @classmethod
    def exception(cls, message):
        """以 ERROR 级别记录日志并附加当前异常栈（须在 except 块内调用）。

        Args:
            message: 日志消息。
        """
        if not cls._logger_initialized:
            classname = cls._get_calling_class()
            cls._cache_log('ERROR', message, classname)
            return
        # 序列化异常日志的写入（包含跨月重置 handler）
        with cls._lock:
            cls._check_month_change()
            classname = cls._get_calling_class()
            record = logging.LogRecord(
                name=cls._logger.name,
                level=logging.ERROR,
                pathname='',
                lineno=0,
                msg=message,
                args=(),
                exc_info=True
            )
            record.classname = classname
            cls._logger.handle(record)

    @classmethod
    def log(cls, level, message):
        """以任意数字级别记录日志（等价 logging.Logger.log）。

        Args:
            level: 数字日志级别。
            message: 日志消息。
        """
        cls._log_with_class(level, message)

    @classmethod
    def setLevel(cls, level):
        """设置底层 logger 的级别（等价 logging.Logger.setLevel）。

        Args:
            level: 数字日志级别；未初始化时为空操作。
        """
        if cls._logger_initialized and cls._logger:
            cls._logger.setLevel(level)

    @classmethod
    def getLogger(cls):
        """返回底层 logging.Logger 实例（供直接操作 handler 等高级用法）。

        Returns:
            logging.Logger | None: 未初始化时为 None。
        """
        return cls._logger
