from functools import cache
import os
import sys
import json
import threading
import time

from src.utils.logging.logger import SpiderLogger as logger
from src.config.paths import config_path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


class GetUnknownKey(Exception):
    """尝试获取不存在的配置键时抛出的异常"""
    pass

class ConfigManager:
    """配置管理器类"""

    # 全局配置字典
    config_dict = {}
    # 配置字典访问锁
    _config_lock = threading.RLock()
    # 守护线程状态
    _daemon_thread = None
    _stop_event = threading.Event()

    # 基础路径超参数，这个会在配置加载之前加载，所以要独立放
    base_path = os.path.join("./docker")
    
    @classmethod
    def init_config(cls):
        """获取配置值"""
        ConfigManager.load_all_configs()
        ConfigManager._load_from_env()
        ConfigManager.start_daemon()

    @classmethod
    def load_all_configs(cls):
        """初始化配置函数 - 加载config_path中的所有配置文件（优先 YAML，其次 JSON）"""
        with cls._config_lock:
            # 清空全局字典
            cls.config_dict.clear()

            # 遍历 config_path 中的配置文件
            if os.path.exists(config_path()):
                filenames = os.listdir(config_path())

                # 同名配置优先级：yaml > yml > json
                priority = {".yaml": 0, ".yml": 1, ".json": 2}
                selected = {}
                # 构建文件字典
                for filename in filenames:
                    base, ext = os.path.splitext(filename)
                    ext = ext.lower()
                    if ext not in priority:
                        continue
                    prev = selected.get(base)
                    if prev is None or priority[ext] < priority[prev[1]]:
                        selected[base] = (filename, ext)

                # 加载配置文件
                for config_name, (filename, ext) in selected.items():
                    config_file_path = os.path.join(config_path(), filename)
                    try:
                        with open(config_file_path, 'r', encoding='utf-8') as f:
                            if ext in (".yaml", ".yml"):
                                if yaml is None:
                                    raise RuntimeError(
                                        "缺少 PyYAML 依赖，无法加载 YAML 配置文件。请安装 pyyaml。"
                                    )
                                config_data = yaml.safe_load(f) or {}
                            else:
                                config_data = json.load(f)

                        if not isinstance(config_data, dict):
                            raise ValueError(f"配置文件根节点必须是对象/字典，实际为: {type(config_data)}")
                        #print(f"加载配置文件: {config_name}, {config_data}")
                        cls.config_dict[config_name] = config_data
                        logger.debug(f"加载配置文件: {config_file_path}")
                    except Exception as e:
                        logger.error(f"加载配置文件失败 {config_file_path}: {e}")
            else:
                logger.error(f"配置目录不存在: {config_path()}")
                raise FileNotFoundError(f"配置目录不存在: {config_path()}")
    
    @classmethod
    def start_daemon(cls):
        """启动守护线程，定期重载配置"""
        with cls._config_lock:
            if cls._daemon_thread is not None and cls._daemon_thread.is_alive():
                return

            cls._stop_event.clear()
            cls._daemon_thread = threading.Thread(target=cls._daemon_loop, daemon=True)
            cls._daemon_thread.start()
            logger.info("配置守护线程已启动")
    
    @classmethod
    def stop_daemon(cls):
        """停止守护线程"""
        with cls._config_lock:
            if cls._daemon_thread is None:
                return

            cls._stop_event.set()
            try:
                timeout = ConfigManager.get("global_conf", "conf_retry_interval") * 2
            except Exception:
                timeout = 5

            cls._daemon_thread.join(timeout=timeout)
            if not cls._daemon_thread.is_alive():
                cls._daemon_thread = None
            else:
                logger.warning("配置守护线程停止超时，线程仍在运行")
    
    @classmethod
    def _daemon_loop(cls):
        """守护线程循环"""
        while not cls._stop_event.is_set():
            try:
                interval = ConfigManager.get("global_conf", "conf_reload_interval")
            except Exception:
                interval = 10

            # Event.wait 可被 stop_daemon 立即唤醒，避免 sleep 卡住退出
            if cls._stop_event.wait(timeout=interval):
                break

            logger.debug("守护线程执行一次配置重载")
            cls.load_all_configs()
    
    @classmethod
    def get(cls, dict_name, key):
        # print(f"获取配置值: {dict_name}, {key}")
        """获取配置值"""
        with cls._config_lock:
            value = cls.config_dict.get(dict_name, {}).get(key, None)
            if value is None:
                logger.error(f"配置值不存在: {dict_name}, {key}")
                if dict_name not in cls.config_dict:
                    print(f"配置字典不存在: {dict_name}")
                    for dict_name in cls.config_dict.keys():
                        print(f"配置字典: {dict_name}")
                    raise GetUnknownKey(f"配置字典不存在: {dict_name}")    
                if key not in cls.config_dict[dict_name]:
                    print(f"配置值不存在: {dict_name}, {key}")
                    for key in cls.config_dict[dict_name].keys():
                        print(f"配置值: {key}")
                    raise GetUnknownKey(f"配置值不存在: {dict_name}, {key}")
                # for key in cls.config_dict.keys():
                #     print(f"配置值: {key}")
                raise GetUnknownKey(f"读取配置遇到未知错误: {dict_name}, {key}")
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
    def _load_from_env(cls):
        """从环境变量加载配置，覆盖已加载的配置值"""
        with cls._config_lock:
            modified_dicts = set()  # 记录哪些字典被修改了
            
            # 第一步：遍历并更新内存中的配置（不保存文件）
            for dict_name, config_data in cls.config_dict.items():
                for key in config_data.keys():
                    # 构建环境变量名：DICT_NAME_KEY (大写，下划线分隔)
                    env_var_name = f"{dict_name.upper().replace('-', '_')}_{key.upper()}"
                    
                    # 检查环境变量是否存在
                    env_value = os.environ.get(env_var_name)
                    if env_value is not None:
                        try:
                            # 尝试解析为 JSON（支持布尔值、数字等）
                            try:
                                parsed_value = json.loads(env_value)
                            except (json.JSONDecodeError, ValueError):
                                # 如果不是有效的 JSON，作为字符串处理
                                parsed_value = env_value
                            
                            # 直接更新内存中的配置（不保存文件）
                            cls.config_dict[dict_name][key] = parsed_value
                            modified_dicts.add(dict_name)  # 记录这个字典被修改了
                            logger.info(f"从环境变量加载配置: {env_var_name} = {parsed_value}")
                        except Exception as e:
                            logger.warning(f"从环境变量加载配置失败 {env_var_name}: {e}")
            
            # 第二步：批量保存所有修改过的字典
            for dict_name in modified_dicts:
                try:
                    cls._save_config(dict_name)
                    logger.debug(f"批量保存配置字典: {dict_name}")
                except Exception as e:
                    logger.error(f"保存配置字典失败 {dict_name}: {e}")
    
    @classmethod
    def _save_config(cls, dict_name):
        """将指定配置字典保存到文件"""
        with cls._config_lock:
            if dict_name not in cls.config_dict:
                logger.error(f"配置字典不存在，无法保存: {dict_name}")
                return

            yaml_path = os.path.join(config_path(), f"{dict_name}.yaml")
            yml_path = os.path.join(config_path(), f"{dict_name}.yml")
            json_path = os.path.join(config_path(), f"{dict_name}.json")

            # 保存时尽量保持“已有文件格式”
            if os.path.exists(yaml_path) or os.path.exists(yml_path):
                if yaml is None:
                    raise RuntimeError("缺少 PyYAML 依赖，无法保存 YAML 配置文件。请安装 pyyaml。")
                config_file_path = yaml_path if os.path.exists(yaml_path) else yml_path
                fmt = "yaml"
            else:
                config_file_path = json_path
                fmt = "json"

            try:
                # 确保目录存在
                os.makedirs(config_path(), exist_ok=True)

                # 写入文件（使用临时文件确保原子性）
                temp_file_path = config_file_path + ".tmp"
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    if fmt == "yaml":
                        yaml.safe_dump(
                            cls.config_dict[dict_name],
                            f,
                            allow_unicode=True,
                            sort_keys=False,
                            default_flow_style=False,
                        )
                    else:
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