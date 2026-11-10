# SpiderScheduler

多站点、插件式的爬虫调度系统。框架负责调度、下载队列、状态管理、登录 cookie 和 Web 界面；
具体怎么爬由**用户脚本**按 `website` 分发决定——框架本身与任何站点无关。

## 核心概念

- **发布位点（publish_pos）**：对某站点某作者的追踪位置。更新器以位点为单位遍历作者的作品流，
  新作品自动进入下载队列。
- **作品（works）**：下载队列的基本单位，每条作品可携带自己的统一下载参数（`downloadInfo`）。
- **用户脚本**：`UpdateUser`（翻页抓取某作者的作品列表）与 `DownloadWork`（下载单个作品）两类，
  放在工作目录 `scripts/` 下，可在线上传、热重载、声明自己的 pip 依赖。
- **站点隔离**：每个站点有独立的下载调度线程（线程池/间隔/限量/缓存/路径都可按站点配置）。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 启动（默认工作目录 ./docker，端口 8300）
python main.py
# 浏览器打开 http://127.0.0.1:8300
```

首次启动会自动在工作目录里生成配置模板和空数据库。

Docker 部署：

```bash
docker compose up -d --build     # 数据在命名卷 spider-data 的 /data 下
```

## 四个功能页

| 页面 | 能做什么 |
|---|---|
| 作品 | 组合筛选（站点/状态多选/作者/日期区间/关键字/排序/分页）；顶部站点×状态统计条可点选；行内停止/重新入队 |
| 位点 | 添加追踪位点（作者 ID + 站点下拉）；按站点筛选；行内停止/恢复追踪；每位点的作品数 |
| Cookie | 查看各站点 cookie 状态；**去登录**——在代理出的目标站登录页里真实登录，cookie 自动捕获落盘；删除 |
| 系统 | 查看脚本路由；热重载脚本；上传/查看脚本（自动装依赖）；在线编辑任意配置段（YAML） |

## 脚本插件

```python
# scripts/download_a_work.py
class DownloadWork:
    website = "pixiv"            # 声明适用的站点；不声明则作为单站兜底

    def __init__(self, work_info, download_path, download_info=None):
        # download_path：本任务专属目录（缓存开=缓存工作目录，关=最终目录），写这里即可
        ...

    def download_it(self):
        ...                       # 把数据写进 download_path，返回产物路径
```

脚本头部可用 `# requirements: 包名` 声明依赖，框架在加载前自动安装缺失的包。
完整的脚本契约、状态机与配置说明见 [使用手册](user-guide.zh-CN.md) 与 [开发手册](dev-guide.zh-CN.md)。

## 目录结构

```
SpiderScheduler/
├── main.py            # 入口（--repl 命令行、--basepath 工作目录）
├── src/               # 调度器、API、前端、基础设施
├── tests/             # pytest 测试（124 例）
├── docker/            # 默认工作目录（运行数据，不入库）
├── docs/              # 本文档目录
├── Dockerfile / docker-compose.yml / .dockerignore
└── ARCHITECTURE.md    # 架构设计细节（与代码同步）
```

## 文档

- [使用手册](user-guide.zh-CN.md)：安装运行、四个功能页逐项说明、REST API 参考、配置详解、常见问题。
- [开发手册](dev-guide.zh-CN.md)：架构分层、脚本契约、状态机、数据库与迁移机制、测试、二次开发指南。
- [ARCHITECTURE.md](../ARCHITECTURE.md)：与代码保持同步的架构设计文档。
