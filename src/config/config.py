"""配置管理器：加载、热重载、环境变量覆盖与持久化。

数据结构：config_dict 是"配置段名 → 键值字典"的两层字典，每个段对应
confs/ 下的一个 yaml/json 文件（同名时 yaml > yml > json）。

线程模型：所有读写经 _config_lock（RLock）串行；热重载采用
"局部构建完整副本 → 锁内整体换入"，读方不会看到空窗，目录级失败时
旧配置原样保留（守护线程兜底重试，见 _daemon_loop）。
"""

import json
import os
import threading

from src.utils.logging.logger import SpiderLogger as logger
from src.config.paths import config_path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


class GetUnknownKey(Exception):
    """尝试获取不存在的配置键（段或键缺失）时抛出的异常。"""


# site_setting 的 default 参数哨兵：未传时键全链缺失仍抛 GetUnknownKey
_UNSET = object()


class ConfigManager:
    """配置管理器：加载、热重载、环境变量覆盖与持久化。

    数据结构：config_dict 是“配置段名 → 键值字典”的两层字典，每个段对应
    confs/ 下的一个 yaml/json 文件。

    线程模型：所有读写经 _config_lock（RLock）串行；热重载采用
    “局部构建完整副本 → 锁内整体换入”，读方不会看到空窗。

    Attributes:
        config_dict: 配置段名 → 键值字典 的两层字典。
        _config_lock: 保护 config_dict 与写盘的全局可重入锁。
        _daemon_thread: 热重载守护线程，start_daemon/stop_daemon 管理。
        _stop_event: 守护线程的停止信号。
        base_path: 工作目录（BASEPATH），在配置加载之前独立初始化。
    """

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
        """初始化入口：加载全部配置文件并启动热重载守护线程。"""
        ConfigManager.load_all_configs()
        ConfigManager.start_daemon()

    @classmethod
    def load_all_configs(cls):
        """加载 config_path 中的所有配置文件（优先 YAML，其次 JSON）

        先在局部构建完整副本，最后整体替换 config_dict：
        热重载期间读方（get/调度循环）不会看到清空后的空窗；
        目录缺失等整体失败时旧配置原样保留。
        """
        loaded = {}
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
                    loaded[config_name] = config_data
                    logger.debug(f"加载配置文件: {config_file_path}")
                except Exception as e:
                    logger.error(f"加载配置文件失败 {config_file_path}: {e}")
        else:
            logger.error(f"配置目录不存在: {config_path()}")
            raise FileNotFoundError(f"配置目录不存在: {config_path()}")

        with cls._config_lock:
            # 整体换入 + 重新应用环境变量覆盖（仅内存，不回写文件）
            cls.config_dict = loaded
            cls._apply_env_overrides()
    
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
                timeout = ConfigManager.get("system", "conf_retry_interval") * 2
            except Exception:
                timeout = 5

            cls._daemon_thread.join(timeout=timeout)
            if not cls._daemon_thread.is_alive():
                cls._daemon_thread = None
            else:
                logger.warning("配置守护线程停止超时，线程仍在运行")
    
    @classmethod
    def _daemon_loop(cls):
        """守护线程循环：按 conf_reload_interval 周期热重载，异常只记录不退出。"""
        while not cls._stop_event.is_set():
            try:
                interval = ConfigManager.get("system", "conf_reload_interval")
            except Exception:
                interval = 10

            # Event.wait 可被 stop_daemon 立即唤醒，避免 sleep 卡住退出
            if cls._stop_event.wait(timeout=interval):
                break

            logger.debug("守护线程执行一次配置重载")
            # 热重载的任何异常（目录短暂缺失、os.listdir 抛 OSError 等）只记录、
            # 不退出：旧配置继续生效，下个周期自动重试。守护线程若在此死亡，
            # 热重载会静默永久失效。首次加载走 init_config，仍会抛错终止启动。
            try:
                cls.load_all_configs()
            except Exception as e:
                logger.error(f"配置热重载失败（保留旧配置，下个周期重试）: {e}")
    
    @classmethod
    def get(cls, dict_name, key):
        """获取配置值；字典或键不存在抛 GetUnknownKey，值为 None 合法；
        字符串值中的 ${BASE_PATH} 占位符会替换为实际工作目录"""
        with cls._config_lock:
            config_data = cls.config_dict.get(dict_name)
            if config_data is None:
                existing = ", ".join(cls.config_dict.keys()) or "无"
                logger.error(f"配置字典不存在: {dict_name}，现有: {existing}")
                raise GetUnknownKey(f"配置字典不存在: {dict_name}")
            if key not in config_data:
                existing = ", ".join(config_data.keys()) or "无"
                logger.error(f"配置值不存在: {dict_name}, {key}，现有键: {existing}")
                raise GetUnknownKey(f"配置值不存在: {dict_name}, {key}")
            value = config_data[key]
            if isinstance(value, str) and '${BASE_PATH}' in value:
                value = value.replace('${BASE_PATH}', str(cls.base_path))
            return value
        
    @classmethod
    def site_setting(cls, section, website, key, default=_UNSET):
        """站点级配置读取：section.site.<website> > section.site.default > 代码兜底。

        合并式配置段（download / update）里，站点可覆盖的键统一放在 `site`
        结构下：`site.default` 是全部站点共用的默认值（default 是保留名，不能
        作为真实站点名），`site.<website>` 按站点覆盖。两层都未配置时回落参数
        default；覆盖值中的 ${BASE_PATH} 同样替换为工作目录。

        Args:
            section: 合并后的配置段名（download / update）。
            website: 站点名。
            key: 配置键。
            default: 两层都未配置时的代码级兜底值；不传（哨兵）时抛 GetUnknownKey。

        Returns:
            解析后的配置值。

        Raises:
            GetUnknownKey: 两层均未配置且调用方未给 default 时。
        """
        site_root = (cls.config_dict.get(section) or {}).get("site") or {}
        site_conf = site_root.get(website) or {}
        if key in site_conf:
            value = site_conf[key]
        else:
            default_conf = site_root.get("default") or {}
            if key in default_conf:
                value = default_conf[key]
            elif default is not _UNSET:
                return default
            else:
                available = ", ".join(sorted(site_root)) or "无"
                raise GetUnknownKey(
                    f"配置键不存在: {section}.site.{website}.{key}（site 下现有: {available}）")
        if isinstance(value, str) and '${BASE_PATH}' in value:
            value = value.replace('${BASE_PATH}', str(cls.base_path))
        return value

    @classmethod
    def set(cls, dict_name, key, value):
        """更新单个配置键（内存 + 原子写盘）。

        Args:
            dict_name: 配置段名。
            key: 配置键（必须已存在，不允许新增键）。
            value: 新值。

        Raises:
            KeyError: 配置段不存在。
        """
        with cls._config_lock:
            if dict_name not in cls.config_dict:
                logger.error(f"配置字典不存在: {dict_name}")
                raise KeyError(f"配置字典不存在: {dict_name}")
            logger.debug(f"设置配置值: {dict_name}, {key}, {value}")
            cls.config_dict[dict_name][key] = value
            cls._save_config(dict_name)
    
    @classmethod
    def replace_section(cls, dict_name, data):
        """整体替换一个已存在的配置段并原子写盘（供系统管理 API 使用）。

        Args:
            dict_name: 配置段名（必须已加载）。
            data: 新的配置字典。

        Raises:
            KeyError: 配置段不存在。
            ValueError: data 不是键值映射。
        """
        with cls._config_lock:
            if dict_name not in cls.config_dict:
                raise KeyError(f"配置段不存在: {dict_name}")
            if not isinstance(data, dict):
                raise ValueError("配置段必须是键值映射")
            cls.config_dict[dict_name] = data
            cls._save_config(dict_name)

    @classmethod
    def _apply_env_overrides(cls):
        """环境变量覆盖配置：仅内存生效，不写回配置文件；
        load_all_configs 每次重载文件后重新应用，保证覆盖在热重载后依然有效"""
        for dict_name, config_data in cls.config_dict.items():
            for key in list(config_data.keys()):
                # 构建环境变量名：DICT_NAME_KEY (大写，下划线分隔)
                env_var_name = f"{dict_name.upper().replace('-', '_')}_{key.upper()}"
                env_value = os.environ.get(env_var_name)
                if env_value is None:
                    continue
                try:
                    # 尝试解析为 JSON（支持布尔值、数字等）
                    try:
                        parsed_value = json.loads(env_value)
                    except (json.JSONDecodeError, ValueError):
                        # 如果不是有效的 JSON，作为字符串处理
                        parsed_value = env_value

                    config_data[key] = parsed_value
                    logger.info(f"从环境变量加载配置: {env_var_name} = {parsed_value}")
                except Exception as e:
                    logger.warning(f"从环境变量加载配置失败 {env_var_name}: {e}")
    
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