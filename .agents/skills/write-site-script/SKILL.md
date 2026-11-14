---
name: write-site-script
description: 为 SpiderScheduler 编写站点下载脚本（DownloadWork 契约）与站点更新脚本（UpdateUser 契约）。凡是要给某个站点（如 bilibili、pixiv、danbooru）写 downloader、下载脚本、下载器，或写 updater、更新脚本、更新器、作者追踪脚本，或提到"接入新站点"、DownloadWork、UpdateUser、scripts/download、scripts/update 目录时，都使用本 skill——读完即可写出正确的站点脚本，无需阅读框架代码。
---

# 编写 SpiderScheduler 站点脚本

## 先分清三个词

- **站点脚本**：你唯一要写的东西——一个自包含的 Python 文件，里面放一个（或多个）
  普通类。下载侧实现 **DownloadWork 契约**，更新侧实现 **UpdateUser 契约**。
- **Downloader / Updater 服务**：框架内部的调度器（`src/service/`）。脚本作者不需要
  读，也不要改。
- **权威契约文档**：`docs/interfaces.zh-CN.md`（英文版 `docs/interfaces.en.md`）。
  本 skill 给出工作流与速查；任何细节冲突以该文档为准。

## 写脚本前读什么

- **必读**：本文全部内容（含两份契约速查）。
- **写第一个脚本前建议精读**：契约文档对应章节（下载 §3 / 更新 §4）+ 对应 demo
  （`demos/demo_site_downloader.py` / `demos/demo_site_updater.py`）。
- **不需要读**：`src/` 下任何框架代码。脚本与框架之间只有本文描述的契约面。

## 公共约定（两类脚本共用）

### 文件位置与单文件自包含

- 下载脚本放 `scripts/download/`，更新脚本放 `scripts/update/`（运行根 BASEPATH 下）。
  一个文件可放多个站点的类。
- 脚本按**文件路径**直接执行加载，不进 `sys.modules`，所以**必须单文件自包含**：
  把需要的工具函数直接写在该文件里（参考 demo 的做法），不要 import 项目内模块。
- 放对目录即可生效：框架每次脚本上传/删除/重载都会重扫，新文件即刻生效；扫描
  失败保留旧路由。

### website 路由（分发器只认这个属性）

```python
class SiteDownloadWork:
    website = "pixiv"          # 字符串；或站点名列表 ["pixiv", "danbooru"]
```

- 站点名必须与数据库中作品 `Works.website` / 位点 `PublishPos.website` **完全一致**。
- 路由表跨文件合并；同一站点在多个文件重复声明时，先加载的生效并告警。
- 文件内所有类都不声明 `website` 时，该文件里的 `DownloadWork` / `UpdateUser`
  类作为传统单文件兜底，对任意未路由站点生效（一般不要用，除非明确要做兜底）。
- 类**不需要继承任何基类**（鸭子类型）。仓库内 demo 为了复用基类工具而继承模板类，
  独立写脚本时直接定义普通类即可。

### 依赖声明

脚本头部写 requirements 注释（可多行、逗号分隔），框架加载前自动 pip 安装缺失项：

```python
# requirements: requests>=2.31, beautifulsoup4
# requirements: selenium
```

安装失败只记日志，随后脚本顶部 import 时会以 ImportError 暴露真实问题。用
selenium 就必须声明。

### 框架注入属性（构造完成后赋值——不要在 `__init__` 里读取）

| 属性 | 值 | 下载脚本 | 更新脚本 |
|---|---|---|---|
| `logger` | SpiderLogger 类 | ✔ | —（改由 `__init__` 传入 `logging` 参数） |
| `config_manager` | ConfigManager 单例 | ✔ | — |
| `cookie_manager` | CookieManager 类 | ✔ | ✔ |
| `tools` | ScriptTools 实例（绑定当前任务站点） | ✔ | ✔ |
| `page_interval` | 翻页间隔秒数（update.yaml 注入） | — | ✔ |

