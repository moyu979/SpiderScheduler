import unittest
import os
import tempfile
import shutil
import logging
from unittest.mock import patch, MagicMock, call
from datetime import datetime
import sys
import inspect

# 获取项目根目录（tests的父目录）
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
src_path = os.path.join(project_root, 'src')

# 添加src目录到Python路径
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from utils.logger import SpiderLogger, logger, debug, info, warning, error, critical, exception, log, setLevel


class TestSpiderLogger(unittest.TestCase):
    """测试SpiderLogger类的所有功能"""
    
    def setUp(self):
        """测试前的设置"""
        # 创建临时目录用于测试
        self.test_dir = tempfile.mkdtemp()
        self.original_log_path = None
        
        # 备份原始配置
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            self.logger = SpiderLogger('TestLogger')
    
    def tearDown(self):
        """测试后的清理"""
        # 清理临时目录
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        
        # 重置全局状态
        import utils.logger
        utils.logger._log_cache.clear()
        utils.logger._logger_initialized = False
    
    def test_init(self):
        """测试SpiderLogger初始化"""
        self.assertEqual(self.logger.name, 'TestLogger')
        self.assertIsNotNone(self.logger.logger)
        self.assertIsInstance(self.logger.logger, logging.Logger)
    
    def test_setup_logger_creates_directory(self):
        """测试日志目录创建"""
        self.assertTrue(os.path.exists(self.test_dir))
    
    def test_setup_logger_creates_handlers(self):
        """测试处理器创建"""
        handlers = self.logger.logger.handlers
        self.assertEqual(len(handlers), 2)  # 文件处理器和控制台处理器
        
        # 检查文件处理器
        file_handlers = [h for h in handlers if isinstance(h, logging.FileHandler)]
        self.assertEqual(len(file_handlers), 1)
        
        # 检查控制台处理器
        console_handlers = [h for h in handlers if isinstance(h, logging.StreamHandler)]
        self.assertEqual(len(console_handlers), 1)
    
    def test_setup_logger_sets_levels(self):
        """测试日志级别设置"""
        self.assertEqual(self.logger.logger.level, logging.DEBUG)
        
        # 检查文件处理器级别
        file_handler = next(h for h in self.logger.logger.handlers if isinstance(h, logging.FileHandler))
        self.assertEqual(file_handler.level, logging.DEBUG)
        
        # 检查控制台处理器级别
        console_handler = next(h for h in self.logger.logger.handlers if isinstance(h, logging.StreamHandler))
        self.assertEqual(console_handler.level, logging.INFO)
    
    def test_log_file_naming(self):
        """测试日志文件命名（按月命名）"""
        current_month = datetime.now().strftime('%Y_%m')
        expected_filename = f'{current_month}.log'
        
        file_handler = next(h for h in self.logger.logger.handlers if isinstance(h, logging.FileHandler))
        self.assertIn(expected_filename, file_handler.baseFilename)
    
    def test_logging_methods(self):
        """测试所有日志记录方法"""
        test_message = "测试日志消息"
        
        # 测试各种日志级别
        with patch.object(self.logger.logger, 'handle') as mock_handle:
            self.logger.debug(test_message)
            self.logger.info(test_message)
            self.logger.warning(test_message)
            self.logger.error(test_message)
            self.logger.critical(test_message)
            
            # 验证调用次数
            self.assertEqual(mock_handle.call_count, 5)
    
    def test_log_with_class_detection(self):
        """测试类名自动检测"""
        with patch.object(self.logger.logger, 'handle') as mock_handle:
            self.logger.info("测试消息")
            
            # 验证LogRecord被创建且包含classname
            mock_handle.assert_called_once()
            call_args = mock_handle.call_args[0][0]
            self.assertIsInstance(call_args, logging.LogRecord)
            self.assertEqual(call_args.name, 'TestLogger')
    
    def test_log_with_explicit_classname(self):
        """测试显式指定类名"""
        with patch.object(self.logger.logger, 'handle') as mock_handle:
            self.logger._log_with_class(logging.INFO, "测试消息", "TestClass")
            
            mock_handle.assert_called_once()
            call_args = mock_handle.call_args[0][0]
            self.assertEqual(call_args.classname, "TestClass")
    
    def test_exception_logging(self):
        """测试异常日志记录"""
        with patch.object(self.logger.logger, 'handle') as mock_handle:
            self.logger.exception("测试异常")
            
            mock_handle.assert_called_once()
            call_args = mock_handle.call_args[0][0]
            self.assertEqual(call_args.level, logging.ERROR)
            self.assertTrue(call_args.exc_info)
    
    def test_set_level(self):
        """测试设置日志级别"""
        new_level = logging.WARNING
        self.logger.setLevel(new_level)
        self.assertEqual(self.logger.logger.level, new_level)
    
    def test_get_logger(self):
        """测试获取底层Logger对象"""
        underlying_logger = self.logger.getLogger()
        self.assertIsInstance(underlying_logger, logging.Logger)
        self.assertEqual(underlying_logger.name, 'TestLogger')
    
    def test_month_change_detection(self):
        """测试月份变化检测"""
        # 模拟月份变化
        with patch('utils.logger.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = '2024_01'
            
            # 重新设置日志记录器
            self.logger._setup_logger()
            
            # 验证新的日志文件路径
            file_handler = next(h for h in self.logger.logger.handlers if isinstance(h, logging.FileHandler))
            self.assertIn('2024_01.log', file_handler.baseFilename)
    
    def test_cache_logging_when_not_initialized(self):
        """测试日志系统未初始化时的缓存功能"""
        # 重置全局状态
        import utils.logger
        utils.logger._logger_initialized = False
        utils.logger._log_cache.clear()
        
        # 创建新的logger实例
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            test_logger = SpiderLogger('CacheTest')
            
            # 记录一些日志（应该被缓存）
            test_logger.info("缓存的消息1")
            test_logger.error("缓存的消息2")
            
            # 验证日志被缓存
            self.assertEqual(len(utils.logger._log_cache), 2)
            self.assertEqual(utils.logger._log_cache[0]['message'], "缓存的消息1")
            self.assertEqual(utils.logger._log_cache[1]['message'], "缓存的消息2")
    
    def test_flush_cache(self):
        """测试缓存刷新功能"""
        # 重置全局状态
        import utils.logger
        utils.logger._logger_initialized = False
        utils.logger._log_cache.clear()
        
        # 添加一些缓存日志
        utils.logger._log_cache.extend([
            {'level': 'INFO', 'message': '缓存消息1', 'classname': 'TestClass'},
            {'level': 'ERROR', 'message': '缓存消息2', 'classname': 'TestClass'}
        ])
        
        # 创建logger实例（应该刷新缓存）
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            with patch.object(SpiderLogger, '_log_with_class') as mock_log:
                test_logger = SpiderLogger('FlushTest')
                
                # 验证缓存被刷新
                self.assertEqual(len(utils.logger._log_cache), 0)
                self.assertEqual(mock_log.call_count, 2)


class TestModuleLevelFunctions(unittest.TestCase):
    """测试模块级便捷函数"""
    
    def setUp(self):
        """测试前的设置"""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """测试后的清理"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        
        # 重置全局状态
        import utils.logger
        utils.logger._log_cache.clear()
        utils.logger._logger_initialized = False
    
    def test_module_functions(self):
        """测试所有模块级函数"""
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            
            # 重新初始化logger
            import utils.logger
            utils.logger._logger_initialized = False
            utils.logger._log_cache.clear()
            
            # 测试所有模块级函数
            with patch.object(SpiderLogger, '_log_with_class') as mock_log:
                debug("调试消息")
                info("信息消息")
                warning("警告消息")
                error("错误消息")
                critical("严重错误消息")
                exception("异常消息")
                log(logging.INFO, "通用日志消息")
                
                # 验证调用次数
                self.assertEqual(mock_log.call_count, 7)
    
    def test_set_level_module_function(self):
        """测试模块级setLevel函数"""
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            
            # 重新初始化logger
            import utils.logger
            utils.logger._logger_initialized = False
            utils.logger._log_cache.clear()
            
            with patch.object(SpiderLogger, 'setLevel') as mock_set_level:
                setLevel(logging.WARNING)
                mock_set_level.assert_called_once_with(logging.WARNING)


class TestLoggerIntegration(unittest.TestCase):
    """测试日志系统的集成功能"""
    
    def setUp(self):
        """测试前的设置"""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """测试后的清理"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        
        # 重置全局状态
        import utils.logger
        utils.logger._log_cache.clear()
        utils.logger._logger_initialized = False
    
    def test_actual_file_logging(self):
        """测试实际的文件日志记录"""
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            
            # 重新初始化logger
            import utils.logger
            utils.logger._logger_initialized = False
            utils.logger._log_cache.clear()
            
            # 创建logger实例
            test_logger = SpiderLogger('FileTest')
            
            # 记录一些日志
            test_message = "测试文件日志记录"
            test_logger.info(test_message)
            
            # 验证日志文件被创建
            current_month = datetime.now().strftime('%Y_%m')
            log_file = os.path.join(self.test_dir, f'{current_month}.log')
            self.assertTrue(os.path.exists(log_file))
            
            # 验证日志内容
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.assertIn(test_message, content)
                self.assertIn('INFO', content)
                self.assertIn('FileTest', content)
    
    def test_log_format(self):
        """测试日志格式"""
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            
            # 重新初始化logger
            import utils.logger
            utils.logger._logger_initialized = False
            utils.logger._log_cache.clear()
            
            # 创建logger实例
            test_logger = SpiderLogger('FormatTest')
            
            # 记录日志
            test_logger.info("格式测试消息")
            
            # 验证日志格式
            current_month = datetime.now().strftime('%Y_%m')
            log_file = os.path.join(self.test_dir, f'{current_month}.log')
            
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 验证格式：时间 - 名称 - 级别 - [类名] - 消息
                lines = content.strip().split('\n')
                self.assertTrue(len(lines) > 0)
                
                log_line = lines[0]
                parts = log_line.split(' - ')
                self.assertEqual(len(parts), 5)
                self.assertIn('FormatTest', parts[1])  # 名称
                self.assertIn('INFO', parts[2])        # 级别
                self.assertIn('FormatTest', parts[3])  # 类名
                self.assertIn('格式测试消息', parts[4])  # 消息


class TestLoggerErrorHandling(unittest.TestCase):
    """测试日志系统的错误处理"""
    
    def setUp(self):
        """测试前的设置"""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """测试后的清理"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        
        # 重置全局状态
        import utils.logger
        utils.logger._log_cache.clear()
        utils.logger._logger_initialized = False
    
    def test_setup_logger_failure(self):
        """测试日志设置失败时的处理"""
        # 模拟get_path抛出异常
        with patch('utils.logger.get_path', side_effect=Exception("配置错误")):
            with patch('utils.logger._log_cache') as mock_cache:
                mock_cache.append = MagicMock()
                
                # 创建logger实例（应该失败并记录到缓存）
                test_logger = SpiderLogger('ErrorTest')
                
                # 验证错误被记录到缓存
                mock_cache.append.assert_called_once()
                call_args = mock_cache.append.call_args[0][0]
                self.assertEqual(call_args['level'], 'ERROR')
                self.assertIn('日志系统初始化失败', call_args['message'])
    
    def test_get_calling_class_failure(self):
        """测试获取调用类名失败时的处理"""
        with patch('utils.logger.get_path') as mock_get_path:
            mock_get_path.return_value = self.test_dir
            
            # 重新初始化logger
            import utils.logger
            utils.logger._logger_initialized = False
            utils.logger._log_cache.clear()
            
            # 模拟inspect.currentframe失败
            with patch('inspect.currentframe', side_effect=Exception("inspect错误")):
                test_logger = SpiderLogger('InspectTest')
                
                # 记录日志（应该使用默认类名）
                with patch.object(test_logger.logger, 'handle') as mock_handle:
                    test_logger.info("测试消息")
                    
                    mock_handle.assert_called_once()
                    call_args = mock_handle.call_args[0][0]
                    self.assertEqual(call_args.classname, 'Unknown')


if __name__ == '__main__':
    unittest.main()
