import time

def now_time():
    time_tuple = time.localtime(time.time())
    name=f"{time_tuple[0]:0>4}:{time_tuple[1]:0>2}:{time_tuple[2]:0>2} {time_tuple[3]:0>2}:{time_tuple[4]:0>2}:{time_tuple[5]:0>2}"
    return name