**CookieManager**：`exists(website)` / `get_header(website)`（requests 的 Cookie
头字符串）/ `get(website)`（Selenium 逐条 `add_cookie` 用的 list[dict]）/
`save` / `delete` / `status()`。cookie 文件由登录代理落盘在
`BASEPATH/datas/cookies/<website>.json`。

**ScriptTools**：

| 方法 | 说明 |
|---|---|
| `log(level, message)` | 以站点上下文写日志（`"info"` / `"warning"` / …） |
| `site_origin()` | websites.yaml 中本站点入口地址（无配置抛 ScriptToolsError） |
| `get_proxies()` | 可直接传给 requests 的代理字典；未启用为 `{}`（可不加判断直接传） |
| `get_driver(...)` | 携带本站点登录态与代理的 Chrome；用完必须 `driver.quit()`；需 `# requirements: selenium` |
| `register(name, fn)` | 动态注册扩展工具，之后经 `self.tools.<name>(...)` 调用 |

### Cookie 三级优先级

内存传入 > 文件传入 > 匿名：

1. **内存传入**（把脚本当库直接实例化时）：`download_info["cookies"]`（下载）/
   `usr["cookies"]`（更新）携带 cookie，支持 Selenium `list[dict]`、
   `{name: value}` dict、`"k=v; k=v"` 字符串。该键不是框架字段，仅供直接实例化。
2. **文件传入**（调度流默认）：`cookie_manager.get_header(website)`（requests）或
   `cookie_manager.get(website)` 逐条 `add_cookie`（Selenium），或直接
   `tools.get_driver()` 一站式搞定 cookie/代理/UA。
3. 都没有就匿名请求。

cookie 形态归一的现成实现见 demo 文件里的 `normalize_cookies`，写脚本时直接抄。

### CLI 工具场景：要 cookie 文件的（you-get / yt-dlp 等）

you-get 这类命令行工具吃的是 Netscape 格式 cookies.txt（`--cookies <文件>`），
不是请求头。框架在 CookieManager 上提供了现成的 Netscape 导出——**脚本不需要
自己转格式、造临时文件**：

```python
if self.cookie_manager is not None and self.cookie_manager.exists(self.website):
    command += ["--cookies", self.cookie_manager.netscape_file(self.website)]
```

`netscape_file(website)` 返回框架管理的导出文件路径（源 JSON 按需导出、更新后
自动刷新），文件生命周期由框架负责。需要读原始 Selenium JSON 文件时用
`cookie_manager.cookie_file(website)`（极少用；常规取值走 `get()`）。
没有 cookie 时 `exists()` 为假，照常匿名执行。

任务级内存 cookie（`download_info["cookies"]` / `usr["cookies"]`）不在框架
存储里，`netscape_file` 覆盖不了：用 `cookie_manager.netscape_lines(cookies)`
转成 Netscape 文本行后自己写临时文件（`tempfile.mkstemp`，`finally` 删除）。

## DownloadWork 契约（下载脚本）

