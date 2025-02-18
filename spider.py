import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# import component.controller as con

# controller=con.Controller()
# controller.change_work_priority(1233,-1)

import component.downloader as dow

downloader=dow.Downloader()
downloader.download_wanted(1224)