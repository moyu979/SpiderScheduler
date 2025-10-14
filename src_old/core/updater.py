
from src.logger import logger
from src.configs.globalVars import update_script_path
from src.py_utils.dynamic_loader import load_class_from_file
from src.py_utils.BlockingThreadPoolExecutor import BlockingThreadPoolExecutor
import src.configs.config as config

class Updater:
    """
    用户更新器
    每隔配置中的check_interval时间，检查数据库中所有用户的uid，
    为每个用户创建对应的update_a_user类实例，使用迭代器方式检查更新
    """
    def __init__(self):
        logger.info("Updater初始化开始")
        
        # 动态加载UpdateUser类，用于特定用户的更新
        self.update_user_class = load_class_from_file(update_script_path, "UpdateUser")
        
        # 获取配置
        self.update_thread = config.get('update_setting', 'update_thread')
        self.check_interval = config.get('update_setting','check_interval')

        # 创建线程池
        self.executor = BlockingThreadPoolExecutor(
            max_workers=self.update_thread, 
            name="UserUpdater"
        )


        logger.info("Updater初始化完成")