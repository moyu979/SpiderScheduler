import os
import sqlite3
import logging
from pathlib import Path
from component.datas import conf
def init_database():
    if not os.path.exists(conf["data_path"]):
        os.mkdir(conf["data_path"])
    dbPath=os.path.join(conf["data_path"],f"{conf["db_name"]}")
    
    if not os.path.exists(dbPath):
        logging.info(f"位于{dbPath}的数据库不存在，新建一个")
        conn=sqlite3.connect(dbPath)
        cursor=conn.cursor()
        script_dir = Path(__file__).resolve().parent.parent
        sql_script_path=os.path.join(script_dir,"resource/init.sql")
        with open(sql_script_path,"r") as script:
            sql_script=script.read()
        cursor.executescript(sql_script)
        conn.commit()
        conn.close()