# SpiderScheduler 接口文档

> 两个扩展点的完整契约：站点**下载脚本**（`DownloadWork`）与站点**更新脚本**
> （`UpdateUser`），以及 `Downloader` / `Updater` 两个调度服务暴露的公共接口。
> 面向站点脚本作者与二次开发者。运行与操作见 [使用手册](user-guide.zh-CN.md)；
> 架构与内部实现见 [开发手册](dev-guide.zh-CN.md) 与 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 1. 扩展点总览

| | 下载 | 更新 |
|---|---|---|
| 脚本基类（兜底类名） | `DownloadWork` | `UpdateUser` |
| 脚本目录 | `scripts/download/` | `scripts/update/` |
| 每站点配置 | `download.yaml` 的 `site` 段 | `update.yaml` 的 `site` 段 |
| 调度粒度 | 每站点独立调度线程 + 线程池 | 同左 |
| 轮次节奏 | `download_interval` | `update_interval`（轮）+ `commit_interval`（位点错峰） |
| 产出 | 更新 `works.state`、写产物文件 | 新增 `works` 行 + `upload` 关联 |

两类脚本共用同一套加载/路由/依赖安装机制（§2）；契约差异分别见 §3、§4；
调度服务自身的公共方法见 §5。

## 2. 脚本公共约定

### 2.1 文件与路由

- **文件位置**：`scripts/download/`、`scripts/update/` 站点脚本目录，一个文件可放
  多个站点的类。部署时框架把契约模板补装为 `scripts/download_a_work.py`、
  `scripts/update_a_user.py`（传统单文件兜底位，缺文件才补装、绝不覆盖）。
- **站点声明**：类属性 `website = "站点名"`，也可给列表 `["pixiv", "danbooru"]`；
  路由表跨文件合并，同一站点重复声明时先加载的生效并告警。
- **兜底**：文件内没有任何类声明 `website` 时，其中的 `DownloadWork` /
  `UpdateUser` 类作为传统单文件兜底，对任意未路由站点生效。
- **依赖声明**：脚本头部写 `# requirements: 包名[版本约束]`（可多行、逗号分隔），
  框架在加载前自动 pip 安装缺失依赖。
- **生效时机**：每次上传/删除/重载脚本都会重新扫描；新文件即刻生效，扫描失败
  保留旧路由。下载脚本上传/重载成功后，`noDownloader` 挂起作品自动刷回
  `inQueue`（见 §3.6）。

### 2.2 框架注入属性

脚本实例构造完成后由框架赋值（因此**不要在 `__init__` 里读取**）：

| 属性 | 值 | 说明 |
|---|---|---|
| `logger` | `SpiderLogger` 类 | 统一日志出口，自动按脚本类归因 |
| `config_manager` | 全局 `ConfigManager` 单例 | 配置读取（享受 `${BASE_PATH}` 与 env 覆盖） |
| `cookie_manager` | `CookieManager` 类 | 按 website 存取登录 cookie |
| `tools` | `ScriptTools` 实例 | 与当前任务站点绑定的运行时工具集 |

`ScriptTools`（`src/service/script_tools.py`）公开方法：

| 方法 | 说明 |
|---|---|
| `log(level, message)` | 以站点上下文写日志（`"info"` / `"warning"` / …） |
| `site_origin()` | websites.yaml 中本站点的入口地址（无配置抛 `ScriptToolsError`） |
| `proxy_url()` | system.yaml 配置的代理地址；未启用返回 `None` |
| `get_proxies()` | 可直接传给 requests 的代理字典；未启用返回 `{}` |
| `get_driver(...)` | 携带本站点登录态与代理的 Chrome（Selenium）；用完须 `driver.quit()`；需 `# requirements: selenium` |
| `register(name, fn)` | 动态注册扩展工具，之后可经 `self.tools.<name>(...)` 调用 |

`CookieManager`（`src/utils/cookie_manager.py`）公开接口：`exists(website)` /
`get(website)`（Selenium 逐条 `add_cookie` 用）/ `get_header(website)`（requests
Cookie 头用）/ `save(website, cookies)` / `delete(website)` / `status()`（全部
cookie 概览，供 Cookie 页展示）。cookie 文件在
`BASEPATH/datas/cookies/<website>.json`，由登录代理落盘。

### 2.3 模板与示例

- 契约模板（部署骨架，含完整契约注释）：`src/assets/scripts/download_a_work.py`、
  `src/assets/scripts/update_a_user.py`。
- 可运行示例（本地虚拟站点）：`demos/demo_site_downloader.py`、
  `demos/demo_site_updater.py`（`demos/run_demo.py` 一键起全链路）。

## 3. DownloadWork 契约（下载脚本）

### 3.1 必实现接口