```python
# requirements: requests
import os
import re

import requests


def _work_subdir(work_number) -> str:
    """作品子目录名：过滤文件系统不安全字符（独立写脚本时自带这个函数）。"""
    return re.sub(r'[^A-Za-z0-9_\-.]', '_', str(work_number))


class SiteDownloadWork:
    website = "pixiv"

    def __init__(self, work_info, download_path, download_info=None):
        # work_info: 作品快照 dict，关键键 workNumber / website；
        #            其余有 upTime / title / kind / downloadInfo 等
        # download_path: 站点级下载根 <根>/<website>/。use_cache 开指向缓存根、
        #            关指向最终保存根——缓存开关对脚本透明
        # download_info: works.downloadInfo 反序列化后的 dict（无则 None），
        #            框架预置 {"authorId", "workNumber"}，其余键站点自定义
        self.work_number = work_info["workNumber"]
        self.download_path = download_path
        self.download_info = download_info or {}
        # 注意：logger / config_manager / cookie_manager / tools 此时尚未注入，
        # 只能在 download_it() 里用

    def download_it(self):
        header = ""
        if self.cookie_manager is not None and self.cookie_manager.exists(self.website):
            header = self.cookie_manager.get_header(self.website)

        resp = requests.get(
            f"{ORIGIN}/works/{self.work_number}",
            headers={"Cookie": header} if header else {},
            proxies=self.tools.get_proxies(),
            timeout=30,
        )
        resp.raise_for_status()          # 失败就抛异常，让任务进 failed

        work_dir = os.path.join(self.download_path, _work_subdir(self.work_number))
        os.makedirs(work_dir, exist_ok=True)          # 作品子目录由脚本自建
        target = os.path.join(work_dir, f"{self.work_number}.bin")
        with open(target, "wb") as f:
            f.write(resp.content)

        # 返回相对 download_path 的相对路径（或绝对路径）
        return os.path.relpath(target, self.download_path)
```

### 返回值与交付规则

- 返回 `str`：产物路径（相对 `download_path` 或绝对路径）。
- 返回 `dict`：`{"path": 路径, "duration": 秒}`，`duration` 供站点
  `waiting_play` 模拟播放时长（视频站用）。
- 配了独立缓存层时，框架会按相对层级把产物从缓存根搬到最终保存根——脚本只管
  写进 `download_path`、返回相对路径即可。缓存模式下返回空路径、返回站点根本
  身、或指向缓存根之外都会判任务失败。

### 失败与挂起语义

| 情形 | 结果 |
|---|---|
| `download_it()` 抛任意异常 | 作品置 `failed`，日志记录异常 |
| 分发器无该站点脚本 | 作品置 `noDownloader` 挂起（不标 failed）；脚本上传/重载成功或服务启动时自动刷回 `inQueue` |
| 挂起/下载期间被 API 置 `stopped` | 保持 `stopped`，完成回调不覆盖 |

### 站点配置键（download.yaml 的 site 段，可缺省）

解析顺序 `site.<website> > site.default > 代码内置兜底`，全部支持热更新。
常用默认值：`download_interval` 3600（`-1` 持续）、`download_thread` 1（改动需
重启）、`once_download_number` -1、`use_cache` true、`sleep_second` 15、
`download_path` datas/download、`cache_path` datas/download_cache、
`do_download` true、`waiting_play` false；`download_window` 可限制可下载时间
窗口（daily/weekly/monthly 模式）。细节见契约文档 §3.5。

## UpdateUser 契约（更新脚本）

构造签名固定为 `__init__(self, usr, logging)`；`usr` 是位点快照
`{authorId, website, addTime}`（框架字段仅此三个），`logging` 是框架日志对象。
两种实现模式**二选一**：

### 模式一：生成器模式（浏览器场景推荐）

```python
# requirements: selenium
import time


class SiteUpdateUser:
    website = "pixiv"

    def __init__(self, usr, logging):
        self.author_id = usr["authorId"]
        self.website = usr.get("website") or self.website
        self.log = logging

    def __iter__(self):
        return self._iterate()

    def _iterate(self):
        driver = self.tools.get_driver()     # 资源在 finally 里确保清理
        try:
            page = 1
            while True:
                if page > 1 and getattr(self, "page_interval", None):
                    time.sleep(self.page_interval)       # 框架注入的翻页间隔
                works, has_more = self._fetch_page(driver, page)
                yield from works             # 产出顺序必须从新到旧
                if not has_more:
                    return
                page += 1
        finally:
            driver.quit()                    # 框架增量同步会提前 break 迭代，
                                             # 生成器 finally 保证浏览器及时关闭
```

推荐生成器模式的原因：框架做增量同步时遇到已知作品会**提前 break** 迭代，
生成器的 `finally` 能保证浏览器等资源及时清理，不依赖 GC。

