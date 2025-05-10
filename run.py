import threading
from time import sleep
import component.assistant.initer
import logging
from component.need_to_rewrite.update_a_user import UpdateUser
from component.updater import Updater as Updater
import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
component.assistant.initer.init()

class UpdaterOne(UpdateUser):
    def __init__(self,uid):
        super().__init__(uid)

    def get_one_page(self):
        logging.info(f"get user {self.uid} page {self.page}")
        if self.page==1:
            self.works=[(0,i,"test","normal","inQueue",None,None) for i in range(10)]

updater=Updater(UpdaterOne(0))
updater.auto_update_start()
print("---")
# 创建线程
t = threading.Thread(target=updater.daily_update)

# 启动线程
t.start()
sleep(15)
updater.auto_update_stop()
print("stop")
sleep(10)
#updater.update_a_user(123456789)

