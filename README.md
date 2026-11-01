# SpiderScheduler

> [!WARNING]
> **免责声明 / Disclaimer**
>
> 1. 本项目由 AI 辅助生成，**尚未经过实际使用校验**，可能存在未知缺陷，使用后果自负。
>    This project is AI-generated and **has not been validated in real-world use** — use it at
>    your own risk.
> 2. 尚未选定开源协议：**在协议确定之前，不允许使用、复制或分发本源码**。
>    No open-source license has been chosen yet: **using, copying, or distributing this source
>    code is not permitted until a license is selected**.

多站点、插件式的爬虫调度系统 / A multi-site, plugin-based crawler scheduling system.

> 框架负责调度、队列、状态管理与 Web 界面；具体怎么爬由用户脚本按 `website` 分发决定。
> The framework handles scheduling, queues, state and the web UI; scraping logic lives in
> user scripts dispatched by `website`.

| 文档 / Docs | 说明 / Description |
|---|---|
| [中文介绍](docs/README.zh-CN.md) | 项目简介、快速开始、功能总览 |
| [English README](docs/README.en.md) | Overview, quick start, feature tour |
| [使用手册（中文）](docs/user-guide.zh-CN.md) | 安装、四大功能页、API 参考、配置、常见问题 |
| [User Guide (EN)](docs/user-guide.en.md) | Install, the four tabs, API reference, config, FAQ |
| [开发手册（中文）](docs/dev-guide.zh-CN.md) | 架构、脚本契约、状态机、迁移、测试、扩展指南 |
| [Dev Guide (EN)](docs/dev-guide.en.md) | Architecture, script contract, state machines, migrations, testing |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构设计细节（中文，与代码同步）/ Architecture details (kept in sync with code) |

## 快速开始 / Quick Start

```bash
pip install -r requirements.txt
python main.py                    # 打开 http://127.0.0.1:8300
```

```bash
docker compose up -d --build      # 数据在命名卷 spider-data 的 /data
```

## 测试 / Tests

```bash
python3 -m pytest tests/
```