### 模式二：模板模式（纯 API 站点）

实现 `get_one_page()` 翻一页、把作品 dict 列表放进 `self.works`，并自己实现
`__iter__`（重置游标）与 `__next__`（当前页消费完则按 `page_interval` 限速翻
下一页，翻完即 `raise StopIteration`）。若运行在仓库内、可 import 模板基类
（`src/assets/scripts/update_a_user.py` 的 `UpdateUser`），`__iter__` /
`__next__` 可直接用基类默认实现，只写 `get_one_page()`。

### 产出条目（迭代器逐条 yield 的 dict）

| 键 | 必填 | 说明 |
|---|---|---|
| `workid` 或 `workNumber` | ✔ | 作品编号（站点内唯一标识） |
| `upTime` | | 上传时间 |
| `title` / `kind` | | 源站元数据 |
| `state` | | 源站自身状态（框架存入 otherInfo.siteState，不进下载管线） |
| `downloadDate` / `downloadPriority` | | 下载管线字段（可选） |
| `downloadInfo` | | 作品级统一下载参数（可选 dict）：与预置 `{"authorId", "workNumber"}` 合并后转 JSON 落盘，同名键以产出为准（可携带任务级 `cookies` 等，下载脚本经 `download_info` 取用） |

**产出顺序必须从新到旧**——增量同步语义依赖它。脚本不需要自己判重：迭代中每
条框架会先查 `upload` 关联，已存在即停止本位点迭代。新作品由框架写入 `works`
（state 统一 `inQueue`）并建 `upload` 关联。

### 站点配置键（update.yaml 的 site 段，可缺省）

默认值：`update_interval` 21600（±10% 抖动，`-1` 持续）、`update_thread` 1
（改动需重启）、`commit_interval` 8、`page_interval` 5（框架灌给脚本）、
`do_update` true。细节见契约文档 §4.5。

## 交付前检查清单

- [ ] `website` 与库里 `Works.website` / `PublishPos.website` 完全一致
- [ ] 文件放对目录（`scripts/download/` 或 `scripts/update/`），单文件自包含，
      不 import 项目内模块
- [ ] 所有第三方依赖都写在 `# requirements:` 头部；用 selenium 必须声明
- [ ] 没有在 `__init__` 里读取 `logger` / `config_manager` / `cookie_manager` /
      `tools` / `page_interval`（构造后才注入）
- [ ] 下载：产物写进 `download_path` 下的作品子目录，返回相对路径（或绝对路径）
- [ ] 更新：产出顺序从新到旧；每条至少含 `workid`/`workNumber`
- [ ] Selenium：`get_driver()` 用完 `quit()`；更新器浏览器场景用生成器模式
- [ ] 需要登录态的站点走 `cookie_manager`（文件）或内存 `cookies` 键；requests
      场景抄 demo 的 `normalize_cookies`；CLI 工具场景直接用
      `cookie_manager.netscape_file(website)`（见上文）
- [ ] 站点特殊节奏/参数写进 download.yaml / update.yaml 的 site 段（有 default
      兜底，可以不写）

## 参考文件（按需读，不必读框架代码）

| 文件 | 用途 |
|---|---|
| `docs/interfaces.zh-CN.md`（en 版同名） | 权威契约文档，细节冲突以它为准 |
| `src/assets/scripts/download_a_work.py` | 下载契约模板 + 部署兜底基类，docstring 与契约一一对应 |
| `src/assets/scripts/update_a_user.py` | 更新契约模板 + 部署兜底基类 |
| `demos/demo_site_downloader.py` | 可运行的下载脚本示例（cookie 三级解析、产物交付） |
| `demos/demo_site_updater.py` | 可运行的更新脚本示例（翻页、产出、cookie） |
| `demos/run_demo.py` | 本地虚拟站点一键跑通全链路，可参考其联调方式 |
