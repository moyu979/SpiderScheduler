import threading
import time
import os
import sys
import logging
from concurrent import futures

# 将当前目录加入 sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"components"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"grpc_file"))
from component import datas
from component.controller import Controller
from component.downloader import Downloader

import grpc
import spider_pb2 as spider_pb2
import spider_pb2_grpc as spider_pb2_grpc

class Server(spider_pb2_grpc.ServerServicer):
    def __init__(self):
        self.controller=Controller()
        self.downloader=Downloader()

        self.update_checker=threading.Thread(target=self.controller.daily_update)
        self.update_checker.daemon=True
        self.update_checker.start()

        logging.info(f"init finish")

    def StartDownload(self, request, context):
        answer=spider_pb2.Reply(info=f"download {request.downloadNumber} videos start")
        if self.downloader.working: 
            answer.info="already has a downloading mission"
            return answer
        if request.downloadNumber==0:
            threading.Thread(target=self.downloader.download_all).start()
        else:
            threading.Thread(target=self.downloader.download_some,kwargs={"download_number":request.downloadNumber}).start()
        return answer
    

    def StopDownload(self, request, context):
        self.downloader.continue_download=False
        while self.download.working:
            time.sleep(1)
        self.downloader.continue_download=True
        answer=spider_pb2.Reply(info="")
        return answer
    
    def DownloadUser(self, request, context):
        answer=spider_pb2.Reply(info=f"download {request.userId} user start")
        if self.downloader.working: 
            answer.info="already has a downloading mission"
            return answer
        threading.Thread(target=self.downloader.downloadUser,kwargs={"user_id":request.userId}).start()
        return answer
    

    def AddUser(self, request, context):
        threading.Thread(target=self.controller.add_a_user,kwargs={"user_id":request.userId}).start()
        answer=spider_pb2.Reply(info=f"add user {request.userId} start")
        return answer
    
    def SetPriority(self, request, context):
        self.controller.change_work_priority(request.VideoId,request.priority)
        answer=spider_pb2.Reply(info=f"set Priority {request.VideoId} success")
        return answer
    
    def Test(self, request, context):
        threading.Thread(target=self.controller.test()).start()

        answer=spider_pb2.NullMessage()
        return answer


        


# 启动 gRPC 服务器
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    spider_pb2_grpc.add_ServerServicer_to_server(Server(), server)
    server.add_insecure_port(f'[::]:{datas.conf["port"]}')  # 监听端口 50051
    logging.info(f"Server started on port {datas.conf["port"]}...")
    server.start()
    try:
        time.sleep(1000)
    except KeyboardInterrupt:
        datas.save_data()
        server.stop(0)
        return

if __name__ == '__main__':
    serve()