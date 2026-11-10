# SpiderScheduler 开发手册

> 面向二次开发者：架构分层、脚本插件生命周期、状态机、数据库与迁移、调度器内部实现、
> 配置系统、前端结构、测试与扩展指南。运行与操作见 [使用手册](user-guide.zh-CN.md)；
> 与代码保持同步的架构文档是根目录 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 1. 架构总览

```
main.py ──► src/core/initialization.py（统一 init：文件→配置→日志→数据库→API→Updater→Downloader）
                     │
     ┌───────────────┼────────────────┬─────────────────┐
     ▼               ▼                ▼                 ▼
 src/config     src/server       src/service        src/utils
 配置/路径       rest_api + 7蓝图  updater/downloader  database/cookie/logging/
 （热重载）      + 前端托管        dispatcher          threadPool/dynamic_loader
```

依赖方向自上而下、无反向引用。全库 ~5400 行 Python + 958 行前端单页。

关键设计决策（背景与理由）：

- **站点差异收拢在数据里**：`downloadInfo` 承载参数维度，`download.yaml` 的 site 段承载节奏维度，
  `websites.yaml` 承载入口维度；框架代码零站点逻辑。
- **脚本即插件**：动态加载 + 按 `website` 路由；加载前自动装依赖；重载失败保留旧路由。
- **单写者模型**：作品认领、状态回写都发生在"站点调度线程"这一个线程里，天然免竞态；
  SQLite 开 WAL + busy_timeout + 外键强制。

## 2. 数据模型

三张表全部以 `website` 入键（迁移历史：v1 multiWeb 初始结构；v2 user→publish_pos 更名）。

```
publish_pos（发布位点）       works                          upload
  authorId ─┐(PK)             workNumber ─┐(PK)              website  (PK)
  website ──┘(PK)            website ────┘(PK)              authorId (PK, FK→publish_pos)
  addTime                    upTime/title/kind              workNumber(PK, FK→works)
  state                      state / downloadDate           （多对多关联）
                             downloadPriority
                             otherInfo / downloadInfo
```

### 2.1 状态机

- `publish_pos.state`: `inQueue` ⇄ `stopped`（stopped 的位点被 updater 跳过）。
- `works.state`（下载管线）: `inQueue（或 NULL，兼容旧数据）→ downloading → done / failed`；
  `stopped` 可随时置入：调度跳过、完成回调不覆盖；崩溃残留的 `downloading` 每轮开始重置回 `inQueue`。
- 源站自身的作品状态不入 `state`，存 `otherInfo` 的 `siteState` 键（JSON）。

### 2.2 实现要点与陷阱

- **复合外键 + DEFERRABLE**：`upload` 的两条外键共享 `website` 列，ORM 同批 flush 无法保证
  父表先插，因此 `DEFERRABLE INITIALLY DEFERRED`（commit 时检查，插入顺序无关、孤儿仍被拒）。
  运行参数在连接级 PRAGMA：`journal_mode=WAL`、`busy_timeout=30000`、`foreign_keys=ON`。
- **会话过期陷阱**：`get_db_session()` 退出即 commit，之后 ORM 对象过期。跨会话使用数据
  必须在会话内拷贝成 dict（认领逻辑就是这么做的）。
- **关系全部 viewonly**：`upload` 两条外键共享列导致关系写方向歧义，写入一律显式构造
  `Upload(...)`，关系只用于导航。

### 2.3 迁移机制

- `schema_version` 表存当前版本；迁移文件 `src/utils/database/migrations/000N_说明.py`，
  提供 `apply(engine)`，**必须幂等**（全新库由 create_all 直接建出最新结构，可能跳过历史迁移）。
- 修改模型的标准流程：改 `models.py` → 写 `000N_*.py` → `database.py` 的 `HEAD_SCHEMA_VERSION` +1。
- 版本判定：全新库 create_all 后直接记为 HEAD；已存在的旧库若首次见到版本表，记为 1（基线
  = 随本版本发布的手工迁移后结构），然后补跑之后的所有迁移。0002 是第一个实战迁移
  （user→publish_pos，含 create_all 预建空表的处理）。

## 3. 脚本插件生命周期

