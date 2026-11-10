# demos：Updater / Downloader 脚本编写示例

一套可直接运行的站点脚本编写示例，重点是 **cookie 的两种传入方式**：
文件传入（框架调度流默认）与内存传入。

## 文件一览

| 文件 | 说明 |
| --- | --- |
| `demo_site_updater.py` | `UpdateUser` 示例（website=`demo`）：翻页抓取作者作品列表，逐条产出作品 |
| `demo_site_downloader.py` | `DownloadWork` 示例（website=`demo`）：下载单个作品并返回产物路径 |
| `in_memory_cookie_manager.py` | 与 `CookieManager` 同接口的内存 cookie 载体（场景三用，可复用） |
| `run_demo.py` | 一键驱动：本地起假站点，把每种 cookie 方式各跑一遍并断言 cookie 确实送达 |

## 运行

```bash
python demos/run_demo.py
```

驱动脚本会在本地随机端口起一个 "demo 站点"（把收到的 Cookie 回显在响应里），
依次执行三个场景并输出每一步的 cookie 来源：

- **场景一（文件传入）**：`CookieManager.save()` 把 cookie 写到
  `<base_path>/datas/cookies/demo.json`（等价于前端 Cookie 页登录代理的产物），
  脚本经框架注入的 `cookie_manager` 读取。
- **场景二（内存传入）**：不读写任何 cookie 文件。updater 经 `usr["cookies"]`、
  downloader 经 `download_info["cookies"]` 直接拿到 cookie，并演示
  Selenium `list[dict]` 与 `"k=v; k=v"` 字符串两种等价形态。
- **场景三（内存注入）**：用 `InMemoryCookieManager` 顶替 `CookieManager`
  注入 `cookie_manager` 属性，脚本代码零改动。

## 两种 cookie 传入方式对照

| | 文件传入（框架默认） | 内存传入 |
| --- | --- | --- |
| cookie 来源 | 前端 Cookie 页登录代理落盘 `BASEPATH/datas/cookies/<website>.json` | 调用方随任务参数直接携带，不落盘 |
| 框架注入点 | `src/service/updater.py:276`、`src/service/downloader.py:473` 把 `CookieManager` 赋给 `instance.cookie_manager` | 无需注入；downloader 经 `works.downloadInfo` 字段随任务流转，updater 仅直接实例化时可用 |
| 脚本侧取法 | `cookie_manager.get_header(website)`（requests）；`cookie_manager.get(website)` 逐条 `add_cookie`（Selenium） | `usr["cookies"]` / `download_info["cookies"]`，支持 Selenium `list[dict]`、`{name: value}`、`"k=v; k=v"` 三种形态 |
| 适用场景 | 常规调度流：人工登录一次，全站复用 | cookie 由上游服务/外部登录流程临时持有；测试；不想落盘的嵌入式用法 |

两种方式的关键差异：

- **downloader 的内存传入在真实调度流内有效**：`works.downloadInfo` 是自由
  JSON 字段，入库时带上 `"cookies"` 键，框架反序列化后随 `download_info`
  传给脚本——cookie 随任务直达，全程不落盘。
- **updater 的内存传入只在直接实例化时有效**：框架传给 updater 脚本的位点
  快照固定为 `{authorId, website, addTime}`，没有自定义字段的通道；要把
  updater 当库调用时才用 `usr["cookies"]`。
- 两个示例脚本各自自带一份 `normalize_cookies()`（框架按单文件动态加载，
  不保证兄弟模块可 import），三种 cookie 形态都归一成 `Cookie` 请求头。

## demo 约定：解析优先级

`_resolve_cookies()` 的顺序为：**内存传入 > 文件传入 > 无 cookie（未登录请求）**，
即任务自带的 cookie 优先于站点全局登录态。抄到自己脚本里时按需调整。

## 放进框架跑

示例完全遵循框架契约（`website` 声明、构造签名、`download_it()` /
`get_one_page()` + 迭代器协议），可直接部署：

1. 把 `demo_site_updater.py` 复制到 `<basepath>/scripts/update/`、
   `demo_site_downloader.py` 复制到 `<basepath>/scripts/download/`
   （默认 basepath 是 `./docker`），分发器即按 `website="demo"` 注册；
2. 写入 website=`demo` 的发布位点即可触发更新，更新入库的作品自动进入下载队列；
3. 接真实站点时，只需替换 `get_one_page()` / `download_it()` 里的请求与解析
   逻辑，cookie 部分原样保留。
