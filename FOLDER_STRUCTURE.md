# SpiderScheduler 文件夹结构说明

## 项目整体结构

```
SpiderScheduler/
├── src/                          # 源代码目录
│   ├── __init__.py
│   ├── core/                     # 核心框架组件
│   ├── templates/                # 模板目录（快速开发模板）
│   ├── utils/                    # 工具类
│   └── api/                      # Web API接口
│   └── config/                   # 配置文件目录
├── tests/                        # 测试目录
├── docs/                         # 文档目录
├── old/                          # 旧代码备份目录
├── docker/                       # Docker挂载目录
│   ├── data/                     # 数据存储目录
│   ├── scripts/                  # 脚本目录
│   └── cookie/                   # cookies存储目录
├── requirements.txt
├── setup.py                      # 安装脚本
├── .gitignore
├── main.py                       # 主入口文件
└── FOLDER_STRUCTURE.md           # 本文件
```

## 详细目录说明

### src/ - 源代码目录
核心代码所在目录，包含所有业务逻辑。

#### src/core/ - 核心框架组件
```
src/core/
├── __init__.py
├── server.py            # Web服务器实现
├── register.py          # 用户注册和管理模块
├── updater.py           # 数据更新器
└── downloader.py        # 文件下载器
```

**说明：**
- `server.py`: 实现Web服务器，处理HTTP请求
- `register.py`: 管理用户注册、删除、优先级设置等功能
- `updater.py`: 负责数据更新和同步
- `downloader.py`: 处理文件下载任务

#### src/templates/ - 模板目录
```
src/templates/
├── __init__.py
├── base_updater.py      # 基础更新器模板
├── base_downloader.py   # 基础下载器模板
├── site_config.py       # 网站配置模板
├── example_site/        # 示例网站实现
│   ├── __init__.py
│   ├── updater.py       # 继承base_updater的实现
│   ├── downloader.py    # 继承base_downloader的实现
│   └── config.py        # 网站特定配置
└── quick_start.py       # 快速开发指南
```

**说明：**
- `base_updater.py`: 提供更新器的基类，包含通用方法
- `base_downloader.py`: 提供下载器的基类，包含通用方法
- `site_config.py`: 网站配置的模板类
- `example_site/`: 完整的示例实现，展示如何使用模板
- `quick_start.py`: 快速开发指南和代码生成器

#### src/utils/ - 工具类
```
src/utils/
├── __init__.py
├── database.py          # 数据库操作工具
├── browser_factory.py   # 浏览器工厂类
├── thread_pool.py       # 线程池管理
└── data_manager.py      # 数据管理器
```

**说明：**
- `database.py`: 数据库连接和操作封装
- `browser_factory.py`: 浏览器实例创建和管理
- `thread_pool.py`: 线程池实现，用于并发下载
- `data_manager.py`: 数据存储和读取管理

#### src/api/ - Web API接口
```
src/api/
├── __init__.py
├── routes.py            # API路由定义
├── models.py            # 数据模型
├── schemas.py           # 请求/响应模式
├── middleware.py        # 中间件
└── controllers.py       # 控制器
```

**说明：**
- `routes.py`: 定义API路由和端点
- `models.py`: 数据模型定义
- `schemas.py`: 请求和响应的数据结构
- `middleware.py`: 认证、日志等中间件
- `controllers.py`: 业务逻辑控制器

#### src/config/ - 配置文件目录
```
src/config/
├── __init__.py
├── settings.py          # 主配置文件
├── database.sql         # 数据库初始化脚本
└── logging.conf         # 日志配置文件
```

**说明：**
- `settings.py`: 应用程序的主要配置，包括数据库连接、下载路径等
- `database.sql`: 数据库表结构和初始化数据
- `logging.conf`: 日志配置，定义日志格式和输出位置

### docker/ - Docker挂载目录
```
docker/
├── data/                # 数据存储目录
│   ├── downloads/       # 下载文件存储
│   │   ├── site_name/   # 网站名称（如pixiv）
│   │   │   ├── users/
│   │   │   │   └── user_123/
│   │   │   │       ├── works/
│   │   │   │       └── metadata.json
│   │   │   └── works/
│   │   │       └── work_456/
│   │   │           ├── images/
│   │   │           └── metadata.json
│   │   └── other_site/ # 其他网站
│   ├── cache/          # 缓存文件
│   │   ├── user_cache.json
│   │   └── work_cache.json
│   └── logs/           # 日志文件
│       ├── spider.log
│       └── download.log
├── scripts/             # 脚本目录
│   ├── run_server.py        # 服务器启动脚本
│   ├── run_client.py        # 客户端脚本
│   ├── spidercmd.py         # 命令行工具
│   ├── docker/              # Docker相关脚本
│   │   ├── build.sh         # 构建镜像脚本
│   │   ├── run.sh           # 运行容器脚本
│   │   └── stop.sh          # 停止容器脚本
│   └── utils/               # 工具脚本
│       ├── backup.sh        # 数据备份脚本
│       └── cleanup.sh       # 清理脚本
└── cookie/              # cookies存储目录
    └── *.json           # 各网站cookies文件
```

