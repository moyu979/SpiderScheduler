"""内置命令行（REPL）。

提供交互式的轻量管理入口，适合不方便开网页时快速操作：
- add-pos：添加发布位点（等价于 POST /api/update/add_pos）；
- exit / quit：退出；Ctrl+D 同退出。

命令的数据库写入路径与 REST API/网页完全一致（复用同一批模型与配置），
保证任何入口的行为语义统一。
"""

import cmd
import datetime as _dt
import shlex

from src.utils.database.database import DatabaseManager
from src.utils.database.models import PublishPos


def _now_iso() -> str:
    """当前时间的 ISO 字符串（秒级精度），用作位点的 addTime。"""
    return _dt.datetime.now().isoformat(timespec="seconds")


class SpiderSchedulerCmd(cmd.Cmd):
    """SpiderScheduler 交互命令行。

    旧命令别名（add-user）通过 default() 做映射以保持兼容。

    Attributes:
        intro: 进入交互模式时打印的欢迎语。
        prompt: 命令提示符。
    """

    intro = "SpiderScheduler 内置命令行。输入 help 或 ? 查看命令。"
    prompt = "SpiderScheduler> "

    def do_add_pos(self, arg: str) -> None:
        """添加发布位点。

        用法: add-pos <authorId> [website]

        写入 publish_pos 表（state=inQueue）；已存在（同 authorId+website）时提示。
        兼容旧命令名 add-user。

        Args:
            arg: 空格分隔的参数；authorId 必填，website 可选（默认 pixiv）。
        """
        try:
            parts = shlex.split(arg)
        except ValueError as e:
            self.stdout.write(f"参数解析失败: {e}\n")
            return

        if len(parts) < 1:
            self.stdout.write("用法: add-pos <authorId> [website]\n")
            return

        author_id = parts[0].strip()
        website = (parts[1].strip() if len(parts) >= 2 else "pixiv") or "pixiv"

        if not author_id:
            self.stdout.write("authorId 不能为空\n")
            return

        with DatabaseManager.get_db_session() as session:
            exists = (
                session.query(PublishPos)
                .filter(PublishPos.authorId == author_id, PublishPos.website == website)
                .first()
            )
            if exists is not None:
                self.stdout.write(f"已存在: authorId={author_id} website={website}\n")
                return

            session.add(
                PublishPos(
                    authorId=author_id,
                    website=website,
                    addTime=_now_iso(),
                    state="inQueue",
                )
            )

        self.stdout.write(f"已添加: authorId={author_id} website={website}\n")

    # 命令别名映射（cmd 默认用方法名 do_xxx）
    def default(self, line: str) -> None:
        """处理未识别命令：把 add-pos / add-user 别名映射到 do_add_pos。"""
        stripped = line.strip()
        for alias, target in (("add-pos", "add_pos"), ("add-user", "add_pos")):
            if stripped.startswith(alias):
                rest = stripped[len(alias):].strip()
                return getattr(self, f"do_{target}")(rest)
        return super().default(line)

    def do_exit(self, arg: str) -> bool:  # type: ignore[override]
        """退出命令行（exit）。

        Returns:
            bool: True，令 cmd.Cmd 结束命令循环。
        """
        return True

    def do_quit(self, arg: str) -> bool:  # type: ignore[override]
        """退出命令行（quit）。

        Returns:
            bool: True，令 cmd.Cmd 结束命令循环。
        """
        return True

    def do_EOF(self, arg: str) -> bool:  # type: ignore[override]
        """Ctrl+D 退出。

        Returns:
            bool: True，令 cmd.Cmd 结束命令循环。
        """
        self.stdout.write("\n")
        return True


def run_repl() -> None:
    """启动 REPL 事件循环（阻塞直到退出命令）。"""
    SpiderSchedulerCmd().cmdloop()

