"""UpdateUser 站点脚本模板：部署骨架 + 脚本契约的唯一文档来源。

本文件会被 init_files 补装到 BASEPATH/scripts/，承担双重角色：
- 传统单文件兜底：全部脚本类都不声明 website 时，这里的 UpdateUser 对未
  路由站点兜底生效（dispatcher 的 fallback_class_name 即 "UpdateUser"）；
- 契约文档：写真实站点脚本时按本文件的约定实现即可。可运行的行为示例见
  demos/demo_site_updater.py（本地虚拟站点）与 scripts/bilibili/（真实站点）。

框架约定：
- 类属性 website 声明适用的站点（须与 PublishPos.website 一致，可给站点列表）；
- __init__(usr, logging)：usr 是位点快照 {authorId, website, addTime}（框架
  传入，仅此三个字段）；logging 是框架日志对象（SpiderLogger）；
- 迭代器协议逐条产出作品字典，按"从新到旧"顺序（至少含 workid 或
  workNumber，其余键可选）：upTime / title / kind / state（框架存入
  otherInfo.siteState）/ downloadDate / downloadPriority；
- 增量同步交给框架：发现该作品的 upload 关联已存在时，框架自动停止本位点
  迭代——脚本只需保证产出顺序从新到旧；
- 框架注入实例属性（构造完成后赋值）：cookie_manager（CookieManager 类）、
  tools（ScriptTools，见下）。

两种实现模式：
1. 模板模式（本文件）：实现 get_one_page() 翻一页、把结果放进 self.works，
   迭代协议用基类的默认 __iter__/__next__；
2. 生成器模式（浏览器场景推荐）：__iter__ 返回生成器——框架做增量同步会
   提前 break，生成器的 finally 能保证浏览器等资源及时清理，不依赖 GC。

cookie 的两种传入方式（优先级：内存 > 文件 > 无）：
1. 文件传入（调度流默认）：cookie_manager 按 website 读
   BASEPATH/datas/cookies/<website>.json；requests 直连用
   get_header(website)，Selenium 用 get(website) 逐条 add_cookie 或直接
   tools.get_driver()（cookie/代理/UA 全自动）；
2. 内存传入（把脚本当库直接实例化时）：usr["cookies"] 携带 cookie——该键
   不是框架字段，仅供绕过调度器直接实例化时使用；支持 Selenium list[dict]、
   {name: value} dict、"k=v; k=v" 字符串。

tools（src/service/script_tools.py，与位点站点绑定）：tools.logger、
tools.get_driver()（自动应用 system.yaml 代理）、tools.get_proxies()、
tools.site_origin()、tools.register(name, fn)。

依赖声明：脚本头部写 "# requirements: 包名[版本约束]"，框架加载前自动安装。
"""


class UpdateUser:
    # 声明本类适用的站点，如 "pixiv"，也可以给列表 ["pixiv", "danbooru"]。
    # 同一文件可放多个站点的类；全部类都不声明时，本文件作为传统单站点脚本兜底。
    website = None

    # 框架注入（实例属性，构造后赋值）：cookie 入口、运行时工具集与翻页限速。
    # cookie_manager 默认是 CookieManager 类（文件传入）；以库方式使用时可
    # 换成任何同接口对象（如 demos/in_memory_cookie_manager.py），脚本代码无需改动。
    cookie_manager = None
    tools = None
    # 翻页间隔（秒）：来自 update.yaml 的 site.<website>.page_interval（未配置 5），
    # 由框架解析后灌入——分页由脚本控制，请在两次取页之间 sleep 本值；
    # 纯 API 站点可忽略。直接实例化（未注入）时为 None，脚本自行决定节奏。
    page_interval = None

    def __init__(self, usr: dict, logging):
        """保存位点信息，具体抓取逻辑由子类实现。

        Args:
            usr: 位点快照 {authorId, website, addTime}；直接实例化时可额外
                约定 usr["cookies"] 携带 cookie（见模块文档）。
            logging: 框架日志对象（SpiderLogger），用法同 logger.info(...)。
        """
        # 基础框架：仅保存必要状态，具体逻辑由子类实现
        self.author_id = usr.get('authorId') if isinstance(usr, dict) else None
        self.website = usr.get('website') if isinstance(usr, dict) else None
        self.page = 1
        self.works = []

    def get_one_page(self) -> None:
        """翻取一页作品列表，结果放进 self.works（模板模式的实现点）。"""
        pass

    def __iter__(self):
        """重置为初始状态（框架对每个位点都重新迭代一次）。"""
        # 重置为初始状态
        self.page = 1
        self.works = []
        return self

    def __next__(self):
        """迭代协议：当前页消费完则翻下一页；翻页后仍无数据即结束。"""
        # 若当前无数据，请求下一页
        if len(self.works) == 0:
            self.get_one_page()
            self.page += 1
        # 若仍无数据，则视为迭代结束
        if len(self.works) == 0:
            raise StopIteration
        # 返回一个条目（应为字典，以适配上游处理）
        return self.works.pop(0)
