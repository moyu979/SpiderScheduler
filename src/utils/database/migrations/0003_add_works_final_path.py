"""0003：works 表新增 finalPath 列（成功下载的产物路径）。

存相对站点级最终下载根的路径，供作品页展示与 tar 下载端点重建绝对路径。
加列即可（nullable，旧数据留 NULL），无数据搬移。

apply 须幂等：迁移的执行与版本号推进是两个事务，若在两者之间崩溃，重启会
重放本文件——列已存在时自然跳过。
"""

from sqlalchemy import text


def _columns(conn, table: str) -> set:
    """查询指定表在 SQLite 中的列名集合。"""
    return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def apply(engine):
    """执行迁移：works 缺 finalPath 列则补上，幂等可重放。

    Args:
        engine: SQLAlchemy 引擎（迁移在其上以单事务执行）。
    """
    with engine.begin() as conn:
        if "works" in {row[0] for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'"))} \
                and "finalPath" not in _columns(conn, "works"):
            conn.execute(text("ALTER TABLE works ADD COLUMN finalPath VARCHAR"))
