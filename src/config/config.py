from functools import cache
import os
import sys
import json
import threading
import time

from src.utils.logging.logger import SpiderLogger as logger
from src.config.globalVars import work_path
from src.config.globalVars import config_path
from src.utils.exceptions import GetUnknownKey

class ConfigManager:
    """配置管理器类"""
    
    # 全局配置字典
    config_dict = {}
    # 守护线程状态
    _daemon_thread = None
    _running = False
    _interval = 300
    
    @classmethod
    def init_config(cls):
        """获取配置值"""
        ConfigManager.load_all_configs()
        ConfigManager.start_daemon()

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
    def start_daemon(cls, interval: int = 10):
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
            cls._interval=cls.get("global_conf","conf_reload_interval")
    
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

    
