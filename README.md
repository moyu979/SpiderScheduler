# SpiderScheduler
这是一个python编写的爬虫框架，写着玩的，主功能就是监听指定网站的指定用户，main分支是框架本体，pixiv分支是一个爬pixiv的实现

# 怎么用：

服务端：

    python server.py

控制端，直接

    python spidercmd.py <cmd> <paras>

具体的命令懒得写了，直接去看源文件吧

# 怎么开发

重写

    component.template.update_a_user
    component.template.download_a_work

两个类，然后在server里传一下就行了

        self.updater=Updater(pixiv_updater.Updater)
        self.register=Register(pixiv_updater.Updater)
        self.downloader=Downloader(pixiv_downloader.Downloader)

