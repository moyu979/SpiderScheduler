import cmd
import datetime as _dt
import shlex

from src.utils.database.database import DatabaseManager
from src.utils.database.models import PublishPos


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class SpiderSchedulerCmd(cmd.Cmd):
    intro = "SpiderScheduler 内置命令行。输入 help 或 ? 查看命令。"
    prompt = "SpiderScheduler> "

    def do_add_pos(self, arg: str) -> None:
        """
        add-pos <authorId> [website]

        添加发布位点（写入 publish_pos 表）。
        - website 可选，默认 pixiv
        - 兼容旧命令名 add-user
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
        stripped = line.strip()
        for alias, target in (("add-pos", "add_pos"), ("add-user", "add_pos")):
            if stripped.startswith(alias):
                rest = stripped[len(alias):].strip()
                return getattr(self, f"do_{target}")(rest)
        return super().default(line)

    def do_exit(self, arg: str) -> bool:  # type: ignore[override]
        """退出命令行（exit）"""
        return True

    def do_quit(self, arg: str) -> bool:  # type: ignore[override]
        """退出命令行（quit）"""
        return True

    def do_EOF(self, arg: str) -> bool:  # type: ignore[override]
        """Ctrl+D 退出"""
        self.stdout.write("\n")
        return True


def run_repl() -> None:
    SpiderSchedulerCmd().cmdloop()

