"""0002：user 表更名为 publish_pos（发布位点），userId 列统一为 authorId

涉及：user -> publish_pos、publish_pos.userId -> authorId、upload.userId -> authorId
（SQLite 的 RENAME 会同步更新 upload 里指向父表的外键定义）。
"""


def apply(engine):
    from sqlalchemy import text

    with engine.begin() as conn:
        # 旧库走到这里时，create_all 可能已按新模型先建出空的 publish_pos，先移除再改名
        conn.execute(text("DROP TABLE IF EXISTS publish_pos"))
        conn.execute(text("ALTER TABLE user RENAME TO publish_pos"))
        conn.execute(text("ALTER TABLE publish_pos RENAME COLUMN userId TO authorId"))
        conn.execute(text("ALTER TABLE upload RENAME COLUMN userId TO authorId"))
