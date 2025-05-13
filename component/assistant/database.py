
import os
import logging
import sqlite3
from pathlib import Path

import component.assistant.data as conf

class Database:

    db_path = os.path.join(conf.get("data_path"), conf.get("db_name"))

    @classmethod
    def init_database(cls):
        """初始化数据库"""
        if not os.path.exists(conf.get("data_path")):
            os.mkdir(conf.get("data_path"))
        
        if not os.path.exists(cls.db_path):
            logging.info(f"位于{cls.db_path}的数据库不存在，新建一个")
            conn=sqlite3.connect(cls.db_path)
            cursor=conn.cursor()
            script_dir = Path(__file__).resolve().parent
            sql_script_path=os.path.join(script_dir,"init.sql")
            with open(sql_script_path,"r") as script:
                sql_script=script.read()
            cursor.executescript(sql_script)
            conn.commit()
            conn.close()
