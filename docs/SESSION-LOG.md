# SpiderScheduler 会话全记录

> 时间跨度：2026-10-31 ~ 2026-11-01 · 19 个提交（`59df14b` → `d2eadf7`）· 测试 0 → 88 例 ·
> 分支 `multiWeb` 开发，最终 fast-forward 合并进 `main` 并推送远端。
>
> 本文件是这段对话的完整纪事：每个阶段做了什么、为什么这么决策、踩过哪些坑、
> 最终落成了什么。配套阅读：[ARCHITECTURE.md](../ARCHITECTURE.md)（与代码同步的架构文档）。

## 起点：会话开始时的项目

提交 `ea7ac1b`（"日常步进"）时的样子——一个半成品的多站点爬虫调度器：

- **数据层**：`user` / `works` / `upload` 三表已加 `website` 入键，但外键还是单列
  （引用不完整主键），`works` 没有 `downloadInfo`；`downloader` 给脚本传参与模板
  签名不匹配（任务一跑就 TypeError）；下载"队列"无认领机制（同一作品重复抓）；
  `add_user` / `add_work` 不写 website（必违反 NOT NULL）。
- **调度层**：updater/downloader 被注释在初始化之外（系统只有 API 在跑）；配置键与
  yaml 对不上（`once_download`/`check_interval` 在 yaml 中根本不存在）；无优雅退出。
- **接口层**：无查询 API、无前端；`old_code/` 归档、`system_api` 单文件混两域、
  文档描述的是不存在的结构；零测试。
- **约定缺失**：token/cookie 概念未定、缓存只有配置键没有机制、无迁移、Docker 无。

## 时间线

### 阶段 0：认知与体检（只读）

确认项目定位（"基于用户脚本注入的爬虫调度系统"），盘点三表数据结构与实际
`spider.db` 的差异，讲解 updater 的返回值契约与入库流程（两步独立事务、
`upload` 撞重即停的增量语义）。

### 阶段 1：多网站数据层统一 + downloadInfo

复合主键 + 复合外键重构（后升级为 DEFERRABLE）、`works.downloadInfo` 列、
website 全链路贯通（updater/downloader/API/REPL/模板），手工迁移真实
`spider.db`（备份 `spider.db.bak-20261031`）。顺带修掉两个潜伏 bug：
downloader 传参与模板签名不匹配、`add_user`/`add_work` 缺 website 必然插入失败。

### 阶段 2：架构评审

三大结论：① 状态机是装饰性的（队列不是队列、stop 不生效）——最严重；
② multiWeb 只贯通到数据层，脚本层仍是单文件假设；③ 工程化欠账
（SQLite 并发裸奔、无迁移、无优雅退出、文档腐化、零测试）。

### 阶段 3：三大块修复（测试从 0 到 24）

- **队列语义**：认领式调度（`inQueue` 过滤 + 优先级排序 + 认领即 `downloading` +
  完成回写 + 崩溃回收），`stop` 全链路生效，新增 `requeue_work`。
- **脚本分发器 ScriptDispatcher**：按类属性 `website` 路由、单类兜底、重载失败
  保留旧路由。
- **工程化**：SQLite WAL/busy_timeout/外键强制、schema 迁移机制（版本表 +
  顺序迁移）、优雅退出（Event 唤醒 + 线程池收尾）、updater/downloader 正式接入
  初始化、config.py 的 `get()` shadow bug 与 env 覆盖不落盘、pytest 起步。

### 阶段 4：TokenManager → 回滚 → CookieManager + 登录代理

先做了 token 方案，随后用户纠偏："**其实是取 cookie**"——回滚 token，
改为按站点存取登录 cookie（`datas/cookies/<website>.json`，Selenium 兼容格式）。
cookie 不存在时，**登录代理**把目标站登录页原样转发到前端（iframe + 同源
HTML 改写），用户真实登录，后端捕获全过程 Set-Cookie 落盘。

### 阶段 5：前端与查询 API

新增 `query_api`（作品/位点组合筛选 + 站点×状态统计）与单页前端
（无构建、vanilla JS）。运行修复：API 端口 5000→8300（macOS AirPlay 占用）、
总开关打开、并抓出 **database URL 拼接 bug**（`sqlite:///./${DB_PATH}` 在绝对
BASEPATH 下产生畸形 URL——这也是"全链路第一次真正跑通"的拦路虎）。

