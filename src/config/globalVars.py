
import os

work_path = "./docker"

download_script_path = os.path.join(work_path, "scripts", "download_a_work.py")
update_script_path = os.path.join(work_path, "scripts", "update_a_user.py")

db_path = os.path.join(work_path, "datas", "spider.db")
log_path = os.path.join(work_path, "datas", "log")

download_path = os.path.join(work_path, "datas", "download")
download_cache_path = os.path.join(work_path, "datas", "download_cache")

config_path = os.path.join(work_path, "confs")