**说明：**
- `data/`: 存储下载数据、缓存和日志，按网站分类
- `scripts/`: 各类运行、管理、备份脚本
- `cookie/`: 存放各网站的cookie文件，便于登录和身份验证
- **Docker挂载**: 整个docker目录挂载到容器，确保数据、脚本和cookie持久化

### tests/ - 测试目录
```
tests/
├── __init__.py
├── test_core/           # 核心模块测试
│   ├── __init__.py
│   ├── test_server.py
│   ├── test_register.py
│   ├── test_updater.py
│   └── test_downloader.py
├── test_templates/      # 模板测试
│   ├── __init__.py
│   ├── test_base_updater.py
│   ├── test_base_downloader.py
│   └── test_example_site/
└── test_utils/          # 工具类测试
    ├── __init__.py
    ├── test_database.py
    └── test_browser_factory.py
```

**说明：**
- `test_core/`: 测试核心框架功能
- `test_templates/`: 测试模板类和示例实现
- `test_utils/`: 测试工具类功能

### docs/ - 文档目录
```
docs/
├── README.md            # 项目说明文档
├── API.md              # Web API接口文档
├── TEMPLATE_GUIDE.md   # 模板开发指南
├── DOCKER_GUIDE.md     # Docker部署指南
└── DEPLOYMENT.md       # 部署指南
```

**说明：**
- `README.md`: 项目介绍和使用说明
- `API.md`: Web API接口文档
- `TEMPLATE_GUIDE.md`: 如何使用模板快速开发爬虫
- `DOCKER_GUIDE.md`: Docker容器化部署指南
- `DEPLOYMENT.md`: 部署和配置说明

### old/ - 旧代码备份目录
```
old/
├── component/           # 原组件目录
├── grpc_file/           # 原gRPC文件
├── server.py            # 原服务器文件
├── spidercmd.py         # 原命令行工具
└── run.py               # 原运行脚本
```

**说明：**
- 存放重构前的旧代码，作为备份和参考

## 文件命名规范

### Python文件
- 使用小写字母和下划线：`user_manager.py`
- 类名使用大驼峰：`UserManager`
- 函数和变量使用小写和下划线：`get_user_info()`

### 配置文件
- 使用小写字母和下划线：`database_config.py`
- 配置文件使用`.py`或`.json`格式

### 数据文件
- 下载文件按网站分类：`site_name/`（如pixiv、twitter等）
- 缓存文件使用描述性名称：`user_cache.json`
- 日志文件按功能分类：`spider.log`, `download.log`
- cookies文件按网站命名：`pixiv.json`, `twitter.json`

## 依赖管理

- `requirements.txt`: Python包依赖列表
- `setup.py`: 项目安装脚本
- `.gitignore`: Git忽略文件配置

## 开发建议

1. **模板化开发**: 使用预定义的模板快速开发新网站爬虫
2. **继承设计**: 通过继承基类，只需实现网站特定的逻辑
3. **配置分离**: 配置与代码分离，便于部署和调试
4. **日志记录**: 完善的日志系统，便于问题排查
5. **快速迭代**: 模板提供通用功能，专注于网站特定逻辑

## Docker部署结构

Docker容器化部署的目录结构：
```
SpiderScheduler/
├── Dockerfile           # Docker镜像构建文件
├── docker-compose.yml   # Docker Compose配置
├── .dockerignore        # Docker忽略文件
├── src/                 # 源代码（容器内）
├── config/              # 配置文件（容器内）
├── docker/              # 宿主机挂载目录（数据、脚本、cookie）
│   ├── data/
│   ├── scripts/
│   └── cookie/
└── logs/                # 日志目录（可选单独挂载）
```

**Docker挂载说明：**
- `docker/data/`: 挂载到容器内的 `/app/docker/data`
- `docker/scripts/`: 挂载到容器内的 `/app/docker/scripts`
- `docker/cookie/`: 挂载到容器内的 `/app/docker/cookie`
- `logs/`: 可选单独挂载到 `/app/logs`，也可放在`docker/data/logs/`下 