### 阶段 6：发布位点更名（schema v2）

用户点破 `user` 表的真实语义是"发布位点"——更名 `user → publish_pos`、
`userId → authorId`，API/REPL/前端/脚本契约同步；迁移 `0002` 落地
（含 create_all 预建空表的处理），真实库数据无损。

### 阶段 7：前端完善与清理

位点 Tab 补"添加位点"（站点下拉来自 `websites.yaml`）与行内停止/恢复追踪；
删除 `old_code/`；空文件 `cookies_manager.py`（早期版本）清理。

### 阶段 8：下载缓存包装

用户设计：**脚本只面对一个下载目录 + downloadInfo**——缓存开时是缓存工作目录，
脚本返回产物路径后框架拷贝到最终路径并清理缓存；缓存关时直写最终目录。
`cache_path` 从脚本签名中移除。

### 阶段 9：Docker 部署

`Dockerfile`（3.12-slim、非 root、STOPSIGNAL SIGINT、健康检查）+ compose
（数据卷/端口/1 分钟 stop 宽限）+ `.dockerignore`（排除本机 `docker/` 工作目录）；
`main.py` 补 SIGTERM。

### 阶段 10：结构整理与谷歌风格注释

updater 内嵌 60 行任务闭包提取为 `_update_position()`；全库补齐模块/类/方法级
谷歌风格 docstring；`SpiderLogger` 五个级别支持标准 `%-args`（修复自定义 logger
不兼容标准写法导致的启动崩溃）；updater 去重改为预检关联（消除每轮必现的假
ERROR 日志）。

### 阶段 11：脚本多文件分发

`scripts/<kind>/<name>.py` **每站点一个文件**，路由跨文件合并（重复站点先到先得），
传统单文件优先兼容；上传两级冲突检测（同名文件 / website 与其他脚本重复 →
409 由用户决定覆盖）；脚本头部 `# requirements:` 依赖自描述（加载前自动
pip 安装）；系统页拆分为 `script_api` + `config_api`，前端改为文件列表管理；
**保存后自动重新扫描分发器**（用户特别要求记住的一点）。

### 阶段 12：可下载时间窗口

每站点 `download_window`（daily/weekly/monthly + start/end 支持跨天、
`month_days` 支持月末负数），窗口外调度线程静默等待（60s 周期）、开窗即抢；
配置非法 fail-open。配合 `-1` 限量/间隔实现"窗口内全速突击消耗代理流量"。

### 阶段 13：调度周期配置化 + 每轮位点限量移除

`site_scan_interval` / `window_check_interval` 配置化（带默认值兜底、最小 1 秒）；
`once_update_number`（每轮位点限量）按用户决定移除——"应该无限"。

### 阶段 14：更新调度每站点独立

updater 重构为与 downloader 对称的站点模型（守护线程发现 → 每站独立线程/间隔/
错峰/开关），理由：**查更新本身就是爬目标站页面**。站点覆盖逻辑提取为
`ConfigManager.site_setting()` 通用方法，两个调度器共用。

### 阶段 15：依赖漏洞修复

flask 2.3.3→3.1.3、requests 2.31.0→2.33.0、pytest 8.3.4→9.0.3
（pip-audit 与 Dependabot 警报对齐），Flask 3.1 运行时冒烟全过，警报清零。

### 阶段 16：最终验证、分段提交、合并推送

全量体检（编译/导入链/陈旧引用/未使用 import/文档一致性）修复 4 个尾巴
（`.gitignore` 补 `.pytest_cache`、空文件清理、未使用 import、蓝图列表过时），
按主题分 **9 个 commit** 提交，fast-forward 合并进 `main`（+7240/−1877 行，
74 文件）并推送 `origin/main` 与 `origin/multiWeb`。

## 关键设计决策

