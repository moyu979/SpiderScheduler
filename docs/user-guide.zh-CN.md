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
> `confs/network.yaml` 的 `rest_api_port`。

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
- **行内操作**：`停止追踪`（不再更新该作者）/ `恢复追踪`（重新参与更新）。
- 每行显示该位点的**作品数**（已建立的作者↔作品关联数）。

### 2.3 Cookie

各站点脚本的登录凭证按站点管理：

1. Cookie 页每个站点行点 **去登录**，会打开一个包装页：顶栏（完成并保存 / 取消）+ 下方是
   **目标站原样的登录页**（通过同源代理转发）。
2. 在页面里真实登录。整个过程的目标站 cookie 由后端自动捕获，不依赖浏览器保存。
3. 点 **完成并保存**，cookie 落盘为 `datas/cookies/<website>.json`，自动跳回系统页。
4. 已有 cookie 时再点"去登录"= 带着旧 cookie 进登录页，可用于刷新过期凭证；
   **删除**则清掉该站点的 cookie 文件。

脚本里通过注入的 `cookie_manager` 取用（见 §4）。

> 局限：代理只改写服务端返回的 HTML。若登录页用 JS 拼绝对 URL 跳转或有强 CSP，
> 可能需要针对性适配（404 时有 Referer 级兜底重定向）。

### 2.4 系统

- **用户脚本**：显示当前脚本路由表（`站点 → 类名`，以及兜底类）。改完工作目录里的脚本后点
  **重载脚本**即时生效；脚本有问题时保留旧路由并标红原因。
- **上传脚本**：两行上传控件（下载脚本/更新脚本）。保存前会做 UTF-8 与语法校验（语法错误
  拒收且不覆盖原文件），保存后自动重载。头部 `# requirements:` 声明的依赖会自动安装。
- **配置编辑**：下拉选择任意配置段（如 `download_setting`、`websites`），以 YAML 直接编辑，
  保存即写盘并在内存即时生效；"从文件重载全部"等效一次手动热重载。

## 3. 配置详解

配置都在 `confs/*.yaml`，修改后约 10 秒内热重载（或系统页保存立即生效）。
也可用环境变量覆盖：`<段名>_<键名>` 大写，如 `DOWNLOAD_SETTING_DO_DOWNLOAD=true`、
`TOKEN_PIXIV=xxx`（仅内存生效，不回写文件）。

### 3.1 download_setting.yaml（全局下载配置）

| 键 | 说明 | 默认 |
|---|---|---|
| `do_download` | 下载总开关（站点级开关的父开关） | false |
| `download_thread` | 全局默认下载线程数（每站点可覆盖） | 1 |
| `once_download_number` | 每站点每轮下载数量上限，-1 无限 | -1 |
| `download_interval` | 每站点轮间隔秒数，-1 = 持续下载 | -1 |
| `waiting_play` | true 时按脚本返回的 duration 模拟播放时长 | false |
| `sleep_second` | 任务间定长睡眠秒数 | 10 |
| `use_cache` | 缓存开关（见 §5 下载缓存） | true |
| `download_path` | 最终保存路径，支持 `${BASE_PATH}` | `./${BASE_PATH}/datas/download` |
| `cache_path` | 缓存中转路径 | `./${BASE_PATH}/datas/download_cache` |

### 3.2 download_sites.yaml（每站点独立配置）

键为 `website`，值为该站点生效的覆盖项，未写的键回落全局值：

```yaml
pixiv:
  download_thread: 2
  sleep_second: 8
  download_interval: 3600
danbooru:
  do_download: false        # 单独关掉某站点（恢复后自动重新拉起）
```

注意：`download_thread` 在站点线程创建时生效，改动需重启进程；其余键热生效。

### 3.3 其他配置段

| 段 | 关键键 |
|---|---|
| `update_setting` | `do_update` 总开关、`update_thread`、`update_interval`（轮间隔）、`once_update_number`、`commit_interval`（位点间错峰） |
| `websites` | `<website>: 入口 URL`——登录代理的目标、站点下拉的选项来源 |
| `network` | `rest_api_host` / `rest_api_port`、代理设置 |
| `global_conf` | `conf_reload_interval`（热重载周期）、`debug` |
| `database` | `url`（留空 = SQLite；可填 Postgres 连接串）、`echo`、`connect_args` |

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

更新脚本用迭代器产出作品（字段见开发手册 §3.2）。站点下拉里没有的站点，先在系统页
编辑 `websites.yaml` 添加入口地址。

## 5. 下载缓存机制

- `use_cache: true`：脚本拿到的是缓存中的专属目录 `cache_path/<站点_作品号>/`；
  `download_it()` 返回产物路径后，框架把产物**拷贝**到最终路径
  `download_path/<站点>/<站点_作品号>/`，然后清理该缓存目录。
- `use_cache: false`：脚本直接写最终保存目录，无中转。
- 两种模式脚本代码完全一致，切换开关不改脚本。

## 6. REST API 参考

统一响应 `{"success": true/false, ...}`；主键身份均为 `(id, website)`。

| 端点 | 说明 |
|---|---|
| `POST /api/update/add_pos` | `{authorId, website?}` 添加发布位点（website 默认 pixiv） |
| `POST /api/update/stop_pos` / `resume_pos` | 停止 / 恢复追踪位点 |
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
- **站点下拉是空的**：先在系统页编辑 `websites.yaml` 添加站点入口地址。
- **作品一直是 failed**：查看日志定位脚本异常，修复后"重新入队"。
- **登录页显示异常**：站点有强 CSP 或 JS 拼绝对 URL 时代理适配不了，属于已知局限。
- **数据库锁冲突**：框架已启用 WAL + busy_timeout，一般不会出现；避免多个进程同时打开
  同一个工作目录。
- **80 端口冲突 / AirPlay**：默认端口已是 8300，勿改回 5000（macOS）。
