"""0002：user 表更名为 publish_pos（发布位点），userId 列统一为 authorId。

涉及：user -> publish_pos、publish_pos.userId -> authorId、upload.userId -> authorId
（SQLite 的 RENAME 会同步更新 upload 里指向父表的外键定义）。

apply 须幂等：迁移的执行与版本号推进是两个事务，若在两者之间崩溃，重启会重放
本文件——每一步都按当前实际结构判断是否还需要执行，重放时全部自然跳过。
"""

from sqlalchemy import text


def _columns(conn, table: str) -> set:
    """查询指定表在 SQLite 中的列名集合。"""
    return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def _tables(conn) -> set:
    """查询数据库当前的全部表名集合。"""
    return {row[0] for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'"))}


def apply(engine):
    """执行迁移：按当前实际结构逐项判断并执行改名，幂等可重放。

    Args:
        engine: SQLAlchemy 引擎（迁移在其上以单事务执行）。
    """
    with engine.begin() as conn:
        tables = _tables(conn)

        # 旧库走到这里时，create_all 可能已按新模型先建出空的 publish_pos，先移除再改名
        if 'user' in tables:
            conn.execute(text("DROP TABLE IF EXISTS publish_pos"))
            conn.execute(text("ALTER TABLE user RENAME TO publish_pos"))
            tables.discard('user')
            tables.add('publish_pos')

        if 'publish_pos' in tables and 'userId' in _columns(conn, 'publish_pos'):
            conn.execute(text("ALTER TABLE publish_pos RENAME COLUMN userId TO authorId"))

        if 'upload' in tables and 'userId' in _columns(conn, 'upload'):
            conn.execute(text("ALTER TABLE upload RENAME COLUMN userId TO authorId"))
