#!/bin/sh
# SpiderScheduler 容器入口：可选从 GitHub 拉取最新代码后再启动。
#
# AUTO_UPDATE=1 时，每次容器启动先 fetch 远端（GIT_BRANCH，默认 main）并
# 硬重置到远端最新提交——/app 只由远端代码生成、无本地修改，硬重置即部署
# 镜像语义；再按 requirements.txt 的 md5 决定是否补装依赖（镜像构建时已
# 装过基线版本）。安全网：
# - 依赖装不上则回退到启动前的提交并清哈希（下次启动重试），杜绝
#   "代码新、依赖旧"的半更新态；
# - 任一步失败（断网、GitHub 不可达）都降级沿用现有代码启动，服务不因
#   更新失败而不可用。
# exec 保证 python 成为 PID 1，docker stop 的 SIGINT 直达 main.py 优雅退出。

set -u
cd /app

if [ "${AUTO_UPDATE:-0}" = "1" ]; then
    branch="${GIT_BRANCH:-main}"
    old=$(git rev-parse HEAD 2>/dev/null || echo unknown)
    if git fetch --depth 1 origin "$branch" && git reset --hard FETCH_HEAD; then
        hash_now=$(md5sum requirements.txt | cut -d' ' -f1)
        if [ "$hash_now" != "$(cat .req_hash 2>/dev/null)" ]; then
            if pip install --no-cache-dir -r requirements.txt; then
                echo "$hash_now" > .req_hash
            else
                [ "$old" != "unknown" ] && git reset --hard "$old" >/dev/null 2>&1
                rm -f .req_hash
                echo "[entrypoint] 依赖安装失败，已回退到 $old，下次启动重试" >&2
            fi
        fi
    else
        echo "[entrypoint] git fetch 失败（远端 ${branch} 不可达），沿用现有代码启动" >&2
    fi
fi

exec python main.py
