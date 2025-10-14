# SpiderScheduler 后端架构设计

## 项目概述

SpiderScheduler 是一个基于用户脚本注入的爬虫调度系统，支持REST API接口，为前端提供完整的后端服务。

## 核心设计理念

- **用户脚本核心**：框架围绕用户编写的脚本设计，支持动态加载
- **REST API优先**：提供完整的REST API接口供前端调用
- **服务化架构**：清晰的职责分离，每个服务专注特定功能
- **配置驱动**：通过配置文件控制系统行为
- **单网站专注**：每个项目实例只处理一个网站

## 项目结构

```
SpiderScheduler/                      # 后端项目根目录
├── src/                              # 源代码目录
│   ├── core/                         # 核心业务层
│   │   ├── __init__.py
│   │   └── backendManager.py         # 后端管理器（主协调器）
│   │
│   ├── api/                          # API层
│   │   ├── __init__.py
│   │   ├── server.py                 # Web服务器（Flask）
│   │   ├── routes/                   # 路由模块
│   │   │   ├── __init__.py
│   │   │   ├── user_routes.py        # 用户管理API
│   │   │   ├── task_routes.py        # 任务管理API
│   │   │   ├── system_routes.py      # 系统管理API
│   │   │   └── download_routes.py    # 下载管理API
│   │   ├── middleware/               # 中间件
│   │   │   ├── __init__.py
│   │   │   ├── cors.py               # CORS中间件
│   │   │   ├── logging.py            # 日志中间件
│   │   │   └── error_handler.py      # 错误处理中间件
│   │   └── schemas/                  # API数据模式
│   │       ├── __init__.py
│   │       ├── user_schemas.py       # 用户相关模式
│   │       ├── task_schemas.py       # 任务相关模式
│   │       └── response_schemas.py   # 响应模式
│   │
│   ├── services/                     # 业务服务层
│   │   ├── __init__.py
│   │   ├── download_service.py       # 下载服务（包含队列处理）
│   │   ├── update_service.py         # 更新服务（包含定时调度）
│   │   ├── user_service.py           # 用户服务
│   │   └── script_service.py         # 脚本服务（动态加载管理）
│   │
│   ├── utils/                        # 工具和基础设施层
│   │   ├── __init__.py
│   │   ├── database/                 # 数据库相关
│   │   │   ├── __init__.py
│   │   │   ├── database.py           # 数据库管理
│   │   │   └── init.sql              # 数据库初始化脚本
│   │   ├── logging/                  # 日志系统
│   │   │   ├── __init__.py
│   │   │   └── logger.py             # 日志管理
│   │   ├── storage/                  # 存储相关
│   │   │   └── file_manager.py       # 文件管理
│   │   ├── dynamic_loader.py         # 动态加载器
│   │   ├── BlockingThreadPoolExecutor.py  # 线程池
│   │   ├── browser_factory.py        # 浏览器工厂
│   │   └── exceptions.py             # 异常定义
│   │
│   ├── initer/                       # 初始化模块
│   │   ├── __init__.py
│   │   ├── init_backend.py           # 后端初始化
│   │   ├── init_config.py            # 配置初始化
│   │   ├── init_database.py          # 数据库初始化
│   │   └── init_file_structure.py    # 文件结构初始化
│   │
│   └── configs/                      # 配置相关
│       ├── __init__.py
│       ├── config.py                 # 配置管理
│       └── globalVars.py             # 全局变量
│
├── scripts/                          # 用户脚本目录
│   ├── download_a_work.py            # 用户编写的下载脚本
│   ├── update_a_user.py              # 用户编写的更新脚本
│   └── site_config.py                # 网站特定配置（可选）
│
├── assets/                           # 项目模板目录
│   ├── confs/                        # 配置文件模板
│   │   ├── download_setting.json
│   │   ├── global_conf.json
│   │   ├── network.json
│   │   ├── path.json
│   │   └── update_setting.json
│   ├── datas/                        # 数据目录模板
│   │   ├── log/
│   │   └── spider.db
│   ├── download/                     # 下载目录模板
│   ├── download_cache/               # 缓存目录模板
│   └── scripts/                      # 脚本目录模板
│       ├── download_a_work.py
│       └── update_a_user.py
│
├── tests/                            # 测试目录
│   ├── __init__.py
│   ├── run_tests.py
│   └── utils/
│       └── test_logger.py
│
├── requirements.txt                  # Python依赖
├── main.py                           # 主入口文件
└── FOLDER_STRUCTURE.md               # 项目结构说明
```

## 核心组件说明

### 1. BackendManager (核心协调器)
- **位置**: `src/core/backendManager.py`
- **职责**: 协调所有服务，提供统一的后端管理接口
- **功能**: 
  - 初始化各个服务
  - 启动定时任务
  - 提供用户管理接口
  - 管理服务生命周期

### 2. API层
- **位置**: `src/api/`
- **职责**: 提供REST API接口供前端调用
- **组件**:
  - `server.py`: Flask Web服务器
  - `routes/`: 各种API路由
  - `middleware/`: 中间件（CORS、日志、错误处理）
  - `schemas/`: 数据验证模式

