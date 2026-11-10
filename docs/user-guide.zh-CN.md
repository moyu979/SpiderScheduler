# SpiderScheduler 使用手册

> 面向使用者：安装运行、四个功能页逐项说明、REST API 参考、配置详解与常见问题。
> 架构与二次开发见 [开发手册](dev-guide.zh-CN.md)。

## 1. 安装与运行

### 1.1 本地运行

```bash
pip install -r requirements.txt      # Python 3.10+
python main.py                       # 默认工作目录 ./docker，API 与页面在 8300 端口
```

常用参数：

| 参数 / 环境变量 | 说明 |
|---|---|
| `--basepath <目录>` 或 `BASEPATH=<目录>` | 指定工作目录（配置、数据库、脚本、下载文件都在这里） |
| `--repl` | 启动后进入命令行（`add-pos <authorId> [website]`、`exit`） |

启动后浏览器打开 `http://127.0.0.1:8300`。首次启动自动在工作目录生成配置模板和空数据库。

> 端口说明：默认 8300。5000 在 macOS 上被 AirPlay Receiver 占用，故避开；改端口编辑
> `confs/system.yaml` 的 `rest_api_port`。

### 1.2 Docker 部署

```bash
docker compose up -d --build
```

- 数据全部在命名卷 `spider-data` 的 `/data`（容器内 BASEPATH）；
- `docker stop` 触发优雅退出（等待下载任务收尾，宽限期 1 分钟）；
- 改配置直接编辑卷内 `/data/confs/*.yaml`（热重载生效），或在系统页在线编辑。

### 1.3 工作目录结构

```
docker/                          ← BASEPATH
├── confs/*.yaml                 配置（可在线编辑、热重载）
├── scripts/                     你的两个用户脚本
└── datas/
    ├── spider.db                SQLite 主库（位点/作品/关联/迁移版本）
    ├── cookies/<website>.json   各站点登录 cookie
    ├── log/                     按月轮转日志
    ├── download/                下载产物（最终保存路径）
    └── download_cache/          下载缓存中转目录
```

备份 = 备份整个工作目录；迁移机器 = 拷贝整个目录。

## 2. 四个功能页

### 2.1 作品

- **筛选**：站点下拉、状态多选（inQueue / downloading / done / failed / stopped / 未标记）、
  作者（authorId，经作品关联反查）、日期区间（可选按"上传时间"或"下载时间"）、
  关键字（标题/作品号模糊匹配）、排序与分页。所有条件可任意组合，修改后约 0.3 秒自动刷新。
- **统计条**：每个站点一行，展示各状态计数。点击站点名 = 按该站点筛选；点击状态 chip = 加入/移出该状态的多选。
- **行内操作**：`inQueue/downloading/failed` 的作品可"停止"（state→stopped）；
  `stopped/failed/done` 的作品可"重新入队"（state→inQueue）。

### 2.2 位点

- **添加位点**：点"添加位点"，输入作者 ID、从下拉选站点（选项来自 `websites.yaml`），
  确认后立即生效——下一轮更新就会遍历该作者。重复添加会提示"已存在"。
- **筛选**：站点、状态（inQueue/stopped）、关键字、收录时间区间。
- **行内操作**：`停止追踪`（不再更新该作者）/ `恢复追踪`（重新参与更新）；
  `立即更新`（绕过轮次调度，后台立刻同步该位点一次——按钮变"更新中…"，
  完成后显示本轮新增数，等不到下一轮）。
- 每行显示该位点的**作品数**（已建立的作者↔作品关联数）。

### 2.3 Cookie

各站点脚本的登录凭证按站点管理：

1. Cookie 页每个站点行点 **去登录**，会打开一个包装页：顶栏（完成并保存 / 取消）+ 下方是
   **目标站原样的登录页**（通过同源代理转发）。
2. 在页面里真实登录。整个过程的目标站 cookie 由后端自动捕获，不依赖浏览器保存。
3. 点 **完成并保存**，cookie 落盘为 `datas/cookies/<website>.json`，自动跳回前端首页。
4. 已有 cookie 时再点"去登录"= 带着旧 cookie 进登录页，可用于刷新过期凭证；
   **删除**则清掉该站点的 cookie 文件。

脚本里通过注入的 `cookie_manager` 取用（见 §4）。

> 局限：代理只改写服务端返回的 HTML。若登录页用 JS 拼绝对 URL 跳转或有强 CSP，
> 可能需要针对性适配（404 时有 Referer 级兜底重定向）。

### 2.4 系统

- **用户脚本**：显示当前脚本路由表（`站点 → 类名`，以及兜底类）。改完工作目录里的脚本后点
  **重载脚本**即时生效；脚本有问题时保留旧路由并标红原因。
