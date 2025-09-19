from functools import cache
import os
import sys
import json
import threading
import time
from .exceptions import ChangeConst, SetUnknownKey
from .logger import logger

class ConfigReader:
    """配置读取器类"""
    
    def __init__(self, config_dir):
        self.config_dir = config_dir
    
    def load_config(self, config_dict, dict_name):
        """加载单个配置文件"""
        config_file_path = os.path.join(self.config_dir, f"{dict_name}.json")
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    config_dict.update(loaded_config)
                logger.info(f"加载配置文件: {config_file_path}")
                return True
            except Exception as e:
                logger.error(f"读取配置文件 {config_file_path} 失败: {e}")
                return False
        return False
    
    def load_all_configs(self, config_dicts):
        """加载所有配置文件"""
        success_count = 0
        for dict_name, config_dict in config_dicts.items():
            if self.load_config(config_dict, dict_name):
                pass
            else:
                return False
        return True

class ConfigWriter:
    """配置写入器类"""
    
    def __init__(self, config_dir):
        self.config_dir = config_dir
    
    def save_config(self, config_dict, dict_name):
        """保存单个配置文件"""
        config_file_path = os.path.join(self.config_dir, f"{dict_name}.json")
        try:
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=4, ensure_ascii=False)
                logger.info(f"保存配置到文件: {config_file_path}")
            return True
        except Exception as e:
            logger.error(f"保存配置文件 {config_file_path} 失败: {e}")
            return False
    
    def save_all_configs(self, config_dicts):
        """保存所有配置文件"""
        success_count = 0
        for dict_name, config_dict in config_dicts.items():
            if self.save_config(config_dict, dict_name):
                pass
            else:
                return False
        return True

class ConfigDaemon:
    """配置守护线程类"""
    
    def __init__(self, config_reader, config_dicts, global_conf):
        self.config_reader = config_reader
        self.config_dicts = config_dicts
        self.global_conf = global_conf
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
            try:
                # 重新加载所有配置（包含 global_conf）
                self.config_reader.load_all_configs(self.config_dicts)
                logger.debug("守护线程重载配置完成")
            except Exception as e:
                logger.error(f"守护线程加载配置失败: {e}")
            time.sleep(global_conf['conf_reload_interval'])  # 定期执行


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
        
        # 设置配置目录
        self.config_dir = path['config_path']
        
        # 创建配置目录
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir, exist_ok=True)
            try:
                from .logger import logger
                logger.info(f"创建配置目录: {self.config_dir}")
            except:
                pass
        
        # 创建配置读写器
        self.reader = ConfigReader(self.config_dir)
        self.writer = ConfigWriter(self.config_dir)
        
        # 创建必要的目录
        self._create_necessary_directories()
        
        # 加载或创建配置文件
        config_files_exist = self._load_or_create_configs()
        
        # 设置系统运行状态
        self._set_system_status(config_files_exist)
        
        # 统一保存（包含 global_conf）在各自文件中，由上面的创建逻辑处理
        
        # 启动守护线程（global_conf 已纳入统一字典）
        self.daemon = ConfigDaemon(self.reader, self.config_dicts, global_conf)
        self.daemon.start_daemon()
        
        try:
            from .logger import logger
            logger.info("配置系统初始化完成")
        except:
            pass
    
    def _create_necessary_directories(self):
        """创建必要的目录"""
        config_dicts = [path, download_setting, network]
        for config_dict in config_dicts:
            path_keys = [key for key in config_dict.keys() if key.endswith('_path')]
            for key in path_keys:
                folder_path = config_dict[key]
                # 只创建目录，不创建文件
                if not os.path.exists(folder_path) and not os.path.isfile(folder_path):
                    try:
                        os.makedirs(folder_path, exist_ok=True)
                        logger.info(f"创建目录: {folder_path}")
                    except PermissionError:
                        logger.warning(f"无法创建目录 {folder_path}")
                    except Exception as e:
                        logger.warning(f"创建目录 {folder_path} 失败: {e}")
    
    def _load_or_create_configs(self):
        """加载或创建配置文件"""
        for dict_name, config_dict in self.config_dicts.items():
            config_file_path = os.path.join(self.config_dir, f"{dict_name}.json")
            if not os.path.exists(config_file_path):
                logger.warning(f"缺少配置文件: {config_file_path}，使用默认值创建")
                # 写入默认配置
                self.writer.save_config(config_dict, dict_name)
            # 加载（无论是新建的还是已存在的）
            self.reader.load_config(config_dict, dict_name)
        return True
    
    def _set_system_status(self, config_files_exist):
        """设置系统运行状态"""
        if not config_files_exist:
            global_conf['run'] = False
            try:
                from .logger import logger
                logger.warning("配置不完整，系统运行状态设置为False")
            except:
                pass
        else:
            global_conf['run'] = True
            try:
                from .logger import logger
                logger.info("配置完整，系统运行状态设置为True")
            except:
                pass
    
    def reload_config(self):
        """手动重载配置"""
        try:
            from .logger import logger
            logger.info("开始手动重载配置")
        except:
            pass
        
        self._load_or_create_configs()
        
        try:
            from .logger import logger
            logger.info("配置重载成功")
        except:
            print("配置重载成功")


