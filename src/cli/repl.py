import cmd
import datetime as _dt
import shlex

from src.utils.database.database import DatabaseManager
from src.utils.database.models import User


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class SpiderSchedulerCmd(cmd.Cmd):
    intro = "SpiderScheduler 内置命令行。输入 help 或 ? 查看命令。"
    prompt = "SpiderScheduler> "

    def do_add_user(self, arg: str) -> None:
        """
        add-user <userId> [website]

        将用户写入数据库 user 表。
        - website 可选，默认 pixiv
        """
        try:
            parts = shlex.split(arg)
        except ValueError as e:
            self.stdout.write(f"参数解析失败: {e}\n")
            return

        if len(parts) < 1:
            self.stdout.write("用法: add-user <userId> [website]\n")
            return

        user_id = parts[0].strip()
        website = (parts[1].strip() if len(parts) >= 2 else "pixiv") or "pixiv"

        if not user_id:
            self.stdout.write("userId 不能为空\n")
            return

        with DatabaseManager.get_db_session() as session:
            exists = (
                session.query(User)
                .filter(User.userId == user_id, User.website == website)
                .first()
            )
            if exists is not None:
                self.stdout.write(f"已存在: userId={user_id} website={website}\n")
                return

            session.add(
                User(
                    userId=user_id,
                    website=website,
                    addTime=_now_iso(),
                    state="inQueue",
                )
            )

        self.stdout.write(f"已添加: userId={user_id} website={website}\n")

    # 让命令名支持 add-user（cmd 默认用方法名 do_xxx；这里做别名映射）
    def default(self, line: str) -> None:
        stripped = line.strip()
        if stripped.startswith("add-user"):
            rest = stripped[len("add-user") :].strip()
            return self.do_add_user(rest)
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