```python
class XXXWork(DownloadWork):
    website = "站点名"          # 或站点名列表；不声明则本文件兜底

    def __init__(self, work_info: dict, download_path: str, download_info: dict | None):
        ...

    def download_it(self) -> str | dict:
        ...  # 执行下载并返回产物路径；抛出异常即任务失败
```

### 3.2 构造参数

**`work_info`** —— 作品快照 dict：

| 键 | 说明 |
|---|---|
| `workNumber` | 作品编号（站点内唯一标识） |
| `website` | 站点名 |
| `upTime` / `title` / `kind` | 源站元数据（更新脚本产出或 add_work 填写） |
| `state` / `downloadDate` / `downloadPriority` | 下载管线字段 |
| `downloadInfo` | 该作品的统一下载参数（见 §3.4） |

**`download_path`** —— 站点级下载根 `<路径根>/<website>/`：`use_cache` 开指向
缓存根，关则指向最终保存根（缓存开关对脚本透明）。**作品子目录由脚本自建**
（建议用基类提供的 `self._work_subdir(work_number)` 过滤文件系统不安全字符命名），
产物写进去。

**`download_info`** —— `work_info["downloadInfo"]`（JSON 文本）反序列化后的
dict，无则 `None`。框架预置 `{"authorId", "workNumber"}`（更新器写入）；
`add_work` API 可直接传 JSON 对象入库。约定 `"cookies"` 键携带任务级 cookie
（内存传入方式，形态同 §4.2），仅供把脚本当库直接实例化时使用。

### 3.3 返回值与交付规则

`download_it()` 返回：

- `str`：产物路径——相对 `download_path`（站点下载根）的相对路径，或绝对路径；
- `dict`：`{"path": 产物路径, "duration": 秒}`，`duration` 供 `waiting_play`
  模拟播放时长。

交付规则（cache 模式，框架侧完成）：

- 缓存根 ≠ 最终保存根：框架按相对层级把产物搬到
  `download_path/<website>/` 下，并清理该作品在缓存侧的残留；
- 两层一致（未配独立缓存层）或 `use_cache` 关：产物原地保留，无需搬运；
- 缓存模式下返回空路径、返回站点根本身、或指向缓存根之外 → 任务失败。

### 3.4 失败与挂起语义

| 情形 | 结果 |
|---|---|
| `download_it()` 抛任意异常 | 作品置 `failed`，日志记录异常 |
| 分发器无该站点脚本（`ScriptRouteError`） | 作品置 `noDownloader` 挂起（**不标 failed**） |
| 挂起/下载期间被 API 置 `stopped` | 保持 `stopped`，完成回调不覆盖 |

`noDownloader` 的作品不参与认领；站点脚本上传/重载成功或服务启动时，已有可用
脚本的站点自动刷回 `inQueue`（`Downloader.requeue_no_downloader()`）。

### 3.5 站点配置键（download.yaml 的 site 段）

解析顺序 `site.<website> > site.default > 代码内置兜底`，全部支持热更新。

| 键 | 默认 | 说明 |
|---|---|---|
| `do_download` | `true` | 站点级下载开关（全局根键 `do_download` 是总开关） |
| `download_thread` | `1` | 每站点下载线程数（改动需重启） |
| `download_interval` | `3600` | 每轮间隔（秒），`-1` 持续下载 |
| `once_download_number` | `-1` | 每轮下载数量限制，`-1` 无限制 |
| `use_cache` | `true` | 产物先写缓存，完成后由框架搬运到最终保存路径 |
| `download_path` | `datas/download` | 最终保存路径根（`${BASE_PATH}` 可用） |
| `cache_path` | `datas/download_cache` | 缓存中转根 |
| `sleep_second` | `15` | 任务间定长节奏（秒） |
| `waiting_play` | `false` | 按脚本返回的 `duration` 模拟播放（视频站用） |
| `download_window` | 无 | 可下载时间窗口：`mode: daily/weekly/monthly`、`start/end: "HH:MM"`（支持跨天）、`weekdays: [1-7]`、`month_days`（负数=倒数第几天）；缺省不限制 |

全局根键：`do_download`（总开关）、`site_scan_interval`（巡检周期）、
`window_check_interval`（窗口外轮询周期）。

## 4. UpdateUser 契约（更新脚本）

### 4.1 必实现接口（两种模式二选一）

```python
class XXXUpdate(UpdateUser):
    website = "站点名"          # 或站点名列表；不声明则本文件兜底

    def __init__(self, usr: dict, logging):
        ...                     # usr 是位点快照，保存即可
```

- **模板模式**：实现 `get_one_page()`——翻一页、把作品 dict 放进 `self.works`，
  迭代协议用基类默认 `__iter__/__next__`；
- **生成器模式**（浏览器场景推荐）：实现 `__iter__` 返回生成器——框架做增量
  同步会提前 break，生成器的 `finally` 能保证浏览器等资源及时清理，不依赖 GC。

