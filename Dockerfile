# SpiderScheduler 部署镜像
#
# 构建：  docker build -t spiderscheduler .
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

# tzdata：让日志时间戳使用本地时区
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY src/ src/

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

CMD ["python", "main.py"]
