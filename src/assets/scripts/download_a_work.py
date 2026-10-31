from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Union

# 依赖声明约定：在脚本头部写 "# requirements: 包名[版本约束]"（可多行、逗号分隔），
# 框架会在加载本脚本前自动安装缺失的依赖，然后才执行脚本顶部的 import。
# 示例（放在本 docstring 外、作为真实的注释行才会生效）：
#   # requirements: requests>=2.31, beautifulsoup4


class DownloadWork:
    # 声明本类适用的站点，如 "pixiv"，也可以给列表 ["pixiv", "danbooru"]。
    # 同一文件可放多个站点的类；全部类都不声明时，本文件作为传统单站点脚本兜底。
    website = None

    config_manager = None
    logger = None
    # 框架注入：按 website 取登录 cookie。
    # cookie_manager.get(website) → [{name,value,domain,path,...}]（Selenium 兼容格式）
    # cookie_manager.get_header(website) → "k1=v1; k2=v2"（可直接作 requests 的 Cookie 头）
    cookie_manager = None

    def __init__(self, work_info, download_path, download_info=None):
        """
        下载任务初始化

        Args:
            work_info (dict): 作品信息字典，包含以下字段：
                - workNumber (str): 作品编号，站点内唯一标识
                - website (str): 作品所属站点
                - upTime (str): 上传时间
                - title (str): 作品标题
                - kind (str): 作品类型
                - state (str): 下载管线状态（inQueue/downloading/done/failed/stopped）
                - downloadDate (str): 下载日期
                - downloadPriority (int): 下载优先级
                - downloadInfo (str): 统一下载参数（JSON 文本）
            download_path (str): 本任务专属的下载目录，框架已创建好，脚本把数据写进这里即可。
                下载缓存开启时这是缓存中的工作目录（产物由框架拷贝到最终保存路径）；
                关闭时这就是最终保存目录。脚本不需要关心区别。
            download_info (dict | None): work_info 中 downloadInfo 反序列化后的字典，
                携带该作品的统一下载参数（如清晰度、格式、标签等站点相关配置），无则传空
        """
        # 基础骨架：仅保存必要状态，具体实现由子类完成
        pass

    def download_it(self) -> Union[str, Dict[str, Any]]:
        """下载入口：框架调用本方法执行下载；抛出异常即视为任务失败。

        返回值（必填）：下载产物的路径——
        - str: 产物的绝对路径，或相对 download_path 的相对路径（缓存开启时，
          框架据此把数据拷贝到最终保存路径）
        - dict: {"path": 产物路径, "duration": 秒（可选，供 waiting_play 模拟播放时长）}
        """
        pass