### 4.2 构造参数

**`usr`** —— 位点快照 dict：`authorId` / `website` / `addTime`（仅此三个框架
字段）。把脚本当库直接实例化时，可约定 `usr["cookies"]` 携带 cookie（支持
Selenium `list[dict]`、`{name: value}` dict、`"k=v; k=v"` 字符串；该键不是
框架字段）。

**`logging`** —— 框架日志对象（`SpiderLogger`），用法同 `logger.info(...)`。

**注入属性**：`cookie_manager`（CookieManager 类）、`tools`（ScriptTools）、
`page_interval`（翻页间隔秒数，来自 `site.<website>.page_interval`，框架解析后
灌入；翻页由脚本控制，请在两次取页之间 sleep 本值，纯 API 站点可忽略）。

### 4.3 产出条目（迭代器逐条 yield 的 dict）

| 键 | 必填 | 说明 |
|---|---|---|
| `workid` 或 `workNumber` | ✔ | 作品编号（站点内唯一标识） |
| `upTime` | | 上传时间 |
| `title` / `kind` | | 源站元数据 |
| `state` | | 源站自身状态 → 框架存入 `otherInfo.siteState`（不进下载管线 state） |
| `downloadDate` / `downloadPriority` | | 下载管线字段（可选） |

**产出顺序必须从新到旧**——增量同步语义依赖它。

### 4.4 增量同步与入库（框架侧行为）

- 迭代中每条先查 `upload` 关联：**已存在即视为该位点已同步到此处，框架停止本
  位点迭代**（脚本无需自己判重）；
- 新作品写 `works`（已存在则跳过；并发竞态由 IntegrityError 兜底），
  `state` 统一 `inQueue`，`downloadInfo` 预置 `{"authorId", "workNumber"}`；
- 建 `upload` 关联（已存在跳过）。

### 4.5 站点配置键（update.yaml 的 site 段）

| 键 | 默认 | 说明 |
|---|---|---|
| `do_update` | `true` | 站点级更新开关（全局根键 `do_update` 是总开关） |
| `update_thread` | `1` | 每站点更新线程数（改动需重启） |
| `update_interval` | `21600` | 每轮间隔（秒，±10% 抖动），`-1` 持续更新 |
| `commit_interval` | `8` | 相邻位点任务的提交间隔（秒，错峰） |
| `page_interval` | `5` | 位点内翻页间隔（秒），框架灌给脚本 |

## 5. 调度服务公共接口

### 5.1 Downloader（`src/service/downloader.py`，模块级单例 `downloader`）

`works.state` 状态机：
`inQueue（或 NULL，兼容旧数据） → downloading → done / failed`；
`stopped` 可随时由 API 置入（调度跳过、完成回调不覆盖）；`noDownloader` 挂起
见 §3.4；进程中断残留的 `downloading` 每轮开始重置回 `inQueue`。

| 方法 | 说明 |
|---|---|
| `init()` | 构建脚本分发器 + 刷回挂起作品 + 启动站点巡检守护线程 |
| `stop()` | 置停止事件（所有 sleep 立即可唤醒）+ 逐站点线程池收尾 |
| `site_setting(website, key, default)` | 站点级配置读取（§3.5 的解析链） |
| `requeue_no_downloader()` | 把站点已就位脚本的 `noDownloader` 作品刷回 `inQueue`，返回刷回数；在 `init()` 与脚本上传/重载成功后自动调用 |

### 5.2 Updater（`src/service/updater.py`，模块级单例 `updater`）

| 方法 | 说明 |
|---|---|
| `init()` | 构建脚本分发器（调度线程由 `start()` 启动） |
| `start()` | 启动站点巡检守护线程 |
| `stop()` | 置停止事件 + 逐站点线程池与"立即更新"执行器收尾 |
| `site_setting(website, key, default)` | 站点级配置读取（§4.5 的解析链） |
| `update_position_now(website, author_id)` | 立即更新单个位点（后台执行，绕过轮次调度；返回 `{"started": bool}`） |
| `manual_status()` | "立即更新"状态快照（键 `"website|authorId"`，供前端轮询） |

### 5.3 ScriptDispatcher（`src/service/dispatcher.py`）

| 方法 | 说明 |
|---|---|
| `load()` | 重新求值脚本来源并加载，跨文件合并路由；失败保留旧路由 |
| `get(website)` | 精确命中 → 兜底类；未命中抛 `ScriptRouteError`（列出可用站点） |
| `snapshot()` | 路由表快照（website → 类名 + 兜底），供系统页展示 |
| `sites_by_file()` | 每个文件声明的站点列表（供上传冲突检测） |
| `websites()` / `has_fallback()` | 已注册站点列表 / 是否存在兜底类（供下载侧判断脚本是否就位） |