```
init / 系统页重载 / 网页上传
        │
        ▼
ScriptDispatcher.load()
  ├─ 求值 sources() → 文件路径列表（传统单文件优先 + scripts/<kind>/ 目录排序；每次 load
  │  重新求值，上传/删除文件后重扫即可发现变化）
  ├─ 逐文件 ensure_requirements()  解析头部 "# requirements:" → 检测缺失（packaging 可用则
  │  校验版本约束）→ 锁内 pip install（失败仅记日志，不阻断）
  ├─ 逐文件 load_module_from_file() 扫描公共类 website 属性 → 跨文件合并路由
  │  （重复站点先到先得并告警；无 website 的文件可贡献兜底，至多一个）
  └─ 全部解析成功才一次性提交 self._routes/_wildcard/_file_routes —— 失败时旧路由原样保留。
     `sites_by_file()` 供上传端点做 website 冲突检测。
```

- 分发：`dispatcher.get(website)` 精确匹配 → 兜底 → `ScriptRouteError`（报可用站点）。
- `snapshot()` 返回路由表快照，供系统页展示。
- 脚本实例注入：`logger`（SpiderLogger 类）、`config_manager`、`cookie_manager`（类本身，
  classmethod 风格）。

### 3.1 DownloadWork 契约

```python
def __init__(self, work_info: dict, download_path: str, download_info: dict | None)
def download_it(self) -> str | dict   # str=产物路径；dict={path, duration?}
```

`download_path` 由包装层决定（见 §5.2），目录已创建。返回值缺路径在 cache 模式下视为失败。

### 3.2 UpdateUser 契约

```python
def __init__(self, usr: dict, logging)   # usr = {authorId, website, addTime}
def __iter__ / __next__                  # 逐条产出 dict：
# workid|workNumber(必填)、upTime、title、kind、state(→otherInfo.siteState)、
# downloadDate、downloadPriority
```

`upload` 关联已存在时停止本位点迭代（增量同步语义）——**产出顺序必须从新到旧**。

## 4. 调度器内部

### 4.1 Updater（每站点独立）

```
守护线程（5s 巡检）：全局 do_update 开 → 发现有未停止位点的站点 → 为每个站点拉起 runner
runner：建站点专属 ThreadPool(update_thread) → _site_loop
_site_loop：站点级 do_update 关闭即退出（恢复后守护线程重拉）→ 每轮：
    查本站未停止位点 → 逐位点提交线程池任务（commit_interval ±10% 错峰）→
    等本轮收尾汇总 → 按 update_interval ±10% 休眠（-1 表示持续更新）
```

任务内逐条入库：`works`（IntegrityError=已存在，忽略）→ `upload`（IntegrityError=已同步过，
break）。`page_interval`（位点内翻页间隔）按站点解析后灌给脚本实例。

### 4.2 Downloader（每站点独立）

```
守护线程（5s 巡检）：全局 do_download 开 → 发现 pending 站点 → 为每个站点拉起 runner
runner：建站点专属 ThreadPool(download_thread) → _site_loop
_site_loop：站点级 do_download 关闭即退出（恢复后守护线程重拉）→ 每轮：
    回收本站 downloading 残留 → 循环认领（本站、优先级降序）→ pool.submit →
    wait_for_completion → 按 download_interval 休眠（每次轮末重读，热生效）
```

- `_claim_next_work(website)`：认领即置 downloading，**单线程认领免竞态**；必须在会话内转 dict。
- `_run_download_task`：按站点解析 use_cache/download_path 等 → 实例化脚本 → `download_it()` →
  cache 模式 `_deliver_to_final()`（拷贝到 `download_path/<website>/<work>/` + rmtree 缓存目录）→
  `_finish_work`。
- `stop()`：置全局 Event（所有 sleep 都是 `Event.wait`，可唤醒）+ 逐池 shutdown(wait=True,
  cancel_futures=True)。已知噪音：若调度线程恰在 submit 时被关池，会记一条无害 error。

### 4.3 线程池

`ThreadPool(ThreadPoolExecutor)`：submit 前信号量限流（池满阻塞提交者，天然背压），
内置计数与 `wait_for_completion` 轮询。站点池在 runner 退出时 shutdown。

## 5. 配置系统内部

- `load_all_configs()`：**局部构建完整副本 → 锁内整体换入** `config_dict`（热重载期间读方
  无空窗；目录缺失时旧配置保留）。单个文件解析失败只丢该段并记日志。
- `_apply_env_overrides()`：每次文件重载后重放，仅内存、不回写 —— env 覆盖永远压过文件。
- `ConfigManager.get(dict_name, key)`：RLock；键不存在抛 `GetUnknownKey`；字符串值中的
  `${BASE_PATH}` 统一替换为工作目录。
- `replace_section()`：系统页配置编辑的写路径（校验根节点为映射、段必须已存在、原子写盘）。
- `site_setting(website, key)`（Downloader）：`download.yaml` 的 `site.<website> >
  site.default > 代码内置兜底`，覆盖值同样做 `${BASE_PATH}` 替换。

