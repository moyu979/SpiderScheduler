# SpiderScheduler 后端架构设计

## 项目概述

SpiderScheduler 是一个**多站点、插件式**的爬虫调度系统：框架负责调度、队列、状态管理、REST API 和 REPL，
具体的抓取/下载逻辑由用户脚本提供，按 `website` 标识分发。每个部署实例通过 `BASEPATH`（默认 `./docker`）
拥有独立的工作目录、配置和数据库。

## 目录结构（与代码一致）

```
SpiderScheduler/
├── main.py                          # 入口：init() + 阻塞；--repl 进入命令行；--basepath 指定工作目录
├── requirements.txt
├── src/
│   ├── core/initialization.py       # 统一初始化：文件 → 配置 → 日志 → 数据库 → REST API → Updater → Downloader
│   ├── config/
│   │   ├── config.py                # ConfigManager：加载/热重载/env 覆盖/原子写回
│   │   └── paths.py                 # BASEPATH 下的各类路径
│   ├── server/
│   │   ├── rest_api.py              # Flask 服务（werkzeug make_server，后台线程，可优雅停止；托管前端页）
│   │   ├── apis/                    # download / update / query / cookie / script / config / website（7 个蓝图）
│   │   └── web/index.html           # 前端单页应用（vanilla JS，无构建依赖，/ 路由直接托管）
│   ├── service/
│   │   ├── updater.py               # 更新调度：巡检守护 + 每站点独立调度线程，位点 → UpdateUser 脚本 → 写 Works/Upload
│   │   ├── downloader.py            # 下载调度：作品队列认领 → DownloadWork 脚本 → 状态回写
│   │   └── dispatcher.py            # ScriptDispatcher：按 website 把任务路由到脚本类
│   ├── cli/repl.py                  # 内置命令行（add-pos 等）
│   ├── utils/
│   │   ├── dynamic_loader.py        # importlib 动态加载
│   │   ├── threadPool/threadPool.py # 阻塞式线程池（信号量限流 + 统计）
│   │   ├── database/
│   │   │   ├── database.py          # DatabaseManager：引擎/会话/PRAGMA/schema 迁移
│   │   │   ├── models.py            # PublishPos / Works / Upload（复合主键 + 延迟复合外键）
│   │   │   └── migrations/          # 结构迁移脚本（000N_说明.py）
│   │   ├── cookie_manager.py        # CookieManager：按 website 存取登录 cookie（datas/cookies/）
│   │   └── logging/logger.py        # SpiderLogger：按月轮转文件 + 控制台
│   └── assets/                      # 模板：confs/（yaml 配置）、scripts/（用户脚本骨架）
├── docker/                          # BASEPATH 工作目录（运行时从 assets 生成，已被 .gitignore 忽略）
│   ├── confs/  scripts/  datas/
└── tests/                           # pytest：models / dispatcher / config / queue / migrations 等
```

## 数据模型

三张表，全部以 `website` 入键（multiWeb 设计核心）：

> 命名说明：原 `user` 表已更名为 `publish_pos`（发布位点）——它的语义不是"我们的账号"，
> 而是"对某站点某作者的追踪位点"；`userId` 列统一更名为 `authorId`（含 upload 表）。
> 该变更由迁移 `0002_rename_user_to_publish_pos.py` 完成（schema v1 → v2）。

```
publish_pos（发布位点）       works                          upload
  authorId ─┐(PK)              workNumber ─┐(PK)              website  (PK)
  website ──┘(PK)             website ────┘(PK)              authorId (PK, FK→publish_pos)
  addTime                     upTime/title/kind              workNumber(PK, FK→works)
  state                       state                          （多对多关联表）
                              downloadDate
                              downloadPriority
                              otherInfo / downloadInfo
```

### 状态机（管线语义，代码与 API 共同遵守）

- `publish_pos.state`: `inQueue`（参与更新）/ `stopped`（Updater 跳过）。由 REPL / `stop_pos` API 设置。
- `works.state`（下载管线）:
  `inQueue（或 NULL，兼容旧数据） → downloading → done / failed`；
  `stopped` 可随时由 `stop_work` API 置入：调度跳过、完成回调不覆盖。
  下载中断残留的 `downloading` 会在下一轮开始时自动重置回 `inQueue`。
  站点暂无可用下载脚本（`ScriptRouteError`）时不标 `failed`，置 `noDownloader`
  挂起；下载脚本上传/重载或服务启动后，站点已就位脚本的挂起作品自动刷回 `inQueue`。
