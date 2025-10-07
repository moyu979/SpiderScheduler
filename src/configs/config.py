from functools import cache
import os
import sys
import json
import threading
import time
from src.logger import logger

from src.configs.globalVars import work_path

class ConfigReader:
    """配置读取器类"""
    
    def __init__(self, config_dir):
        self.config_dir = config_dir
    
    def load_config(self, config_dict, dict_name):
        """加载单个配置文件"""
        config_file_path = os.path.join(self.config_dir, f"{dict_name}.json")
        with open(config_file_path, 'r', encoding='utf-8') as f:
            loaded_config = json.load(f)
        config_dict.update(loaded_config)
        logger.info(f"加载配置文件: {config_file_path}")
        
    
    def load_all_configs(self, config_dicts):
        """加载所有配置文件"""
        for dict_name, config_dict in config_dicts.items():
            self.load_config(config_dict, dict_name)

class ConfigWriter:
    """配置写入器类"""
    
    def __init__(self, config_dir):
        self.config_dir = config_dir
    
    def save_config(self, config_dict, dict_name):
        """保存单个配置文件"""
        config_file_path = os.path.join(self.config_dir, f"{dict_name}.json")
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
            logger.info(f"保存配置到文件: {config_file_path}")
    
    def save_all_configs(self, config_dicts):
        """保存所有配置文件"""
        for dict_name, config_dict in config_dicts.items():
            self.save_config(config_dict, dict_name)

class ConfigDaemon:
    """配置守护线程类"""
    
    def __init__(self, config_reader, config_dicts):
        self.config_reader = config_reader
        self.config_dicts = config_dicts
        self.daemon_thread = None
        self.running = False
    
    def start_daemon(self):
        """启动守护线程"""
        if self.running:
            return
        
        self.running = True
        self.daemon_thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self.daemon_thread.start()
        
        logger.info("配置守护线程已启动")

    
    def stop_daemon(self):
        """停止守护线程"""
        self.running = False
        if self.daemon_thread:
            self.daemon_thread.join(timeout=1)
    
    def _daemon_loop(self):
        """守护线程循环"""
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
    """配置管理器类"""
    
    def __init__(self):
        self.config_dir = None
        self.reader = None
        self.writer = None
        self.daemon = None
        self.config_dicts = None  # 将在init_config_system中设置
    
    def init_config_system(self):
        """初始化配置系统"""
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
        """仅加载配置文件（不创建默认值），若缺失返回 False"""
        logger.info(f"加载全部配置文件")
        self.reader.load_all_configs(self.config_dicts)
    
    def reload_config(self):
        """手动重载配置"""
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
    """初始化配置函数"""
    config_manager.init_config_system()

def get(dict,key):
    global config_manager
    return config_manager.config_dicts.get(dict,{}).get(key)