## 6. 登录代理内部

- 每站点一个 `requests.Session`（进程内；save/cancel 后销毁）——Set-Cookie 全部进 jar，
  浏览器只看到同源响应（绕开第三方 cookie 限制）；后续请求自动带 jar 里的 cookie。
- `_rewrite_html`：绝对/协议相对地址 → 占位符 → 根相对 `href|src|action/...="/x"` 补代理前缀
  → 统一还原 + 注入 `<base>`。占位符两步法防止双重前缀。
- 已知局限：只改写服务端返回的 HTML 文本；JS 运行时拼的根相对请求由 rest_api 的 404
  handler（Referer 判断）302 救回；第三方 OAuth/强 CSP 站点需针对性适配。
- 并发假设：单用户单会话；`requests.Session` 非严格线程安全，勿多人同时登录同一站点。

## 7. 前端架构

`src/server/web/index.html` 单文件（无构建、无依赖），由 Flask `/` 路由同源托管。

- 全局状态 `S = {tab, works, positions, stats, size}`；`api` 是可调用对象，附 `post/put`。
- 每个 Tab 一组函数：`loadX / renderX`；表格渲染统一走 `#table`，行内操作用事件委托
  （`data-*` 属性分发）。
- 筛选变更 → `reload()`（防抖 300ms）；统计条点击直接改筛选状态。
- 已知坑：`th` 的 sticky 在 `border-collapse` + `overflow:hidden` 表格中被 Chromium 错位
  （已移除）；Playwright 自动化在该页面偶发 click 静默失效，测试时用页面内 evaluate 循环重试。

## 8. 测试

```bash
python3 -m pytest tests/          # 124 例
```

| 文件 | 覆盖 |
|---|---|
| test_models | 复合外键 DEFERRABLE、downloadInfo、关系导航 |
| test_dispatcher | 路由/兜底/重载安全/requirements |
| test_config | 副本换入原子性、env 内存覆盖、replace_section、${BASE_PATH} |
| test_queue | 认领排序/状态回写/stopped 保护/崩溃回收/缓存包装/每站隔离 |
| test_updater | 站点级配置解析、每站点调度、产出从新到旧、page_interval 灌参 |
| test_script_tools | 日志出口、站点地址、Selenium 装配桩测、动态注册 |
| test_e2e | 内嵌虚拟站点 + 真实调度全链路 |
| test_logger | 日志调用方归因（实例方法/classmethod）与月度轮转 |
| test_query_api | 各筛选维度组合、分页、统计 |
| test_cookie | HTML 改写、存取、save 流程 |
| test_system_api | 脚本路由/重载/上传、配置 raw 读写、站点入口 CRUD、立即更新 |
| test_migrations | 版本戳幂等、PRAGMA、v1→v2 旧库升级 |

常用模式：`monkeypatch.setattr(ConfigManager, "base_path", str(tmp_path))` 隔离工作目录；
`DatabaseManager.engine = create_engine(...)` 指向临时库；Flask `test_client` 直接注册蓝图。

## 9. 扩展指南

**接入新站点**：① Cookie 页添加站点入口（写 `websites.yaml`）→ ② Cookie 页去登录存 cookie →
③ 系统页上传脚本（类声明 `website`，头部可声明 requirements）→ ④ 可选：`download.yaml` 的 site 段
加该站点的节奏覆盖。全程无需重启。

**新增 REST 端点**：在对应蓝图 `_register_routes` 里加路由（错误统一 `_err` 帮助函数，
响应带 `success`），在 `docs/user-guide*.md` 的 API 表登记。

**新增数据库变更**：见 §2.3 三步流程；迁移测试参考 `test_migrations.py::test_old_user_table_migrated_to_publish_pos`
（手工构造旧结构 → 跑 runner → 断言数据与版本）。

**约定**：注释与日志用中文；ORM 关系一律 `viewonly=True`；跨会话使用 ORM 数据先转 dict；
配置读取走 `ConfigManager.get`（享受 ${BASE_PATH} 与 env 覆盖），站点级走 `site_setting`。

## 10. 已知局限（诚实录）

- REST API 无鉴权（0.0.0.0，仅限内网）；cookie 文件明文。
- 登录代理会话进程内单例——gunicorn 多 worker 部署会分裂；`requests.Session` 非严格线程安全。
- 缓存模式下拷贝前崩溃会残留缓存目录（重下覆盖，无害但累积，可手动清理）。
- `download_thread` 热改不生效（需重启）。