### 3. 业务服务层
- **位置**: `src/services/`
- **职责**: 实现具体的业务逻辑
- **服务**:
  - `download_service.py`: 下载服务（包含队列处理）
  - `update_service.py`: 更新服务（包含定时调度）
  - `user_service.py`: 用户管理服务
  - `script_service.py`: 脚本管理服务

### 4. 工具和基础设施层
- **位置**: `src/utils/`
- **职责**: 提供工具函数和基础服务支持
- **组件**:
  - `database/`: 数据库操作
  - `logging/`: 日志系统
  - `storage/`: 文件存储
  - `dynamic_loader.py`: 动态加载器
  - `BlockingThreadPoolExecutor.py`: 线程池
  - `browser_factory.py`: 浏览器工厂
  - `exceptions.py`: 异常定义

### 5. 配置管理
- **位置**: `src/configs/`
- **职责**: 配置管理和全局变量
- **组件**:
  - `config.py`: 配置管理器
  - `globalVars.py`: 全局变量定义

## API接口设计

### 用户管理
- `GET /api/users/` - 获取所有用户
- `POST /api/users/` - 创建用户
- `DELETE /api/users/{user_id}` - 删除用户

### 任务管理
- `POST /api/tasks/update` - 启动更新任务
- `POST /api/tasks/download` - 启动下载任务
- `GET /api/tasks/status` - 获取任务状态

### 系统管理
- `GET /api/system/status` - 获取系统状态
- `GET /api/system/config` - 获取系统配置
- `PUT /api/system/config` - 更新系统配置

### 下载管理
- `GET /api/downloads/queue` - 获取下载队列
- `GET /api/downloads/history` - 获取下载历史

## 数据流架构

```
用户脚本 (scripts/)
    ↓
ScriptService (动态加载)
    ↓
BackendManager (协调)
    ↓
├── UpdateService (定时更新)
│   └── 使用 UpdateUser 脚本
└── DownloadService (下载队列)
    └── 使用 DownloadWork 脚本
    ↓
REST API (Flask)
    ↓
前端应用
```

## 初始化流程

```
main.py
    ↓
init_backend()
    ↓
├── init_files() (文件结构)
├── init_config() (配置系统)
├── logger.init_log() (日志系统)
├── db_manager.init_database() (数据库)
└── BackendManager() (后端服务)
    └── 启动定时任务
    └── 启动API服务器
```

## 用户脚本接口

### 下载脚本接口
```python
# scripts/download_a_work.py
class DownloadWork:
    def __init__(self, work_id: str):
        self.work_id = work_id
        
    def download_it(self, path: str = None) -> dict:
        """用户实现具体的下载逻辑"""
        # 用户在这里编写具体的下载代码
        pass
```

### 更新脚本接口
```python
# scripts/update_a_user.py
class UpdateUser:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.page = 1
        self.works = []
        
    def get_one_page(self):
        """用户实现获取一页数据的逻辑"""
        # 用户在这里编写具体的数据获取代码
        pass
        
    def __iter__(self):
        return self
        
    def __next__(self):
        # 用户在这里实现迭代逻辑
        pass
```

## 配置系统

### 配置文件位置
- `assets/confs/global_conf.json` - 全局配置模板
- `assets/confs/path.json` - 路径配置模板
- `assets/confs/download_setting.json` - 下载配置模板
- `assets/confs/update_setting.json` - 更新配置模板
- `assets/confs/network.json` - 网络配置模板

**注意**: 实际运行时，这些配置文件会被复制到用户指定的工作目录（如 `docker/` 目录）

### 配置管理
- 支持热重载
- 配置验证
- 默认值处理

## 技术栈

### 后端技术
- **语言**: Python 3.8+
- **Web框架**: Flask
- **数据库**: SQLite
- **任务队列**: 自定义线程池
- **动态加载**: importlib
- **浏览器自动化**: Selenium

### 依赖管理
- `requirements.txt` - Python包依赖
- 支持虚拟环境

## 部署说明

### 开发环境
- 后端运行在 `http://localhost:5000`
- 前端运行在 `http://localhost:3000`
- 支持CORS跨域请求

### 生产环境
- 后端可部署到服务器
- 前端构建后部署到CDN
- 支持Docker容器化部署

## 扩展性

### 添加新网站
1. 在 `scripts/` 目录下编写新的下载和更新脚本
2. 实现对应的接口
3. 配置网站特定参数

### 添加新功能
1. 在 `services/` 目录下添加新服务
2. 在 `api/routes/` 目录下添加新路由
3. 更新 `BackendManager` 集成新服务

## 注意事项

1. **用户脚本是核心**：框架只提供基础设施，具体逻辑由用户脚本实现
2. **单网站专注**：每个项目实例只处理一个网站
3. **配置驱动**：通过配置文件控制系统行为
4. **REST API优先**：所有功能都通过API接口暴露
5. **前后端分离**：前端项目独立开发，通过API与后端通信
