import logging

def show_process(func):
    def wrapper(*args, **kwargs):
        logging.debug(f"{func.__name__} start")
        result = func(*args, **kwargs)
        logging.debug(f"{func.__name__} end")
        return result
    return wrapper


def decorate_all_methods(cls):
    for attr_name, attr_value in cls.__dict__.items():
        if callable(attr_value):  # 检查该属性是否为可调用对象（即方法）
            setattr(cls, attr_name, show_process(attr_value))  # 给方法加装饰器
    return cls