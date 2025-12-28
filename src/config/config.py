from functools import cache
import os
import sys
import json
import threading
import time

from src.utils.logging.logger import SpiderLogger as logger
from src.config.globalVars import config_path


class GetUnknownKey(Exception):
    """尝试获取不存在的配置键时抛出的异常"""
    pass

class ConfigManager:
    """配置管理器类"""

    # 全局配置字典
    config_dict = {}
    # 配置字典访问锁
    _config_lock = threading.Lock()
    # 守护线程状态
    _daemon_thread = None
    _running = False
    
    @classmethod
    def init_config(cls):
        """获取配置值"""
        ConfigManager.load_all_configs()
        ConfigManager.start_daemon()

    @classmethod
    def load_all_configs(cls):
        """初始化配置函数 - 加载config_path中的所有JSON文件"""
        with cls._config_lock:
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
                                logger.debug(f"加载配置文件: {config_file_path}")
                        except Exception as e:
                            logger.error(f"加载配置文件失败 {config_file_path}: {e}")
            else:
                logger.error(f"配置目录不存在: {config_path}")
                raise FileNotFoundError(f"配置目录不存在: {config_path}")
    
    @classmethod
    def start_daemon(cls):
        """启动守护线程，定期重载配置"""
        if cls._running:
            return
        cls._running = True
        cls._daemon_thread = threading.Thread(target=cls._daemon_loop, daemon=True)
        cls._daemon_thread.start()
        logger.info("配置守护线程已启动")
    
    @classmethod
    def stop_daemon(cls):
        """停止守护线程"""
        cls._running = False
        if cls._daemon_thread is not None:
            cls._daemon_thread.join(timeout=ConfigManager.get("global_conf","conf_reload_interval")*2)
            cls._daemon_thread = None
    
    @classmethod
    def _daemon_loop(cls):
        """守护线程循环"""
        while cls._running:
            time.sleep(ConfigManager.get("global_conf","conf_reload_interval"))
            logger.debug("守护线程执行一次配置重载")
            cls.load_all_configs()
    
    @classmethod
    def get(cls, dict_name, key):
        """获取配置值"""
        with cls._config_lock:
            value = cls.config_dict.get(dict_name, {}).get(key, None)
            if value is None:
                logger.error(f"配置值不存在: {dict_name}, {key}")
                for key in cls.config_dict.keys():
                    print(f"配置值: {key}")
                raise GetUnknownKey(f"配置值不存在: {dict_name}, {key}")
            return value
        
    @classmethod
    def set(cls, dict_name, key, value):
        """设置配置值并保存到文件"""
        with cls._config_lock:
            if dict_name not in cls.config_dict:
                logger.error(f"配置字典不存在: {dict_name}")
                raise KeyError(f"配置字典不存在: {dict_name}")
            logger.debug(f"设置配置值: {dict_name}, {key}, {value}")
            cls.config_dict[dict_name][key] = value
            cls._save_config(dict_name)
    
    @classmethod
    def _save_config(cls, dict_name):
        """将指定配置字典保存到文件"""
        with cls._config_lock:
            if dict_name not in cls.config_dict:
                logger.error(f"配置字典不存在，无法保存: {dict_name}")
                return
        
            config_file_path = os.path.join(config_path, f"{dict_name}.json")

            try:
                # 确保目录存在
                os.makedirs(config_path, exist_ok=True)

                # 写入文件（使用临时文件确保原子性）
                temp_file_path = config_file_path + ".tmp"
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump(cls.config_dict[dict_name], f, ensure_ascii=False, indent=4)

                # 原子性替换
                os.replace(temp_file_path, config_file_path)
                logger.debug(f"配置已保存到文件: {config_file_path}")
            except Exception as e:
                logger.error(f"保存配置文件失败 {config_file_path}: {e}")
                # 清理临时文件
                temp_file_path = config_file_path + ".tmp"
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except:
                        pass
                raise

    
config_manager = ConfigManager()