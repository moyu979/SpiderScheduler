import os
import json
import threading
import time
from .exceptions import ChangeConst, SetUnknownKey

global_conf={
    "run":False,
}


path={
    "DB_FILE": "docker/data/spider.db", #数据库路径
    "CONFIG_PATH": "docker/config",#配置文件路径
    "LOG_PATH": "docker/logs",#日志路径
\
}

download_setting={
    "download_thread":1,    #下载线程数
    "once_download":-1,     #一次下载数量，-1为不限
    "waiting_play":False,   #是否在下载之间插入长睡眠，以模拟正常播放
    "sleep_second":10,      #如果不启用长睡眠，每个下载的间隔
    "download_vip":False,   #是否下载vip内容
    "use_cache":True,       #是否使用缓存
    "download_interval":10, #每多久下载一次，模拟用户一天不可能24h观看 

    "CACHE_PATH":"./docker/data/cache", #缓存路径
    "DOWNLOAD_PATH":"./docker/data/download", #下载路径
}

update_setting={
    "update_thread":1,      #更新线程数

    "check_interval":86400, #检查更新的频率,-1是不检查
}

proxy={
    "use_proxy":False,        #是否使用代理
    "proxy_ip":"127.0.0.1",#代理ip
    "proxy_port":"7897",  #代理端口
}

browser={
    "use_cookie":True,                  #是否使用cookie
    "domain":"https://www.pixiv.net",   #使用的域名

    "COOKIE_FILE": "docker/resource/cookie.pkl",#cookies路径
    "CHROME_FILE": "C:\Program Files\Google\Chrome\Application\chrome.exe",#chrome路径
}