- **上传脚本**：选择种类（下载/更新）+ .py 文件上传；“文件名”是服务器上的保存名，留空则自动取上传文件名（含中文等字符时需手动指定）。脚本采用**多文件分发**：
  `scripts/<种类>/<文件名>.py` 每站点一个文件，路由跨文件合并。上传前做 UTF-8/语法校验，
  并检测两级冲突——同名文件已存在、website 与其他脚本重复——返回 409 并**询问是否覆盖**
  （确认后带 force 重传）；**保存成功后自动重新扫描分发器**，新文件即刻生效，扫描失败
  保留旧路由并标红原因。文件列表支持在线查看与删除（删除后同样重扫）。
- **配置编辑**：下拉选择任意配置段（如 `download`、`websites`），以 YAML 直接编辑，
  保存即写盘并在内存即时生效；"从文件重载全部"等效一次手动热重载。

## 3. 配置详解

配置都在 `confs/*.yaml`，修改后约 10 秒内热重载（或系统页保存立即生效）。
也可用环境变量覆盖：`<段名>_<键名>` 大写，如 `DOWNLOAD_DO_DOWNLOAD=true`、
`WEBSITES_PIXIV=https://www.pixiv.net`（仅内存生效，不回写文件）。

### 3.1 download.yaml（下载配置：全局层 + 站点层合并）

根键是**不可按站点覆盖**的全局开关与巡检周期；站点可覆盖的键统一放在 `site`
结构下（解析顺序：**site.<website> > site.default > 代码内置默认值**，任一层
缺省都不会导致调度失败）。日常调优只需要改 `site.default`：

```yaml
# ---- 全局层（根键） ----
do_download: false            # 下载总开关（站点级开关的父开关）
site_scan_interval: 5         # 站点巡检周期秒数（发现延迟）
window_check_interval: 60     # 窗口外轮询周期秒数（开窗后最多延迟该时长进场）

# ---- 站点层 ----
site:
  default:                    # 全部站点共用的默认值
    download_thread: 1        # 每站点下载线程数
    once_download_number: -1  # 每轮下载数量上限，-1 无限
    download_interval: 3600   # 每轮间隔秒数，-1 = 持续下载
    waiting_play: false       # 按脚本返回的 duration 模拟播放
    sleep_second: 15          # 任务间定长睡眠秒数
    use_cache: true           # 缓存开关（见 §5 下载缓存）
    download_path: "./${BASE_PATH}/datas/download"
    cache_path: "./${BASE_PATH}/datas/download_cache"

  pixiv:                      # 站点段只写与 default 不同的键
    download_thread: 2
    sleep_second: 8
  danbooru:
    do_download: false        # 单独关掉某站点（恢复后自动重新拉起）
```

注意：`download_thread` 在站点线程创建时生效，改动需重启进程；其余键热生效。
`download_path`/`cache_path` 未配置时代码兜底为 `BASEPATH/datas/{download,download_cache}`。

### 3.1.1 可下载时间窗口（突击消耗代理流量）

每个站点可以配置"什么时间允许下载"——窗口外该站点的调度线程静默等待（60 秒周期重新
评估），窗口一到立即开抢。三种模式（`start`/`end` 为 HH:MM，支持跨天如 22:00-06:00）：

| mode | 含义 | 专属键 |
|---|---|---|
| `daily` | 每天的固定时段 | — |
| `weekly` | 每周指定星期的时段 | `weekdays: [1, 5]`（1=周一…7=周日） |
| `monthly` | 每月指定日期的时段 | `month_days: [1, 2, -1]`（负数=倒数第几天，-1=最后一天） |

"突击消耗代理流量"的推荐配方（窗口内全速、不限量）：

```yaml
# download.yaml
site:
  pixiv:
    download_window:
      mode: monthly          # 每月 1、2 号和最后一天
      month_days: [1, 2, -1]
    once_download_number: -1   # 不限量
    download_interval: -1      # 不间断
    sleep_second: 0            # 任务间不休眠
```

细节：窗口外不认领新任务，进行中的任务会自然完成后停止；未配置窗口 = 不限制；
配置非法（时间格式错、weekly 缺 weekdays、monthly 缺 month_days）时**放行**并记警告，
不会静默停掉你的下载。

### 3.2 update.yaml（更新配置：全局层 + 站点层合并）

结构与 download.yaml 完全一致：根键 `do_update` 总开关；`site.default` 放
`update_thread`（线程数）/ `update_interval`（轮间隔）/ `commit_interval`
（相邻**位点**之间的提交间隔，错峰）/ `page_interval`（同一位点内相邻两页的
抓取间隔，由框架解析后灌给 updater 脚本——分页由脚本控制，纯 API 站点可忽略），
`site.<website>` 按站点覆盖（查更新也是爬页面，按站点限流）。

### 3.3 其他配置段

