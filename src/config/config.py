from functools import cache
import os
import sys
import json
import threading
import time

from src.utils.logging.logger import logger
from src.config.globalVars import work_path
from src.config.globalVars import config_path
from utils.exceptions import GetUnknownKey

class ConfigManager:
    """配置管理器类"""
    
    # 全局配置字典
    config_dict = {}
    # 守护线程状态
    _daemon_thread = None
    _running = False
    _interval = 300
    
    @classmethod
    def init_config(cls, dict_name, key):
        """获取配置值"""
        ConfigManager.load_all_configs()

    @classmethod
    def load_all_configs(cls):
        """初始化配置函数 - 加载config_path中的所有JSON文件"""
        # 清空全局字典
        cls.config_dict.clear()
        
        # 遍历config_path中的所有JSON文件
        if os.path.exists(config_path):
            for filename in os.listdir(config_path):
                if filename.endswith('.json'):
                    # 去掉.json后缀作为key
                    config_name = filename[:-5]
                    config_file_path = os.path.join(config_path, filename)
                    
                    try:
                        with open(config_file_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                            cls.config_dict[config_name] = config_data
                            logger.info(f"加载配置文件: {config_file_path}")
                    except Exception as e:
                        logger.error(f"加载配置文件失败 {config_file_path}: {e}")
        else:
            logger.warning(f"配置目录不存在: {config_path}")
    
    @classmethod
    def start_daemon(cls, interval: int = 300):
        """启动守护线程，定期重载配置"""
        if cls._running:
            return
        cls._interval = interval
        cls._running = True
        cls._daemon_thread = threading.Thread(target=cls._daemon_loop, daemon=True)
        cls._daemon_thread.start()
        logger.info("配置守护线程已启动")
    
    @classmethod
    def stop_daemon(cls):
        """停止守护线程"""
        cls._running = False
        if cls._daemon_thread is not None:
            cls._daemon_thread.join(timeout=1)
            cls._daemon_thread = None
    
    @classmethod
    def _daemon_loop(cls):
        """守护线程循环"""
        while cls._running:
            time.sleep(cls._interval)
            logger.debug("守护线程执行一次配置重载")
            cls.load_all_configs()
    
    @classmethod
    def get(cls, dict_name, key):
        """获取配置值"""
        value=cls.config_dict.get(dict_name, {}).get(key,None)
        if value is None:
            logger.error(f"配置值不存在: {dict_name}, {key}")
            raise GetUnknownKey(f"配置值不存在: {dict_name}, {key}")
        return value
    @classmethod
    def set(cls, dict_name, key, value):
        """设置配置值"""
        cls.config_dict[dict_name][key] = value

    
    
"""

class ConfigDaemon:
    # 配置守护线程类
    
    def __init__(self, config_reader, config_dicts):
        self.config_reader = config_reader
        self.config_dicts = config_dicts
        self.daemon_thread = None
        self.running = False
    
    def start_daemon(self):
        # 启动守护线程
        if self.running:
            return
        
        self.running = True
        self.daemon_thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self.daemon_thread.start()
        
        logger.info("配置守护线程已启动")

    
    def stop_daemon(self):
        # 停止守护线程
        self.running = False
        if self.daemon_thread:
            self.daemon_thread.join(timeout=1)
    
    def _daemon_loop(self):
        # 守护线程循环
        while self.running:
            
            interval = self.config_dicts.get('global_conf', {}).get('conf_reload_interval', 300)
            time.sleep(interval)  # 定期执行
            logger.debug("守护线程启动一次")
            try:
                # 重新加载所有配置（包含 global_conf）
                self.config_reader.load_all_configs(self.config_dicts)
                logger.debug("守护线程重载配置完成")
            except Exception as e:
                logger.error(f"守护线程加载配置失败: {e}")
            


class ConfigManager:
    # 配置管理器类
    
    def __init__(self):
        self.config_dir = None
        self.reader = None
        self.writer = None
        self.daemon = None
        self.config_dicts = None  # 将在init_config_system中设置
    
    def init_config_system(self):
        # 初始化配置系统
        logger.info("开始初始化配置系统")
        
        # 设置配置字典引用
        self.config_dicts = {
            'path': path,
            'download_setting': download_setting,
            'update_setting': update_setting,
            'network': network,
            'global_conf': global_conf,
        }
        
        # 固定配置目录为 docker/confs（仅从文件加载，不创建默认值文件）
        self.config_dir = os.path.join(work_path, 'confs')
        
        # 创建配置读写器
        self.reader = ConfigReader(self.config_dir)
        self.writer = ConfigWriter(self.config_dir)
        
        # 仅加载配置文件（不创建默认值）
        self._load_configs()
        
        # 启动守护线程（global_conf 已纳入统一字典）
        self.daemon = ConfigDaemon(self.reader, self.config_dicts)
        self.daemon.start_daemon()
        
        logger.info("配置系统初始化完成")
    
    def _load_configs(self):
        # 仅加载配置文件（不创建默认值），若缺失返回 False
        logger.info(f"加载全部配置文件")
        self.reader.load_all_configs(self.config_dicts)
    
    def reload_config(self):
        # 手动重载配置
        logger.info("开始手动重载配置")
        self._load_configs()

# 全局配置实例
config_manager = ConfigManager()

# 从文件加载实际内容，这里不保留内置默认值
global_conf = {}
path = {}
download_setting = {}
update_setting = {}
network = {}


def init_config():
    # 初始化配置函数
    config_manager.init_config_sysjia 
"""