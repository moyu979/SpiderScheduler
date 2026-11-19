"""在线自更新端点：查看状态/当前提交、触发从 GitHub 拉取最新代码、优雅热重启。

仅在容器部署下可用（支持性探测与安全网见 src/service/self_update.py）。
拉取行为与容器启动期的 AUTO_UPDATE 完全一致；热重启以 exec 自替换进程，
同一容器载入磁盘上的新代码，等效 docker restart 但无 docker 依赖。
"""

from flask import Blueprint, jsonify

from src.service.self_update import self_updater


class SelfUpdateApi:
    """在线自更新端点（/api/system/selfupdate*）。

    Attributes:
        blueprint: 挂载全部路由的 Flask 蓝图。
    """

    def __init__(self):
        """创建蓝图并注册全部路由。"""
        self.blueprint = Blueprint('selfupdate_api', __name__,
                                   url_prefix='/api/system/selfupdate')
        self._register_routes()

    def _register_routes(self):
        """注册在线自更新路由。"""

        @self.blueprint.route('/status')
        def status():
            """返回自更新状态快照（支持性、分支、前后提交、上次结果）。

            Returns:
                JSON：success 与 status 快照。
            """
            return jsonify({'success': True, 'status': self_updater.status()})

        @self.blueprint.route('/run', methods=['POST'])
        def run():
            """触发一次在线更新（后台执行，立即返回是否受理）。

            Returns:
                JSON：started=true 已受理；环境不支持/代码目录非法 400、
                已有更新进行中 409。
            """
            result = self_updater.trigger()
            if result["started"]:
                return jsonify({'success': True, **result})
            code = 409 if result.get("reason_code") == "running" else 400
            return jsonify({'success': False, **result}), code

        @self.blueprint.route('/restart', methods=['POST'])
        def restart():
            """触发一次优雅热重启（收尾在途任务后 exec 以磁盘当前代码重启）。

            注意：受理后本服务会短暂下线（收尾+重启），前端轮询 /status 会在
            重启完成后自动恢复并读到 last_applied 标记。

            Returns:
                JSON：started=true 已受理；环境不支持 400、拉取/重启进行中 409。
            """
            result = self_updater.trigger_restart()
            if result["started"]:
                return jsonify({'success': True, **result})
            code = 409 if result.get("reason_code") == "running" else 400
            return jsonify({'success': False, **result}), code