# 全局配置实例
config_manager = ConfigManager()

global_conf={
    "run":False,
    "conf_reload_interval":300,
}

path={
    "db_file": "docker/spider.db", #数据库路径
    "config_path": "docker/config",#配置文件路径
    "log_path": "docker/logs",#日志路径
    "download_path": "docker/download",#下载路径
    "download_cache_path": "docker/download_cache",#下载缓存路径
}

download_setting={
    "download_thread":1,    #下载线程数
    "once_download":-1,     #每次启动下载后的下载数量，-1为不限
    "waiting_play":False,   #是否在下载之间插入长睡眠，以模拟正常播放
    "sleep_second":10,      #如果不启用长睡眠，每个下载的间隔
    "download_vip":False,   #是否下载vip内容
    "use_cache":False,       #是否使用缓存
    "download_interval":10, #每多久下载一次，模拟用户一天不可能24h观看,仅设定了“once_download”时有效
}

update_setting={
    "update_thread":1,      #更新线程数
    "check_interval":86400, #检查更新的频率,-1是不检查
}

network={

    "use_proxy":False,        #是否使用代理
    "proxy_ip":"127.0.0.1",#代理ip
    "proxy_port":"7897",  #代理端口

    "use_cookie":True,                  #是否使用cookie
    "domain":"https://www.pixiv.net",   #需要下载的域名

    "cookie_file": "docker/resource/cookie.pkl",#cookies路径
    
    # 三个路径下的chrome_driver路径
    "windows_chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chromedriver.exe",#windows路径
    "linux_chrome_path": "/usr/local/bin/chromedriver",#linux路径
    "mac_chrome_path": "/usr/local/bin/chromedriver",#mac路径

    "chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",#chrome路径
}


def init_config():
    """初始化配置函数"""
    config_manager.init_config_system()


def validate_config_value(key, value, config_dict):
    """验证配置值的类型和范围"""
    try:
        from .logger import logger
        logger.debug(f"验证配置项: {key} = {value}")
    except:
        pass
    
    if key == 'download_thread' or key == 'update_thread':
        if not isinstance(value, int) or value <= 0:
            error_msg = f"{key} 必须是正整数"
            try:
                from .logger import logger
                logger.error(f"配置验证失败: {error_msg}")
            except:
                pass
            raise ValueError(error_msg)
    elif key == 'once_download':
        if not isinstance(value, int) or value < -1:
            error_msg = f"{key} 必须是大于等于-1的整数"
            try:
                from .logger import logger
                logger.error(f"配置验证失败: {error_msg}")
            except:
                pass
            raise ValueError(error_msg)
    elif key == 'sleep_second' or key == 'check_interval':
        if not isinstance(value, int) or value < 0:
            error_msg = f"{key} 必须是非负整数"
            try:
                from .logger import logger
                logger.error(f"配置验证失败: {error_msg}")
            except:
                pass
            raise ValueError(error_msg)
    elif key in ['waiting_play', 'download_vip', 'use_cache', 'use_proxy', 'use_cookie']:
        if not isinstance(value, bool):
            error_msg = f"{key} 必须是布尔值"
            try:
                from .logger import logger
                logger.error(f"配置验证失败: {error_msg}")
            except:
                pass
            raise ValueError(error_msg)
    elif key == 'proxy_port':
        if not isinstance(value, str) or not value.isdigit() or not (1 <= int(value) <= 65535):
            error_msg = f"{key} 必须是1-65535之间的端口号"
            try:
                from .logger import logger
                logger.error(f"配置验证失败: {error_msg}")
            except:
                pass
            raise ValueError(error_msg)