| 决策 | 拍板 | 理由 |
|---|---|---|
| 站点差异收拢在数据里（downloadInfo） | 用户 | 参数差异不该散在代码分支里 |
| 脚本按 website 类属性路由 + 单类兜底 | 用户定方向，兜底为实现补充 | 一个文件可承载多站点，旧脚本零改动兼容 |
| token → cookie + 登录代理 | 用户纠偏 | 脚本要的是登录态；真实登录页转发比模拟登录可靠 |
| user → publish_pos（发布位点） | 用户点破语义 | 它不是"我们的账号"，是对作者作品流的追踪位置 |
| 下载/更新都按站点独立调度 | 用户 | 查更新与下载都是爬目标站，限流必须按站 |
| 可下载时间窗口（daily/weekly/monthly） | 用户 | 突击消耗代理流量 |
| 缓存包装（脚本只见一个目录） | 用户 | 缓存对脚本透明，开关切换零成本 |
| 每轮位点限量移除 | 用户 | 应该无限 |
| once_download_number 保留 | 本轮判断 | 下载侧限流阀有独立场景 |

## 修复过的坑（按戏剧性排序）

1. **配置键与代码从未对齐**——downloader 读的 `once_download`/`check_interval` 在
   yaml 中不存在，服务一启动就异常循环；"全链路第一次跑通"前的最大拦路虎。
2. **SQLite URL 拼接 bug**——`sqlite:///./${DB_PATH}` 在绝对 BASEPATH 下产生按
   cwd 误解的畸形路径，`./docker` 能跑纯属运气。
3. **SpiderLogger 不支持 `%-args`**——整理日志时用了标准写法，启动即崩；
   已让 logger 兼容标准习惯。
4. **ORM 同批 flush 外键顺序**——两条复合外键共享 website 列时 upload 先于
   父表插入；DEFERRABLE INITIALLY DEFERRED 解决。
5. **假 ERROR 日志**——每轮更新撞 IntegrityError 被记成数据库失败；改为预检关联。
6. **前端上传整文件覆盖**——旧设计传 pixiv 会抹掉 danbooru 的类；多文件分发根治。
7. **Chromium sticky 表头错位**——`border-collapse` + `overflow:hidden` 下
   `th{position:sticky}` 渲染漂移 49px；移除 sticky。
8. **HTML 改写双重前缀**——绝对地址改写后又被根相对正则再包一层；占位符两步法。
9. **切换 Tab 自动展开空表单**——站点下拉只在按钮处理里填充，切 Tab 时表单
   先展开导致"没有可用站点"误报；改为只由按钮打开。
10. **`work_dir` 残留引用**——目录层级重构后调用处漏改一处变量名，测试当场抓住。

## 问答与讲解记录（只读类交互）

- updater 的返回值契约与两步入库流程（works 去重 / upload 撞重即停）
- 整体架构讲解、代码框架带读、数据存放位置、线程模型（更新全局/下载分站的不对称）
- 可下载时间窗口/调度周期是否配置化
- bilibili 专用脚本是否存在（全分支全历史搜索：不存在）
- 下载缓存设计的前世今生

## 最终状态

- **规模**：src + main + tests 共 ~6900 行（Python + 单页前端）；88 例测试全绿。
- **架构**：入口(main) → 初始化(core) → 配置(config) → 数据库(utils/database) →
  双调度器(service: updater/downloader，均每站点独立) + 分发器(dispatcher) →
  REST API(server: 9 蓝图) + 前端(web/index.html)；基础设施在 utils。
- **线程模型**：主线程、API 线程、配置热重载守护、Update/Download 两个巡检守护、
  每站点一个更新/下载调度线程 + 各自池内工作线程。
- **配置**：9 个 yaml 段，全局默认 + 站点覆盖（download_sites / update_sites），
  热重载 + env 覆盖 + 系统页在线编辑。
- **分支**：`main` = `multiWeb` = `origin/main` = `d2eadf7`。

## 已知局限与待办

- REST API 无鉴权（0.0.0.0，仅限内网）；cookie 文件明文。
- 登录代理只改写服务端 HTML（JS 拼绝对 URL / 第三方 OAuth / 强 CSP 站点需适配）；
  代理会话为进程内单例，多 worker 部署会分裂。
- `download_thread` 热改不生效；`once_*_size/duration` 类限制未实现（键已清理）。
- Dockerfile 尚未真机构建验证（本机无 Docker，已做依赖 wheel 与生命周期模拟）。
- 依赖升级在 anaconda base 环境进行，建议后续为项目建立独立 venv。