| 段 | 关键键 |
|---|---|
| `system` | 原四段合并：`debug`/`conf_reload_interval`/`conf_retry_interval`（运行）、`console_log_level`/`file_log_level`（日志）、`database_url`/`database_echo`/`database_connect_args`（数据库；远程库跳过 schema 迁移）、`rest_api_host`/`rest_api_port`/`use_proxy`/`proxy_ip`/`proxy_port`（网络与代理） |
| `websites` | `<website>: 入口 URL`——登录代理的目标、站点下拉的选项来源；支持 Cookie 页在线增删改（写回本文件） |

## 4. 用户脚本契约

脚本放在 `scripts/` 下，可在线上传（自动做语法校验与依赖安装）。

```python
# requirements: requests>=2.31          ← 依赖声明，加载前自动安装缺失的包
class DownloadWork:
    website = "pixiv"                   # 声明适用站点；不声明则本文件作为单站兜底
    # 框架注入：logger / config_manager / cookie_manager

    def __init__(self, work_info, download_path, download_info=None):
        # work_info: {workNumber, website, title, ...}
        # download_path: 本任务专属目录，框架已创建，把数据写这里
        # download_info: downloadInfo 反序列化后的 dict

    def download_it(self):
        ...                             # 返回产物路径（str）或 {path, duration}
```

更新脚本用迭代器产出作品（字段见开发手册 §3.2）。站点下拉里没有的站点，先在 Cookie 页
"添加站点"填写入口地址（写回 `websites.yaml`）。

## 5. 下载缓存机制

- `use_cache: true`：脚本拿到的是缓存中的专属目录 `cache_path/<站点>/<作品号>/`；
  `download_it()` 返回产物路径后，框架把产物**拷贝**到最终路径
  `download_path/<站点>/<作品号>/`，然后清理该作品缓存目录（站点目录保留）。
- `use_cache: false`：脚本直接写最终保存目录，无中转。
- 两种模式脚本代码完全一致，切换开关不改脚本。

## 6. REST API 参考

统一响应 `{"success": true/false, ...}`；主键身份均为 `(id, website)`。

| 端点 | 说明 |
|---|---|
| `POST /api/update/add_pos` | `{authorId, website?}` 添加发布位点（website 默认 pixiv） |
| `POST /api/update/stop_pos` / `resume_pos` | 停止 / 恢复追踪位点 |
| `POST /api/update/update_now` | `{authorId, website?}` 立即更新单个位点（后台执行）；`GET /api/update/update_now/status` 查询状态 |
| `POST /api/download/add_work` | `{workNumber, website?, downloadInfo?}` 作品入队 |
| `POST /api/download/stop_work` / `requeue_work` | 停止 / 重新入队 |
| `GET /api/query/works` | 组合筛选作品：`website`(逗号多选)、`state`(逗号多选，`none`=NULL)、`author`、`date_field`+`date_from`+`date_to`、`keyword`、`sort`、`order`、`limit`、`offset` |
| `GET /api/query/positions` | 组合筛选位点（附 `workCount`） |
| `GET /api/query/stats` | 站点×状态计数（页面统计条数据源） |
| `GET /api/cookie/status` | 站点 cookie 状态 |
| `GET /api/cookie/<w>/login_page` | 登录包装页 |
| `POST /api/cookie/<w>/save` / `cancel`、`DELETE /api/cookie/<w>` | 保存 / 放弃 / 删除 |
| `GET /api/system/scripts` · `POST .../reload` | 路由表 · 热重载脚本 |
| `GET /api/system/scripts/<kind>/source` · `POST .../upload` | 查看脚本 · 上传（multipart：`kind`+`file`） |
| `GET /api/system/config` · `GET/PUT /api/system/config/<段>/raw` · `POST /api/system/config/reload` | 配置查看 / YAML 读写 / 整体重载 |
| `PUT /api/{update,download,global,network}/config` | 按键更新对应配置段（键必须已存在） |

## 7. 常见问题

- **页面打开是空白/旧版**：浏览器强刷（Cmd+Shift+R）；页面文件每次请求都从磁盘读取。
- **改了配置/脚本没生效**：配置约 10 秒热重载（系统页保存立即生效）；脚本需在系统页点
  "重载脚本"；`download_thread` 例外，需重启进程。
- **站点下拉是空的**：先在 Cookie 页"添加站点"填写入口地址（写回 `websites.yaml`）。
- **作品一直是 failed**：查看日志定位脚本异常，修复后"重新入队"。
- **登录页显示异常**：站点有强 CSP 或 JS 拼绝对 URL 时代理适配不了，属于已知局限。
- **数据库锁冲突**：框架已启用 WAL + busy_timeout，一般不会出现；避免多个进程同时打开
  同一个工作目录。
- **80 端口冲突 / AirPlay**：默认端口已是 8300，勿改回 5000（macOS）。