- 源站自身的作品状态不入 `state`，由更新器存进 `otherInfo` 的 `siteState` 键（JSON）。
- `works.downloadInfo`：该作品的统一下载参数（JSON 文本）。`add_work` API 可直接传 JSON 对象入库；
  下载时反序列化为 dict，作为 `download_info` 参数交给脚本。站点差异尽量收拢在数据里而不是代码分支。

### 外键

`upload` → `publish_pos`、`works` 均为**复合外键**（完整覆盖父表联合主键），且 `DEFERRABLE INITIALLY DEFERRED`：
两条外键共享 `website` 列，ORM 同批次 flush 时无法保证父表先插入，延迟到 commit 检查后
插入顺序不再敏感，孤儿数据依然会被拒绝（需连接级 `PRAGMA foreign_keys=ON`，见下）。

## 用户脚本契约与分发

脚本放在 `BASEPATH/scripts/`，由框架动态加载。**website 路由约定**：

- 多文件分发：`scripts/download/`、`scripts/update/` 目录下**每站点一个文件**
  （如 `pixiv.py`），路由跨文件合并——同一站点重复声明时先加载的生效并告警；
  无 website 声明的文件可作为兜底（至多一个，传统单文件优先）。来源列表每次
  load 重新求值：旧的单文件（`download_a_work.py` 等）保持兼容且优先级最高，
  新上传的文件在**重新扫描后立即生效**；
- 依赖自描述：脚本头部可写 `# requirements: 包名[版本约束]`（可多行、逗号分隔），
  框架在每次加载前检测缺失并自动 `pip install` 到当前环境，之后才执行脚本顶部的
  import；安装失败仅记录日志，不阻断加载（导入错误会自然暴露）；
- 脚本内任意公共类声明 `website = "pixiv"`（或站点列表 `["a", "b"]`）即注册到对应站点；
  一个文件可以放多个站点的类，类名不限。
- 文件内**没有任何类声明 website** 时，视为传统单站点脚本：回退到约定的类名
  （`DownloadWork` / `UpdateUser`），对任意 website 生效——旧脚本无需改动即可继续工作。
- 路由失败（无匹配且无兜底）抛 `ScriptRouteError`，错误信息列出可用站点；下载任务据此
  置 `noDownloader` 挂起（不标 `failed`），上传/重载下载脚本成功后自动刷回 `inQueue`。

### 更新脚本（每用户一个实例，迭代器协议）

```python
class UpdateUser:            # 或多个类各自声明 website
    website = "pixiv"        # 不声明则整体兜底

    def __init__(self, usr: dict, logging): ...   # usr 含 authorId/website/addTime（发布位点信息）
    def get_one_page(self): ...                   # 抓一页，填充 self.works
    def __iter__(self): ...   # 重置
    def __next__(self): ...   # 逐条产出 dict：workid/workNumber、upTime、title、
                              # kind、state（→ 源站状态，存 otherInfo.siteState）、
                              # downloadDate、downloadPriority
```

更新器逐条入库：新作品写 `works`（state=inQueue），`upload` 建关联；`upload` 重复即认为
该用户已同步到历史点，停止本用户迭代。

### 下载脚本（每作品一个实例）

```python
class DownloadWork:
    website = "pixiv"

    def __init__(self, work_info: dict, download_path: str, download_info: dict | None): ...
    def download_it(self) -> str | dict: ...  # 下载入口；把数据写入 download_path；
        # 返回产物路径（str，或 {path, duration?}）；失败抛异常；
        # duration（秒）供 waiting_play 使用
```

实例化后框架会注入 `logger`、`config_manager`、`cookie_manager` 属性。登录 cookie 按 website 取用：
`cookie_manager.get(website)` 返回 cookie 列表（Selenium 兼容格式，可逐条 add_cookie），
`cookie_manager.get_header(website)` 返回可直接用于 requests 的 Cookie 头字符串；
未登录时抛 `CookieNotFoundError`。UpdateUser 实例同样被注入 `cookie_manager`。

### 登录 cookie 的获取（登录代理）

cookie 不存在时，用户在前端 Cookie 页点"去登录"：后端把 `websites.yaml` 中该站点的登录页
**原样代理**给前端（iframe），用户真实登录——代理把整个过程的 Set-Cookie 收进后端会话，
不依赖浏览器存 cookie；点"完成并保存"落盘为 `datas/cookies/<website>.json`。
细节见 `src/server/apis/cookie_api.py`（同源 HTML 改写、404 救援、重登刷新）。

