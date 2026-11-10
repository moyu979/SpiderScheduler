"""DownloadWork 站点脚本模板：部署骨架 + 脚本契约的唯一文档来源。

本文件会被 init_files 补装到 BASEPATH/scripts/，承担双重角色：
- 传统单文件兜底：全部脚本类都不声明 website 时，这里的 DownloadWork 对
  未路由站点兜底生效（dispatcher 的 fallback_class_name 即 "DownloadWork"）；
- 契约文档：写真实站点脚本时按本文件的约定实现即可（可继承本基类，也可
  直接新建类——分发器只认 website 属性）。可运行的行为示例见
  demos/demo_site_downloader.py（对本地虚拟站点）与 scripts/bilibili/（真实站点）。

框架约定：
- 类属性 website 声明适用的站点（须与 Works.website 一致，可给站点列表）；
- __init__(work_info, download_path, download_info=None)：
    work_info:     作品快照 {workNumber, website, upTime, title, kind, state,
                   downloadDate, downloadPriority, downloadInfo}
    download_path: 本任务专属目录（框架已建好；缓存开关对脚本透明，产物写
                   在这里并把路径返回即可）
    download_info: works.downloadInfo（JSON 文本）反序列化后的统一下载参数
- download_it() 执行下载并返回产物路径，抛出异常即任务失败：
    str:                          产物绝对路径，或相对 download_path 的相对路径
    {"path": ..., "duration": 秒}: duration 供站点 waiting_play 模拟播放时长
- 框架注入实例属性（构造完成后赋值，因此不要在 __init__ 里读取）：
    logger（SpiderLogger）、config_manager（ConfigManager 单例）、
    cookie_manager（CookieManager 类）、tools（ScriptTools，见下）

cookie 的两种传入方式（优先级：内存 > 文件 > 无）：
1. 文件传入（调度流默认）：cookie_manager 按 website 读
   BASEPATH/datas/cookies/<website>.json（前端 Cookie 页登录代理的产物）：
   - requests 直连：cookie_manager.get_header(website) → "k1=v1; k2=v2"
   - Selenium：     cookie_manager.get(website) → [{name, value, ...}] 逐条
                    add_cookie；或直接 tools.get_driver()（cookie/代理/UA 全自动）
2. 内存传入（不落盘）：works.downloadInfo 里带 "cookies" 键，框架反序列化后
   随任务直达脚本。支持 Selenium list[dict]、{name: value} dict、"k=v; k=v"
   字符串；"任务自带 cookie 优先于站点全局登录态"。

tools（src/service/script_tools.py，与任务站点绑定）：
- tools.logger / tools.log(级别, 消息)：框架日志
- tools.get_driver()：携带本站登录态的 Chrome——自动应用 system.yaml 代理与
  无头 UA 清洗（需 "# requirements: selenium"；用完 driver.quit()）
- tools.get_proxies()：requests 代理字典（未启用代理为 {}，可不加判断直接传）
- tools.site_origin()：websites.yaml 里的站点入口地址
- tools.register(name, fn)：动态注册扩展工具

依赖声明：脚本头部写 "# requirements: 包名[版本约束]"（可多行、逗号分隔），
框架在加载本脚本前自动安装缺失依赖，然后才执行脚本顶部的 import。示例：
    # requirements: requests>=2.31, beautifulsoup4
"""


class DownloadWork:
    # 声明本类适用的站点，如 "pixiv"，也可以给列表 ["pixiv", "danbooru"]。
    # 同一文件可放多个站点的类；全部类都不声明时，本文件作为传统单站点脚本兜底。
    website = None

    # 框架注入（实例属性，构造后赋值）：日志、配置、cookie 与运行时工具集。
    # cookie_manager 默认是 CookieManager 类（文件传入）；以库方式使用时可
    # 换成任何同接口对象（如 demos/in_memory_cookie_manager.py），脚本代码无需改动。
    config_manager = None
    logger = None
    cookie_manager = None
    tools = None

    def __init__(self, work_info: dict, download_path: str, download_info: dict | None = None):
        """保存任务参数，具体下载逻辑由子类实现。

        Args:
            work_info: 作品快照，关键键 workNumber（站点内唯一标识）/ website。
            download_path: 本任务专属目录，产物写在这里并返回该路径。
            download_info: downloadInfo 反序列化后的统一下载参数（如清晰度、
                格式、标签等站点相关配置）；约定其 "cookies" 键可携带任务级
                cookie（形态见模块文档），无则传空。
        """
        # 基础骨架：仅保存必要状态，具体实现由子类完成
        pass

    def download_it(self) -> str | dict:
        """下载入口：框架调用本方法执行下载；抛出异常即视为任务失败。

        Returns:
            str | dict: 下载产物的路径——
            - str: 产物的绝对路径，或相对 download_path 的相对路径（缓存开启时,
              框架据此把数据拷贝到最终保存路径）
            - dict: {"path": 产物路径, "duration": 秒（可选，供 waiting_play
              模拟播放时长）}
        """
        pass