def init_config():
    """初始化配置函数"""
    import os
    import json
    import threading
    import time
    
    # 记录初始化开始
    try:
        from .logger import logger
        logger.info("开始初始化配置系统")
    except:
        pass
    
    # 检查以PATH结尾的文件夹是否存在，不存在则新建
    path_keys = [key for key in path.keys() if key.endswith('PATH')]
    for key in path_keys:
        folder_path = path[key]
        if not os.path.exists(folder_path):
            os.makedirs(folder_path, exist_ok=True)
            try:
                from .logger import logger
                logger.info(f"创建目录: {folder_path}")
            except:
                pass
    
    # 检查download_setting中以PATH结尾的文件夹
    download_path_keys = [key for key in download_setting.keys() if key.endswith('PATH')]
    for key in download_path_keys:
        folder_path = download_setting[key]
        if not os.path.exists(folder_path):
            os.makedirs(folder_path, exist_ok=True)
            try:
                from .logger import logger
                logger.info(f"创建目录: {folder_path}")
            except:
                pass
    
    # 检查browser中以PATH结尾的文件夹
    browser_path_keys = [key for key in browser.keys() if key.endswith('PATH')]
    for key in browser_path_keys:
        folder_path = browser[key]
        if not os.path.exists(folder_path):
            os.makedirs(folder_path, exist_ok=True)
            try:
                from .logger import logger
                logger.info(f"创建目录: {folder_path}")
            except:
                pass
    
    # 检查所有字典里以FILE结尾的key的value文件是否存在（不新建）
    file_exists = True
    for config_dict in [path, download_setting, update_setting, proxy, browser]:
        for key, value in config_dict.items():
            if key.endswith('FILE'):
                if not os.path.exists(value):
                    file_exists = False
                    try:
                        from .logger import logger
                        logger.warning(f"文件不存在: {value}")
                    except:
                        pass
    
    # 检查CONFIG_PATH文件夹下以字典命名的json文件
    config_dir = path['CONFIG_PATH']
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        try:
            from .logger import logger
            logger.info(f"创建配置目录: {config_dir}")
        except:
            pass
    
    config_files_exist = True
    config_dicts = {
        'path': path,
        'download_setting': download_setting,
        'update_setting': update_setting,
        'proxy': proxy,
        'browser': browser
    }
    
    for dict_name, config_dict in config_dicts.items():
        config_file_path = os.path.join(config_dir, f"{dict_name}.json")
        if os.path.exists(config_file_path):
            # 读取配置文件
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 更新当前配置
                    config_dict.update(loaded_config)
                try:
                    from .logger import logger
                    logger.info(f"加载配置文件: {config_file_path}")
                except:
                    pass
            except Exception as e:
                try:
                    from .logger import logger
                    logger.error(f"读取配置文件 {config_file_path} 失败: {e}")
                except:
                    print(f"读取配置文件 {config_file_path} 失败: {e}")
        else:
            # 使用默认值新建配置文件
            config_files_exist = False
            try:
                with open(config_file_path, 'w', encoding='utf-8') as f:
                    json.dump(config_dict, f, indent=4, ensure_ascii=False)
                try:
                    from .logger import logger
                    logger.info(f"创建配置文件: {config_file_path}")
                except:
                    pass
            except Exception as e:
                try:
                    from .logger import logger
                    logger.error(f"创建配置文件 {config_file_path} 失败: {e}")
                except:
                    print(f"创建配置文件 {config_file_path} 失败: {e}")
    
    # 设置globa_conf的run值
    if not file_exists or not config_files_exist:
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
    
    # 保存globa_conf到文件
    global_config_path = os.path.join(config_dir, 'global_conf.json')
    try:
        with open(global_config_path, 'w', encoding='utf-8') as f:
            json.dump(global_conf, f, indent=4, ensure_ascii=False)
        try:
            from .logger import logger
            logger.info(f"保存全局配置: {global_config_path}")
        except:
            pass
    except Exception as e:
        try:
            from .logger import logger
            logger.error(f"保存global_conf失败: {e}")
        except:
            print(f"保存global_conf失败: {e}")
    
    def load_conf():
        """加载配置的守护线程函数"""
        while True:
            try:
                for dict_name, config_dict in config_dicts.items():
                    config_file_path = os.path.join(config_dir, f"{dict_name}.json")
                    if os.path.exists(config_file_path):
                        with open(config_file_path, 'r', encoding='utf-8') as f:
                            loaded_config = json.load(f)
                            config_dict.update(loaded_config)
                
                # 重新加载global_conf
                global_config_path = os.path.join(config_dir, 'global_conf.json')
                if os.path.exists(global_config_path):
                    with open(global_config_path, 'r', encoding='utf-8') as f:
                        loaded_global_conf = json.load(f)
                        global_conf.update(loaded_global_conf)
                        
                try:
                    from .logger import logger
                    logger.debug("守护线程重载配置完成")
                except:
                    pass
            except Exception as e:
                try:
                    from .logger import logger
                    logger.error(f"守护线程加载配置失败: {e}")
                except:
                    print(f"守护线程加载配置失败: {e}")
            
            time.sleep(300)  # 每5分钟执行一次
    
    # 启动守护线程
    daemon_thread = threading.Thread(target=load_conf, daemon=True)
    daemon_thread.start()
    
    try:
        from .logger import logger
        logger.info("配置系统初始化完成")
    except:
        pass


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
    config_dir = path['CONFIG_PATH']
    config_file_path = os.path.join(config_dir, f"{dict_name}.json")
    print("_________________________",config_file_path)
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
    try:
        from .logger import logger
        logger.info("开始手动重载配置")
    except:
        pass
    
    config_dir = path['CONFIG_PATH']
    config_dicts = {
        'path': path,
        'download_setting': download_setting,
        'update_setting': update_setting,
        'proxy': proxy,
        'browser': browser
    }
    
    try:
        for dict_name, config_dict in config_dicts.items():
            config_file_path = os.path.join(config_dir, f"{dict_name}.json")
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    config_dict.update(loaded_config)
        
        # 重新加载global_conf
        global_config_path = os.path.join(config_dir, 'global_conf.json')
        if os.path.exists(global_config_path):
            with open(global_config_path, 'r', encoding='utf-8') as f:
                loaded_global_conf = json.load(f)
                global_conf.update(loaded_global_conf)
        
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
    if key.endswith('FILE') or key.endswith('PATH'):
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
    if key.endswith('FILE') or key.endswith('PATH'):
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
    if key.endswith('FILE') or key.endswith('PATH'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, update_setting)
    update_setting[key] = value
    save_config_to_file(update_setting, 'update_setting')
    try:
        from .logger import logger
        logger.info(f"设置配置项: update_setting.{key} = {value}")
    except:
        pass

def get_proxy(key):
    """获取proxy字典中的值"""
    if key not in proxy:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return proxy.get(key)

def set_proxy(key, value):
    """设置proxy字典中的值"""
    if key not in proxy:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('FILE') or key.endswith('PATH'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, proxy)
    proxy[key] = value
    save_config_to_file(proxy, 'proxy')
    try:
        from .logger import logger
        logger.info(f"设置配置项: proxy.{key} = {value}")
    except:
        pass

def get_browser(key):
    """获取browser字典中的值"""
    if key not in browser:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return browser.get(key)

def set_browser(key, value):
    """设置browser字典中的值"""
    if key not in browser:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('FILE') or key.endswith('PATH'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, browser)
    browser[key] = value
    save_config_to_file(browser, 'browser')
    try:
        from .logger import logger
        logger.info(f"设置配置项: browser.{key} = {value}")
    except:
        pass

def get_global_conf(key):
    """获取global_conf字典中的值"""
    if key not in global_conf:
        raise SetUnknownKey(f"配置键不存在: {key}")
    return global_conf.get(key)

def set_global_conf(key, value):
    """设置global_conf字典中的值"""
    if key not in global_conf:
        raise SetUnknownKey(f"配置键不存在: {key}")
    if key.endswith('FILE') or key.endswith('PATH'):
        raise ChangeConst(f"不能修改常量配置: {key}")
    validate_config_value(key, value, global_conf)
    global_conf[key] = value
    save_config_to_file(global_conf, 'global_conf')
    try:
        from .logger import logger
        logger.info(f"设置配置项: global_conf.{key} = {value}")
    except:
        pass