## 调度循环

**Updater（每站点独立调度，与 Downloader 对称）**：守护线程周期性发现有未停止位点的
站点，为每个站点启动独立调度线程——各自的线程池（`update_thread`）、轮间隔
（`update_interval`，±10% 抖动，-1 持续更新）、位点间错峰（`commit_interval`）与站点开关
（`do_update`）。查更新本身也是爬目标站页面，因此按站点限流；站点级配置写在
`update.yaml` 的 `site` 结构（解析顺序 site.<website> > site.default > 代码内置兜底）；根键 `do_update` 是总开关。

**Downloader（每站点独立调度）**：守护线程周期性发现有待下载作品的站点，为每个站点
启动独立调度线程——各自独立的线程池（`download_thread`）、轮间隔（`download_interval`，-1
持续下载）、数量限制（`once_download_number`）、缓存与路径。站点循环内：回收中断残留 →
按优先级认领本站任务（`state ∈ {inQueue, NULL}`）→ 认领即置 `downloading`，交线程池执行 →
成功置 `done` 记录 `downloadDate`，异常置 `failed`（不覆盖 `stopped`），站点无下载脚本置
`noDownloader` 挂起 → 轮末等任务收尾。
站点级配置写在 `download.yaml` 的 `site` 结构（解析顺序 site.<website> > site.default > 代码内置兜底），支持运行中热更新
（线程数除外，改动后重启进程或站点线程重建时生效）；全局 `do_download` 是总开关，
站点级 `do_download: false` 可单独关站，开关恢复后守护线程自动重新拉起。
每站点还可配 **可下载时间窗口** `download_window`（mode: daily/weekly/monthly，start/end
HH:MM 支持跨天，weekdays: 1=周一..7=周日，month_days 支持负数 -1=当月最后一天）：窗口外
站点循环按 60s 周期静默等待（状态切换才打日志），窗口开启后立即调度；未配置或配置非法
一律放行（fail-open）。配合 `once_download_number: -1` 与 `download_interval: -1` 可实现
窗口内全速突击消耗代理流量。

**下载路径包装**（脚本拿站点级下载根，作品子目录由脚本自建）：脚本接收站点级
下载根 `<路径根>/<website>/`（路径根只配到 cache/download 这一层，`<website>`
由框架按 site 拼）+ downloadInfo，在其下自建作品子目录（建议 workNumber 过滤
文件系统不安全字符命名），`download_it` 返回产物路径（相对该根或绝对路径均可）。
交付：`use_cache` 开且 `cache_path` ≠ `download_path` 时，框架按相对层级把产物
搬到 `download_path/<website>/` 下并清理该作品在缓存侧的残留（缺产物路径、返回
站点根本身或指向缓存根之外均视为失败）；两层一致或 `use_cache` 关时无需搬运，
产物原地保留。

两个服务都有 `stop()`：置停止事件（所有 sleep 均为可唤醒的 `Event.wait`）+ 线程池
`shutdown(wait=True, cancel_futures=True)`，Ctrl+C 时由 main 的信号处理依次调用。

## 配置系统

- 配置在 `BASEPATH/confs/`，YAML 优先（同名 yaml > yml > json）。模板来自 `src/assets/confs/`，
  `init_files()` 只补缺失文件，不覆盖已有配置。
- `ConfigManager`：内存字典 + RLock；`set()` 内存与文件同时更新（临时文件原子替换）；
  守护线程按 `conf_reload_interval` 定期重载文件。
- **环境变量覆盖**：`字典名_键名`（大写）命中即覆盖内存值，仅内存生效、不回写文件；
  每次文件重载后重新应用，保证热重载不丢覆盖。
- 字符串值中的 `${BASE_PATH}` 占位符在 `get()` 返回时替换为实际工作目录；
  `system.yaml` 的 `database_url` 由 DatabaseManager 解析（`${DB_PATH}` 占位）。

关键键位（代码与 yaml 已对齐）：

