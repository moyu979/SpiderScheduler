import threading
import time
import os
import sys
import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
from concurrent import futures

# 将当前目录加入 sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"components"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"grpc_file"))

import grpc
import spider_pb2 as spider_pb2
import spider_pb2_grpc as spider_pb2_grpc

from component.register import Register as Register
from component.updater import Updater as Updater
from component.downloader import Downloader as Downloader

import pixiv_downloader as pixiv_downloader
import pixiv_updater as pixiv_updater
import component.assistant.initer as initer

import component.assistant.data as datas
class Server(spider_pb2_grpc.ServerServicer):
    def __init__(self):
        initer.init()

        self.updater=Updater(pixiv_updater.Updater)
        self.register=Register(pixiv_updater.Updater)
        self.downloader=Downloader(pixiv_downloader.Downloader)

        logging.info(f"init finish")

    def StartDownload(self, request, context):
        answer=spider_pb2.Reply(info=f"download {request.downloadNumber} videos start")
        self.downloader.start_event.set()
        return answer
    
    def StopDownload(self, request, context):
        answer=spider_pb2.Reply(info=f"stop {request.downloadNumber} videos start")
        self.downloader.start_event.clear()
        return answer    

    def AddUser(self, request, context):
        answer=spider_pb2.Reply(info=f"add {request.userId}")
        self.register.add_a_user(request.userId)
        return answer
    def AddWork(self, request, context):
        answer=spider_pb2.Reply(info=f"add {request.WorkId}")
        self.register.add_work(request.WorkId)
        return answer
    
    def RemoveUser(self, request, context):
        answer=spider_pb2.Reply(info=f"tremove {request.userId}")
        self.register.remove_user(request.userId)
        return answer
    
    def RemoveWork(self, request, context):
        answer=spider_pb2.Reply(info=f"remove {request.WorkId}")
        self.register.remove_work(request.WorkId)
        return answer
    
    def SetPriority(self, request, context):
        answer=spider_pb2.Reply(info=f"set {request.WorkId} priority to {request.priority}")
        self.register.set_priority(request.WorkId,request.priority)
        return answer


    def GetDownloadNumber(self, request, context):
        answer=spider_pb2.Reply(info=f"already download {self.downloader._already_downloaded}")
        return answer
    
    def Test(self, request, context):
        threading.Thread(target=self.controller.test()).start()

        answer=spider_pb2.NullMessage()
        return answer


        


# 启动 gRPC 服务器
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    spider_pb2_grpc.add_ServerServicer_to_server(Server(), server)
    server.add_insecure_port(f'[::]:{datas.get("port")}')  # 监听端口 50051
    logging.info(f"Server started on port {datas.get("port")}...")
    server.start()
    while True:
        try:
            time.sleep(10)
            print(123)
        except KeyboardInterrupt:
            logging.info("Stopping the server...")
            datas.to_json()
            server.stop(0)
            return

if __name__ == '__main__':
    serve()