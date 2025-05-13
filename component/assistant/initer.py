from abc import ABC
import os
import sqlite3
import logging
from pathlib import Path
import os
import logging
import pickle


import component.assistant.data as conf
import component.assistant.BrowserFactory as BrowserFactory
import component.assistant.database as db
def init():
    init_config()  # 初始化配置
    init_database()  # 初始化数据库
    if conf.get("use_cookie"):
        init_cookie()  # 初始化cookie

def init_config():
    conf.init_config()

def init_cookie():
    BrowserFactory.BrowserFactory.init_cookie()

def init_database():
    db.Database.init_database()

              