| 文件 | 键 | 用途 |
|---|---|---|
| download（根键） | do_download | 下载总开关（站点级开关的父开关） |
| | site_scan_interval / window_check_interval | 站点巡检周期 / 窗口外检查周期（秒） |
| download（site.default） | download_thread / once_download_number / download_interval | 线程数 / 每轮数量限制（-1 无限）/ 轮间隔（-1 持续下载） |
| | waiting_play / sleep_second | 任务间节奏 |
| | use_cache / download_path / cache_path | 缓存开关与存储路径（支持 ${BASE_PATH}） |
| （download.site） | `download_window` | 每站点可下载时间窗口（daily/weekly/monthly + start/end/weekdays/month_days） |
| （download.site） | `<website>: {键覆盖}` | 每站点独立下载配置（未写键回落 site.default） |
| update（根键） | do_update | 更新总开关 |
| update（site.default） | update_thread / update_interval / commit_interval | 线程数 / 轮间隔 / 位点间错峰 |
| （update.site） | `<website>: {键覆盖}` | 每站点独立更新配置（含站点级 do_update 开关） |
| websites | `<website>: 入口URL` | 各站点域名（登录代理目标、脚本可参考） |
| system | debug / conf_reload_interval / conf_retry_interval / console_log_level / file_log_level / database_* / rest_api_* / use_proxy / proxy_* | 运行 / 日志 / 数据库 / 网络（原 global_conf+logging+database+network 合并） |

## 数据库

- SQLAlchemy 2.0 + SQLite（`system.yaml` 的 `database_url` 支持填完整连接串换 Postgres 等，
  `${DB_PATH}` 占位符代表默认 SQLite 文件路径。**schema 迁移仅支持 SQLite**——配置远程库时
  跳过迁移并告警，需自行保证结构与当前模型一致）。
- 连接级 PRAGMA：`journal_mode=WAL`（读写互斥降低）、`busy_timeout=30000`（并发写退避）、
  `foreign_keys=ON`（外键强制）。`database_echo`、`database_connect_args` 由 system.yaml 配置。
- 会话统一走 `DatabaseManager.get_db_session()` 上下文管理器（自动提交/回滚/关闭）。
  **注意：ORM 对象在会话提交后即过期，跨会话使用需在会话内转字典。**

### Schema 迁移

`schema_version` 表记录当前版本。约定：

1. 修改 `models.py` 后，新建 `migrations/000N_说明.py`，提供 `apply(engine)`（幂等）；
2. `database.py` 的 `HEAD_SCHEMA_VERSION` +1。
全新库由 `create_all` 直接建出最新结构并记为最新版本；旧库按版本号补跑迁移。

## REST API

| 端点 | 说明 |
|---|---|
| POST /api/update/add_pos | 添加发布位点（authorId + website，默认 pixiv） |
| POST /api/update/stop_pos | 停止追踪位点（state→stopped） |
| POST /api/download/add_work | 作品入队（可带 downloadInfo 对象） |
| POST /api/download/stop_work | 停止下载（state→stopped） |
| POST /api/download/requeue_work | 重新入队（failed/stopped/done → inQueue） |
| POST /api/update/resume_pos | 恢复追踪位点（stopped → 追踪中） |
| POST /api/update/update_now · GET /api/update/update_now/status | 立即对指定位点跑一轮更新（绕过周期调度）· 查询立即更新进度 |
| PUT /api/{update,download}/config | 更新对应配置段 |
| GET /api/query/works | 组合筛选作品：website/state 多选(none=NULL)/author/日期区间(upTime、downloadDate)/keyword/排序(白名单)/分页 |
| GET /api/query/positions | 组合筛选位点：website/state/keyword/addTime 区间/分页，附每个位点的作品关联数 |
| GET /api/query/stats | 按 website × state 计数，供前端生成筛选选项与概览条 |
| GET /api/cookie/status | 各站点 cookie 存储状态（前端 Cookie 页数据源） |
| GET /api/cookie/<w>/login_page | 登录包装页（顶栏 + 代理 iframe） |
| ANY /api/cookie/<w>/proxy/[path] | 登录代理：转发到目标站，捕获 Set-Cookie，HTML 同源改写 |
| POST /api/cookie/<w>/save | 登录完成，会话 cookie 落盘 |
| POST /api/cookie/<w>/cancel · DELETE /api/cookie/<w> | 放弃登录会话 · 删除已存 cookie |
| GET /api/system/scripts · POST /api/system/scripts/reload | 查看脚本路由表 · 热重载用户脚本（失败保留旧路由） |
| GET /api/system/scripts/<kind>/files | 列出脚本文件（传统单文件 + 站点目录）及声明站点 |
| GET /api/system/scripts/<kind>/source?name= · POST /api/system/scripts/upload | 按名查看 · 上传（multipart：kind+name+file[+force]）。上传前两级冲突检测——同名文件、website 与其他脚本重复——409 由用户决定覆盖（force=true）；**保存成功后立即重新扫描分发器**，新文件即刻生效，失败保留旧路由 |
| DELETE /api/system/scripts/<kind>/<name> | 删除脚本文件并重新扫描 |
| GET /api/system/config · GET/PUT /api/system/config/<段>/raw · POST /api/system/config/reload | 列配置段 · 以 YAML 读/写单段（写盘+内存即时生效） · 从文件整体重载 |
| GET /api/system/websites | 站点入口列表与占用统计（作品/位点/脚本路由引用情况） |
| PUT /api/system/websites/<name> | 新增/更新站点入口（写 websites.yaml，站点名限字母/数字/下划线/连字符） |
| DELETE /api/system/websites/<name>?force= | 删除站点入口（仍被作品/位点/脚本路由引用时要求 force=true） |

