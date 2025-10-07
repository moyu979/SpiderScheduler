class ChangeConst(Exception):
    """尝试修改常量配置时抛出的异常"""
    pass

class SetUnknownKey(Exception):
    """尝试设置不存在的配置键时抛出的异常"""
    pass


class CookieNotExist(Exception):
    """Cookie文件不存在时抛出的异常"""
    pass
