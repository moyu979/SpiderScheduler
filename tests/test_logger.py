"""日志调用方归因测试：实例方法与 classmethod 归因到用户类，及月度轮转。"""
import logging
import os
from datetime import datetime

import pytest

import src.utils.logging.logger as logger_module
from src.utils.logging.logger import SpiderLogger


@pytest.fixture(autouse=True)
def _fresh_logger(tmp_path, monkeypatch):
    """日志落到临时目录，测试结束关闭 handler 并复位全局状态"""
    monkeypatch.setattr(logger_module, '_global_log_path', lambda: str(tmp_path))
    saved_logger, saved_cache, saved_flag = (SpiderLogger._logger, SpiderLogger._log_cache,
                                             SpiderLogger._logger_initialized)
    yield tmp_path
    if SpiderLogger._logger:
        for handler in SpiderLogger._logger.handlers:
            handler.close()
        SpiderLogger._logger.handlers.clear()
    SpiderLogger._logger = saved_logger
    SpiderLogger._log_cache = saved_cache
    SpiderLogger._logger_initialized = saved_flag


def _month_log_file(tmp_path, dt=None):
    month = (dt or datetime.now()).strftime('%Y_%m')
    return os.path.join(str(tmp_path), f'{month}.log')


def test_classname_attribution(tmp_path):
    """日志按真实调用方归因：实例方法→类名，模块级函数→模块名；
    门面自身（SpiderLogger）不得再出现在归因里"""
    SpiderLogger.init_log()

    class LogProbe:
        def emit(self):
            SpiderLogger.info("probe message")

    LogProbe().emit()

    def module_level_emit():
        SpiderLogger.info("module message")

    module_level_emit()

    content = open(_month_log_file(tmp_path), encoding='utf-8').read()
    probe_line = next(line for line in content.splitlines() if "probe message" in line)
    module_line = next(line for line in content.splitlines() if "module message" in line)
    assert "[LogProbe]" in probe_line
    assert "[SpiderLogger]" not in probe_line
    assert "[test_logger]" in module_line  # 无 self/cls 时回落模块名


def test_classmethod_caller_attribution(tmp_path):
    """用户的 classmethod 调日志时按其类归因（cls 不是 SpiderLogger 的帧正常返回）"""
    SpiderLogger.init_log()

    class ClsProbe:
        @classmethod
        def emit(cls):
            SpiderLogger.info("cls probe message")

    ClsProbe.emit()

    content = open(_month_log_file(tmp_path), encoding='utf-8').read()
    line = next(line for line in content.splitlines() if "cls probe message" in line)
    assert "[ClsProbe]" in line


def test_month_change_switches_log_file(tmp_path):
    """跨月检查生效：handler 文件名落后于当前月份时自动重建到新月文件"""
    real_datetime = logger_module.datetime

    class _FakePastDatetime:
        @classmethod
        def now(cls):
            return real_datetime(2027, 1, 15, 10, 0, 0)

    # 用假时间初始化：handler 落在 2027_01.log（手动换入/换出，
    # 避免与 fixture 共用的 monkeypatch.undo 相互影响）
    logger_module.datetime = _FakePastDatetime
    try:
        SpiderLogger.init_log()
    finally:
        logger_module.datetime = real_datetime

    # 恢复真实时间后写日志 → 应触发跨月检查并切换到当前月
    SpiderLogger.info("message in current month")

    handler = next(h for h in SpiderLogger.getLogger().handlers
                   if isinstance(h, logging.FileHandler))
    assert handler.baseFilename == _month_log_file(tmp_path)  # 已切回当前月
    content = open(_month_log_file(tmp_path), encoding='utf-8').read()
    assert "message in current month" in content
