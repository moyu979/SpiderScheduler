"""
数据库迁移脚本目录。

约定：
- 文件命名 000N_说明.py，N 为目标 schema 版本，按序执行；
- 每个文件提供 apply(engine) 函数，用 `with engine.begin() as conn:` 写变更；
- 迁移必须幂等（先检查再改），因为全新数据库由 create_all 直接建出最新结构，
  可能跳过历史迁移；
- 每新增一个迁移，同步把 database.py 里的 HEAD_SCHEMA_VERSION +1。
"""
