import cmd
import os
import json
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"grpc_file"))
# 导入生成的 Python 文件
import grpc
import grpc_file.spider_pb2 as spider_pb2
import grpc_file.spider_pb2_grpc as spider_pb2_grpc

class MyCmd(cmd.Cmd):
    intro = '欢迎使用命令解释器！输入 "help" 或 "?" 查看帮助。'
    prompt = '>>> '

    def __init__(self, completekey = "tab", stdin = None, stdout = None):
        super().__init__(completekey, stdin, stdout)
        self.conf={
            "port":50051
        }
        self.do_loadConf()

        self.channal=f'localhost:{self.conf["port"]}'
        
    def do_startDownload(self, line):
        """开始下载若干个文件"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.StartDownload(spider_pb2.NullMessage())
            print(response.info)

    def do_StopDownload(self,line):
        """停止现有下载"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.StopDownload(spider_pb2.NullMessage())
            print(response.info)

    def do_AddUser(self, userId):
        """下载某个指定的用户"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.AddUser(spider_pb2.User(userId=userId))
            print(response.info)
    def do_AddWork(self, workId):
        """下载某个指定的用户"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.AddWork(spider_pb2.Work(userId=workId))
            print(response.info)
    def do_RemoveUser(self, userId):
        """下载某个指定的用户"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.RemoveUser(spider_pb2.User(userId=userId))
            print(response.info)
    def do_RemoveWork(self, workId):
        """下载某个指定的用户"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.RemoveWork(spider_pb2.Work(workId=workId))
            print(response.info)

    def do_SetPriority(self, bv):
        """将某个bv设置为优先下载"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.SetPriority(spider_pb2.Video(VideoId=bv))
            print(response.info)
    def do_GetDownloadNumber(self, line):
        """将某个bv设置为优先下载"""
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.SetPriority(spider_pb2.NullMessage())
            print(response.info)

    def do_test(self,line):
        with grpc.insecure_channel(self.channal) as channel:
            stub = spider_pb2_grpc.ServerStub(channel)
            response = stub.Test(spider_pb2.NullMessage())


if __name__ == '__main__':
    MyCmd().cmdloop()