统一响应 `{success, message/error, ...}`；主键身份均为 `(id, website)`。

## 前端

`src/server/web/index.html` 单文件单页应用（无框架、无构建），由 REST API 的 `/` 路由同源托管。
功能：作品 / 位点 / Cookie / 系统四个 Tab；顶部按站点×状态的统计条（点击站点名设站点筛选、点击状态 chip 切换状态多选）；
筛选维度可任意组合——站点、状态多选、作者（经 upload 关联）、日期区间（可选字段）、关键字、排序方向；
分页与每页大小；作品行内"停止/重新入队"操作（调用对应管理 API）；筛选变更 300ms 防抖自动刷新。
位点 Tab 支持在线添加位点（站点选项来自 `websites.yaml`）和行内"停止追踪 / 恢复追踪 / 立即更新"；
Cookie 页提供登录代理入口与状态，以及站点入口在线增删改（写 `websites.yaml`）；
系统页提供脚本路由查看/热重载/Web 上传脚本、单段 YAML 配置编辑器、配置整体重载。

## 初始化与生命周期

```
main.py (--basepath / BASEPATH)
  └─ init()
     ├─ init_files()        # assets 模板补齐工作目录
     ├─ config_manager.init_config()
     ├─ logger.init_log()
     ├─ DatabaseManager.init_database()
     ├─ rest_api.init()     # 后台线程
     ├─ updater.init() + start()
     └─ downloader.init()   # init 内自启调度线程
SIGINT → downloader.stop() → updater.stop() → rest_api.stop() → ConfigManager.stop_daemon()
```

## 测试

`tests/`（pytest）：models（外键/复合主键/downloadInfo/关系）、dispatcher（路由/兜底/报错）、
config（get 语义/占位符/env 覆盖不落盘）、queue（认领排序/状态回写/stopped 保护/崩溃回收/API）、
migrations（版本戳/幂等/PRAGMA）。运行：`python3 -m pytest tests/`。

## 部署（Docker）

仓库根目录：`Dockerfile`（python:3.12-slim，非 root，STOPSIGNAL SIGINT，自带健康检查）、
`docker-compose.yml`（数据卷 + 端口 + 1 分钟 stop 宽限）、`.dockerignore`（排除本机 `docker/` 工作目录）。

```bash
docker compose up -d --build     # 首次启动自动在卷里 bootstrap 配置模板
# 数据（配置/数据库/cookie/下载文件）全在命名卷 spider-data 的 /data 下，升级镜像不丢
# 改配置：直接编辑卷内 /data/confs/*.yaml（热重载生效），或 docker cp 后等重载
# docker stop 会触发 SIGINT 优雅退出，等池内任务收尾（宽限期 compose 里给了 1 分钟）
```

注意：镜像内不需要 Chrome（登录走代理，无浏览器依赖）；健康检查固定探测 8300，
改端口需同步改 compose 和 `/data/confs/system.yaml`。

## 已知未接线 / 待办

- size/duration 类下载限制（`once_download_size` / `once_download_duration`、`once_update_duration`）
  未实现；实现时需把相应配置键加回（当前 yaml 已清理）。
- `download_thread` 热改不生效（站点线程池在启动时建好），改后需重启进程。
- 登录代理只改写服务端返回的 HTML 文本，站点若用 JS 拼绝对 URL 跳转或强 CSP，可能需要针对性适配
  （有 404 Referer 救援兜底）。
- REST API 无鉴权（仅限内网使用）；cookie 文件为明文 JSON，靠工作目录权限保护。
