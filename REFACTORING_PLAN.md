# SpiderScheduler 重构状态与路线

> 本文档取代旧版重构计划。旧计划中"已完成"的勾选与当时实际进度不符，
> 现在以 2026-10 的 multiWeb 分支重构为基线，如实记录。

## 已完成（2026-10-31）

### 多站点（multiWeb）贯通
- [x] 数据模型：三张表全部以 `(id, website)` 为联合主键；`upload` 使用复合外键
      （`DEFERRABLE INITIALLY DEFERRED`，解决 ORM 同批 flush 排序 + 保持约束强制）
- [x] 服务层读写全部携带 website（updater / downloader）
- [x] REST API 四个管理端点按复合身份查重定位；`add_user` 补齐 addTime/state
- [x] REPL 已支持 `add-user <userId> [website]`（本次作为对齐基准）

### 脚本层多站点分发
- [x] 新增 `ScriptDispatcher`（src/service/dispatcher.py）：按类属性 `website` 路由，
      支持站点列表；无声明时回退传统单类（向后兼容）；路由失败报可用站点
- [x] Downloader / Updater 接入 dispatcher，按任务的 website 分发脚本类
- [x] 脚本模板加 `website` 字段；UpdateUser 模板实例可读 `self.website`

### 队列语义（修复"队列不是队列"）
- [x] 认领式调度：`inQueue/NULL` 过滤 + `downloadPriority` 降序 + workNumber 升序
- [x] 认领即置 `downloading`，完成置 `done`（记 downloadDate）/失败置 `failed`
- [x] `stopped` 全链路生效：downloader 跳过、完成回调不覆盖；updater 跳过 stopped 用户
- [x] 崩溃回收：每轮开始把残留 `downloading` 重置回 `inQueue`
- [x] 新增 `POST /api/download/requeue_work` 重新入队
- [x] 状态语义统一：`works.state` 管线化，源站状态进 `otherInfo.siteState`

### downloadInfo
- [x] `works.downloadInfo`（JSON 文本）：`add_work` 接受任意 JSON 入库，
      下载时反序列化为 `download_info` 传给脚本；解析失败告警并传 None
- [x] 下载脚本模板签名对齐：`(work_info, download_path, cache_path, download_info)`
      （此前 downloader 传 `use_cache=`/`logger=` 与模板不匹配，任务必然 TypeError；
      入口统一为 `download_it()`）

### 工程化
- [x] SQLite：连接级 WAL / busy_timeout=30s / foreign_keys=ON
- [x] `database.yaml` 的 `echo`、`connect_args` 真正被读取（此前是装饰性配置）
- [x] 轻量 schema 迁移：`schema_version` 表 + `migrations/000N_*.py` + HEAD_SCHEMA_VERSION
- [x] 优雅退出：updater/downloader `stop()`（Event 唤醒所有 sleep + 线程池收尾），
      main 信号处理依次停服务/停 API/停配置守护线程
- [x] updater/downloader 正式接入初始化流程（此前被注释，系统只有 API 在跑）
- [x] config.py：`get()` 诊断循环 shadow 参数导致报错信息错乱（已修）；
      None 值合法；`${BASE_PATH}` 占位符统一替换；
      env 覆盖不再回写配置文件、热重载后重放
- [x] 配置键与代码对齐（此前 downloader 读 `once_download`/`check_interval`、
      updater 读 `check_interval` 在 yaml 中根本不存在，服务一启动即异常循环）：
      轮间隔统一 `download_interval`/`update_interval`，数量限制
      `once_download_number`（update 侧每轮位点限量已移除），任务节奏 `sleep_second`，
      新增 `commit_interval`；清理重复的 `use_cache` 键
- [x] 测试：pytest 五组（models / dispatcher / config / queue / migrations），24 例全过
- [x] threadPool 自测代码引用不存在的方法（已删）；文档重写与代码一致
- [x] 脚本热重载：系统页一键重载（失败保留旧路由并提示原因），无需重启进程
- [x] 脚本 Web 上传：multipart 上传两种脚本（UTF-8/语法校验拒收坏脚本，保存后自动重载对应分发器）
- [x] 脚本多文件分发：scripts/<kind>/<name>.py 每站点一个文件，路由跨文件合并（重名先到先得）；
  上传两级冲突检测（同名文件/website 重复，409 由用户决定覆盖），保存后自动重新扫描生效
- [x] 脚本依赖自描述：头部 `# requirements:` 声明，加载前自动检测并安装缺失依赖（packaging 可用时校验版本约束）
- [x] 前端系统页：脚本路由查看/重载 + 单段 YAML 配置编辑器（写盘+内存即时生效）+ 配置整体重载
- [x] 配置加载改为"构建副本-锁内整体换入"，消除热重载期间读方的空窗
- [x] 死配置键清理（network.yaml 的 domain/cookie_file/use_cookie/chrome_path、global_conf.run、
      download_kind、once_*_size/duration；实现对应功能时再加回）
- [x] 下载缓存包装（use_cache 以新语义回归）：脚本只面对一个下载目录（开=缓存工作目录，
      关=最终目录），返回产物路径，框架负责拷贝到最终保存路径并清理缓存
- [x] old_code/ 归档清理（git 历史可找回）
- [x] 下载配置每站独立：download_sites.yaml 站点段覆盖全局（线程池/间隔/限量/缓存/路径/站点开关），
      每站点独立调度线程，守护线程自动发现/拉起站点
- [x] 每站点可下载时间窗口：daily/weekly/monthly + start/end（支持跨天/月末负数），窗口外静默等待、
      开窗即抢；配置非法 fail-open；配合 -1 限量/间隔实现窗口内全速突击消耗代理流量
- [x] 更新调度每站点独立（与下载对称）：update_sites.yaml 站点段覆盖全局（线程/间隔/错峰/站点开关），
      每站点独立调度线程，守护线程自动发现/拉起
- [x] user 表按其真实语义更名：user → publish_pos（发布位点）、userId → authorId（含 upload），
      API/REPL/前端/脚本契约同步；迁移 0002 完成（schema v2），真实库数据无损

### 数据迁移
- [x] `docker/datas/spider.db` 已迁移至当前结构（备份：`spider.db.bak-20261031`），
      upload 表重建为延迟复合外键版本，2 条 pixiv 用户数据无损

## 待办路线（按建议顺序）

1. **下载/更新限制补全**：once_download_number 已接线；size/duration 类限制实现时需把
   相应配置键加回（已清理）
2. **安全**：REST API 鉴权（当前 0.0.0.0 裸奔，仅限内网使用）；
   cookie 文件是明文 JSON，靠工作目录权限保护
3. **登录代理健壮性**：只改写服务端 HTML，JS 拼绝对 URL/第三方 OAuth 跳转/强 CSP 站点需针对性适配；
   requests.Session 为进程内单例，若未来换多 worker 部署（gunicorn）登录会话会分裂
4. 可选：引入 alembic 替代自研迁移（当前规模下自研版够用）