def save_config_to_file(config_dict, dict_name):
    """保存配置到文件"""
    if config_manager.writer:
        config_manager.writer.save_config(config_dict, dict_name)
    else:
        # 如果配置管理器未初始化，使用旧方法
        config_dir = path['config_path']
        config_file_path = os.path.join(config_dir, f"{dict_name}.json")
        try:
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=4, ensure_ascii=False)
            try:
                from .logger import logger
                logger.info(f"保存配置到文件: {config_file_path}")
            except:
                pass
        except Exception as e:
            try:
                from .logger import logger
                logger.error(f"保存配置文件 {config_file_path} 失败: {e}")
            except:
                print(f"保存配置文件 {config_file_path} 失败: {e}")

def reload_config():
    """手动重载配置"""
    if config_manager:
        config_manager.reload_config()
    else:
        # 如果配置管理器未初始化，使用旧方法（统一加载所有配置，包括 global_conf）
        try:
            from .logger import logger
            logger.info("开始手动重载配置")
        except:
            pass
        
        config_dir = path['config_path']
        config_dicts = {
            'path': path,
            'download_setting': download_setting,
            'update_setting': update_setting,
            'network': network,
            'global_conf': global_conf,
        }
        
        try:
            for dict_name, config_dict in config_dicts.items():
                config_file_path = os.path.join(config_dir, f"{dict_name}.json")
                if os.path.exists(config_file_path):
                    with open(config_file_path, 'r', encoding='utf-8') as f:
                        loaded_config = json.load(f)
                        config_dict.update(loaded_config)
            
            try:
                from .logger import logger
                logger.info("配置重载成功")
            except:
                print("配置重载成功")
        except Exception as e:
            try:
                from .logger import logger
                logger.error(f"配置重载失败: {e}")
            except:
                print(f"配置重载失败: {e}")

def get_path(key):
    """获取path字典中的值"""
    if key not in path:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return path.get(key)

def set_path(key, value):
    """设置path字典中的值"""
    if key not in path:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('_file') or key.endswith('_path'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, path)
    path[key] = value
    save_config_to_file(path, 'path')
    try:
        from .logger import logger
        logger.info(f"设置配置项: path.{key} = {value}")
    except:
        pass

def get_download_setting(key):
    """获取download_setting字典中的值"""
    if key not in download_setting:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return download_setting.get(key)

def set_download_setting(key, value):
    """设置download_setting字典中的值"""
    if key not in download_setting:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('_file') or key.endswith('_path'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, download_setting)
    download_setting[key] = value
    save_config_to_file(download_setting, 'download_setting')
    try:
        from .logger import logger
        logger.info(f"设置配置项: download_setting.{key} = {value}")
    except:
        pass

def get_update_setting(key):
    """获取update_setting字典中的值"""
    if key not in update_setting:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return update_setting.get(key)

def set_update_setting(key, value):
    """设置update_setting字典中的值"""
    if key not in update_setting:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('_file') or key.endswith('_path'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, update_setting)
    update_setting[key] = value
    save_config_to_file(update_setting, 'update_setting')
    try:
        from .logger import logger
        logger.info(f"设置配置项: update_setting.{key} = {value}")
    except:
        pass

def get_network(key):
    """获取network字典中的值"""
    if key not in network:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return network.get(key)

def set_network(key, value):
    """设置network字典中的值"""
    if key not in network:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('_file') or key.endswith('_path'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, network)
    network[key] = value
    save_config_to_file(network, 'network')
    try:
        from .logger import logger
        logger.info(f"设置配置项: network.{key} = {value}")
    except:
        pass

# 为了向后兼容，保留旧的函数名
def get_proxy(key):
    """获取proxy字典中的值（向后兼容）"""
    return get_network(key)

def set_proxy(key, value):
    """设置proxy字典中的值（向后兼容）"""
    return set_network(key, value)

def get_browser(key):
    """获取browser字典中的值（向后兼容）"""
    return get_network(key)

def set_browser(key, value):
    """设置browser字典中的值（向后兼容）"""
    return set_network(key, value)

def get_global_conf(key):
    """获取global_conf字典中的值"""
    if key not in global_conf:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return global_conf.get(key)

def set_global_conf(key, value):
    """设置global_conf字典中的值"""
    if key not in global_conf:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('_file') or key.endswith('_path'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, global_conf)
    global_conf[key] = value
    save_config_to_file(global_conf, 'global_conf')
    try:
        from .logger import logger
        logger.info(f"设置配置项: global_conf.{key} = {value}")
    except:
        pass

