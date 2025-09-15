import os
import logging
import logging.handlers
import inspect
from datetime import datetime
from .config import get_path

# 全局日志缓存
_log_cache = []
_logger_initialized = False

class SpiderLogger:
    """SpiderScheduler 日志管理器"""
    
    def __init__(self, name='SpiderScheduler'):
        self.name = name
        self.logger = None
        self._setup_logger()
        self._flush_cache()
    
    def _setup_logger(self):
        """设置日志记录器"""
        global _logger_initialized
        
        try:
            # 获取日志路径
            log_path = get_path('LOG_PATH')
            
            # 确保日志目录存在
            if not os.path.exists(log_path):
                os.makedirs(log_path, exist_ok=True)
            
            # 创建日志记录器
            self.logger = logging.getLogger(self.name)
            self.logger.setLevel(logging.DEBUG)
            
            # 清除已有的处理器
            self.logger.handlers.clear()
            
            # 创建格式化器
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(classname)s] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # 创建文件处理器（按月轮转）
            current_month = datetime.now().strftime('%Y_%m')
            log_file = os.path.join(log_path, f'{current_month}.log')
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            
            # 创建控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            
            # 添加处理器到日志记录器
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
            
            _logger_initialized = True
            
        except Exception as e:
            # 如果初始化失败，记录到缓存
            _log_cache.append({
                'level': 'ERROR',
                'message': f'日志系统初始化失败: {e}',
                'classname': 'SpiderLogger'
            })
    
    def _flush_cache(self):
        """刷新缓存中的日志"""
        global _log_cache, _logger_initialized
        
        if _logger_initialized and _log_cache:
            for cached_log in _log_cache:
                self._log_with_class(
                    getattr(logging, cached_log['level']),
                    cached_log['message'],
                    cached_log['classname']
                )
            _log_cache.clear()
    
    def _cache_log(self, level, message, classname='Unknown'):
        """缓存日志消息"""
        global _log_cache
        _log_cache.append({
            'level': level,
            'message': message,
            'classname': classname
        })
    
    def _get_calling_class(self):
        """获取调用日志的类名"""
        try:
            # 获取调用栈
            frame = inspect.currentframe()
            # 跳过当前方法、日志方法等，找到真正的调用者
            while frame:
                frame = frame.f_back
                if frame:
                    # 获取调用者的类信息
                    if 'self' in frame.f_locals:
                        # 这是一个类方法调用
                        class_name = frame.f_locals['self'].__class__.__name__
                        return class_name
                    elif 'cls' in frame.f_locals:
                        # 这是一个类方法调用
                        class_name = frame.f_locals['cls'].__name__
                        return class_name
                    else:
                        # 检查是否是模块级函数调用
                        module_name = frame.f_globals.get('__name__', '')
                        if module_name and module_name != '__main__':
                            return module_name.split('.')[-1]
            return 'Unknown'
        except Exception:
            return 'Unknown'
    
    def _check_month_change(self):
        """检查是否需要切换到新的月份日志文件"""
        if not _logger_initialized:
            return
            
        current_month = datetime.now().strftime('%Y_%m')
        try:
            log_path = get_path('LOG_PATH')
            expected_log_file = os.path.join(log_path, f'{current_month}.log')
            
            # 检查当前处理器是否指向正确的文件
            for handler in self.logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    if handler.baseFilename != expected_log_file:
                        # 月份已改变，重新设置日志记录器
                        self._setup_logger()
                        break
        except Exception:
            pass
    
    def _log_with_class(self, level, message, classname=None):
        """记录带类名的日志"""
        global _logger_initialized
        
        if not _logger_initialized:
            # 日志系统未初始化，缓存日志
            if classname is None:
                classname = self._get_calling_class()
            self._cache_log(level, message, classname)
            return
        
        self._check_month_change()
        if classname is None:
            classname = self._get_calling_class()
        
        # 创建自定义的LogRecord
        record = logging.LogRecord(
            name=self.logger.name,
            level=level,
            pathname='',
            lineno=0,
            msg=message,
            args=(),
            exc_info=None
        )
        record.classname = classname
        
        self.logger.handle(record)
    
    def debug(self, message):
        """记录调试信息"""
        self._log_with_class(logging.DEBUG, message)
    
    def info(self, message):
        """记录一般信息"""
        self._log_with_class(logging.INFO, message)
    
    def warning(self, message):
        """记录警告信息"""
        self._log_with_class(logging.WARNING, message)
    
    def error(self, message):
        """记录错误信息"""
        self._log_with_class(logging.ERROR, message)
    
    def critical(self, message):
        """记录严重错误信息"""
        self._log_with_class(logging.CRITICAL, message)
    
    def exception(self, message):
        """记录异常信息（包含堆栈跟踪）"""
        global _logger_initialized
        
        if not _logger_initialized:
            # 日志系统未初始化，缓存日志
            classname = self._get_calling_class()
            self._cache_log('ERROR', message, classname)
            return
        
        self._check_month_change()
        classname = self._get_calling_class()
        
        # 创建自定义的LogRecord
        record = logging.LogRecord(
            name=self.logger.name,
            level=logging.ERROR,
            pathname='',
            lineno=0,
            msg=message,
            args=(),
            exc_info=True
        )
        record.classname = classname
        
        self.logger.handle(record)
    
    def log(self, level, message):
        """通用日志记录方法"""
        self._log_with_class(level, message)
    
    def setLevel(self, level):
        """设置日志级别"""
        if _logger_initialized and self.logger:
            self.logger.setLevel(level)
    
    def getLogger(self):
        """获取底层的logging.Logger对象"""
        return self.logger

# 创建默认日志实例
logger = SpiderLogger()

# 提供便捷的模块级函数
def debug(message):
    """记录调试信息"""
    logger.debug(message)

def info(message):
    """记录一般信息"""
    logger.info(message)

def warning(message):
    """记录警告信息"""
    logger.warning(message)

def error(message):
    """记录错误信息"""
    logger.error(message)

def critical(message):
    """记录严重错误信息"""
    logger.critical(message)

def exception(message):
    """记录异常信息（包含堆栈跟踪）"""
    logger.exception(message)

def log(level, message):
    """通用日志记录方法"""
    logger.log(level, message)

def setLevel(level):
    """设置日志级别"""
    logger.setLevel(level)
