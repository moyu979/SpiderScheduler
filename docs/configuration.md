# SpiderScheduler 配置文档

## 概述

SpiderScheduler 使用模块化的配置管理系统，所有配置项都通过 `src/utils/config.py` 进行管理。配置系统支持自动验证、持久化存储和热重载功能。

## 配置管理

### 初始化配置
```python
from src.utils.config import init_config

# 初始化配置系统
init_config()
```

### 获取配置
```python
from src.utils.config import get_path, get_download_setting, get_update_setting, get_proxy, get_browser, get_global_conf

# 获取路径配置
db_path = get_path('DB_FILE')

# 获取下载设置
thread_count = get_download_setting('download_thread')

# 获取更新设置
check_interval = get_update_setting('check_interval')

# 获取代理设置
use_proxy = get_proxy('use_proxy')

# 获取浏览器设置
domain = get_browser('domain')

# 获取全局配置
is_running = get_global_conf('run')
```

### 设置配置
```python
from src.utils.config import set_download_setting, set_proxy

# 设置下载线程数
set_download_setting('download_thread', 4)

# 设置代理
set_proxy('use_proxy', True)
```

### 重载配置
```python
from src.utils.config import reload_config

# 手动重载配置
reload_config()
```

## 配置项详解

### 1. 全局配置 (global_conf)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| run | bool | False | 系统运行状态 |

### 2. 路径配置 (path)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| DB_FILE | string | "docker/data/spider.db" | 数据库文件路径 |
| CONFIG_PATH | string | "docker/config" | 配置文件目录路径 |
| LOG_PATH | string | "docker/logs" | 日志目录路径 |

### 3. 下载设置 (download_setting)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| download_thread | int | 1 | 下载线程数（正整数） |
| once_download | int | -1 | 一次下载数量（-1为不限） |
| waiting_play | bool | False | 是否在下载间插入长睡眠模拟正常播放 |
| sleep_second | int | 10 | 下载间隔秒数（非负整数） |
| download_vip | bool | False | 是否下载VIP内容 |
| use_cache | bool | True | 是否使用缓存 |
| CACHE_PATH | string | "./docker/data/cache" | 缓存目录路径 |
| DOWNLOAD_PATH | string | "./docker/data/download" | 下载目录路径 |

### 4. 更新设置 (update_setting)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| update_thread | int | 1 | 更新线程数（正整数） |
| check_interval | int | 86400 | 检查更新频率秒数（-1为不检查） |

### 5. 代理设置 (proxy)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| use_proxy | bool | False | 是否使用代理 |
| proxy_ip | string | "127.0.0.1" | 代理服务器IP地址 |
| proxy_port | string | "7897" | 代理服务器端口（1-65535） |

### 6. 浏览器设置 (browser)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| BROWSER_TYPE | string | "chrome" | 浏览器类型 |
| BROWSER_PATH | string | "" | 浏览器可执行文件路径 |
| DOMAIN | string | "https://www.example.com" | 目标网站域名 |
| HEADLESS | bool | True | 是否使用无头模式 |
| USE_PROXY | bool | False | 是否使用代理 |
| USE_COOKIE | bool | False | 是否使用cookie |

## 配置验证规则

### 数值类型验证
- **线程数** (`download_thread`, `update_thread`): 必须是正整数
- **下载数量** (`once_download`): 必须是大于等于-1的整数
- **时间间隔** (`sleep_second`, `check_interval`): 必须是非负整数
- **端口号** (`proxy_port`): 必须是1-65535之间的字符串

### 布尔类型验证
- **开关选项** (`waiting_play`, `download_vip`, `use_cache`, `use_proxy`, `use_cookie`): 必须是布尔值

### 路径保护
- 所有以 `FILE` 或 `PATH` 结尾的配置项都是受保护的，不能通过 set 方法修改
- 尝试修改这些配置项会抛出 `ChangeConst` 异常

## 异常处理

### ChangeConst 异常
当尝试修改以 `FILE` 或 `PATH` 结尾的配置项时抛出：
```python
try:
    set_path('DB_FILE', 'new_path.db')
except ChangeConst as e:
    print(f"错误: {e}")
```

### SetUnknownKey 异常
当尝试获取或设置不存在的配置项时抛出：
```python
try:
    value = get_download_setting('non_existent_key')
except SetUnknownKey as e:
    print(f"错误: {e}")
```

### ValueError 异常
当配置值类型或范围不正确时抛出：
```python
try:
    set_download_setting('download_thread', -1)
except ValueError as e:
    print(f"错误: {e}")
```

## 配置文件结构

配置系统会在 `docker/config/` 目录下创建以下JSON文件：

```
docker/config/
├── global_conf.json      # 全局配置
├── path.json            # 路径配置
├── download_setting.json # 下载设置
├── update_setting.json  # 更新设置
├── proxy.json           # 代理设置
└── browser.json         # 浏览器设置
```

## 自动功能

### 文件夹创建
系统会自动检查并创建以下目录：
- `docker/data/` - 数据目录
- `docker/config/` - 配置目录
- `docker/logs/` - 日志目录
- `docker/data/cache/` - 缓存目录
- `docker/data/download/` - 下载目录
- `docker/resource/` - 资源目录

### 守护线程
系统会启动一个守护线程，每5分钟自动重载配置文件，确保配置变更能够及时生效。

### 配置持久化
所有通过 set 方法修改的配置都会自动保存到对应的JSON文件中。

## 最佳实践

1. **初始化**: 在应用启动时调用 `init_config()`
2. **配置验证**: 在修改配置前检查值的有效性
3. **异常处理**: 使用 try-catch 处理配置相关的异常
4. **路径保护**: 不要尝试修改以 `FILE` 或 `PATH` 结尾的配置项
5. **热重载**: 在需要时使用 `reload_config()` 手动重载配置
