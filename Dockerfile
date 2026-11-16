# SpiderScheduler 部署镜像
#
# 构建：  docker compose build
#   镜像内代码不再来自构建目录，而是构建时从 GitHub main 拉取（匿名可读，
#   REPO_URL 可覆盖）。配合 AUTO_UPDATE=1（docker-compose.yml 已开），每次
#   容器启动先拉最新代码再启动；拉取/依赖安装失败自动降级沿用现有代码，
#   服务不因更新失败而不可用。
# 运行：  docker run -d --name spider -p 8300:8300 -v spider-data:/data spiderscheduler
#   或用 docker compose up -d（见 docker-compose.yml）
#
# /data 是工作目录（BASEPATH）：confs/ scripts/ datas/（数据库、日志、cookie、下载文件）
# 首次启动会自动从内置模板初始化缺失文件；数据全部落在卷里，升级镜像不丢。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    BASEPATH=/data

# git：构建时拉代码 + 运行时 AUTO_UPDATE 增量更新
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层独立：requirements 不变的提交重建镜像时缓存直接复用
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码来自 GitHub main：/app 已含 requirements.txt 不能 clone，用
# init+fetch+reset 镜像远端；基线依赖哈希落盘供 entrypoint 增量判断
ARG REPO_URL=https://github.com/moyu979/SpiderScheduler.git
RUN git init -b main /app \
    && git remote add origin "$REPO_URL" \
    && git fetch --depth 1 origin main \
    && git reset --hard FETCH_HEAD \
    && md5sum requirements.txt | cut -d' ' -f1 > .req_hash

# 非 root 运行
RUN useradd --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME /data
EXPOSE 8300

# docker stop 发送 SIGINT，走 main.py 的优雅退出（等池内任务收尾）
STOPSIGNAL SIGINT

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/', timeout=3)" || exit 1

# entrypoint.sh 随代码仓库分发（见文件头）：exec 后 python 为 PID 1，
# SIGINT 直达 main.py，优雅退出语义不变
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
