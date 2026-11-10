"""ORM 模型定义。

三张表构成"更新→入库→下载"管线的存储核心：
- Works：作品（下载队列），联合主键 (workNumber, website)；
- PublishPos：发布位点（作者追踪），联合主键 (authorId, website)；
- Upload：作者↔作品关联，联合主键 (website, authorId, workNumber)，
  两条复合外键分别指向 PublishPos 与 Works。

schema 变更走 migrations/（见 database.py 的 HEAD_SCHEMA_VERSION），
本文件始终保持与最新结构一致。
"""

from sqlalchemy import Column, ForeignKeyConstraint, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Works(Base):
    """作品表（下载队列）。

    Attributes:
        workNumber: 作品编号（站点内唯一标识），联合主键之一。
        website: 所属站点名，联合主键之一。
        upTime: 作品在源站的发布时间（ISO 或空串）。
        title: 作品标题。
        kind: 作品类型（站点自定义，如 vip/normal 或页面徽标文本）。
        state: 下载管线状态：inQueue → downloading → done/failed，stopped
            可随时由 API 置入；NULL 视为 inQueue（兼容旧数据）。源站自身的
            作品状态存 otherInfo 的 siteState 键。
        downloadDate: 下载完成时间（ISO 字符串）。
        downloadPriority: 下载优先级，认领时按其降序取最前。
        otherInfo: 源站附加信息（JSON 文本，含 siteState）。
        downloadInfo: 统一下载参数（JSON 文本），下载时反序列化传给脚本。
        uploads: 与 Upload 的只读导航关系（写入统一显式构造 Upload）。
    """

    __tablename__ = "works"

    workNumber = Column(String, primary_key=True)  # 联合主键的一部分
    website = Column(String, primary_key=True)  # 联合主键的一部分
    upTime = Column(String, default="")
    title = Column(String)
    kind = Column(String)
    # 下载管线状态: inQueue -> downloading -> done/failed，stopped 可随时置入；
    # NULL 视为 inQueue（兼容旧数据）。源站自身的作品状态存 otherInfo 的 siteState 键
    state = Column(String)
    downloadDate = Column(String)
    downloadPriority = Column(Integer, default=0)
    otherInfo = Column(String)
    downloadInfo = Column(String)  # 统一下载参数，JSON 文本

    # 与 upload 关联（只读导航；写入统一显式构造 Upload，避免两条复合外键共享 website 列的写方向歧义）
    uploads = relationship("Upload", back_populates="work", viewonly=True)

    def __repr__(self):
        """返回便于日志排查的对象摘要。"""
        return f"<Works(workNumber={self.workNumber}, website={self.website}, title={self.title})>"


class PublishPos(Base):
    """发布位点：对某站点某作者的追踪位点（原 user 表）。

    更新器以位点为单位遍历作者的作品流，upload 关联隐式记录已同步到哪里。

    Attributes:
        authorId: 作者标识（站点内），联合主键之一。
        website: 所属站点名，联合主键之一。
        addTime: 添加追踪的时间（ISO 字符串）。
        state: 追踪状态：inQueue / stopped，stopped 的位点不参与更新。
        uploads: 与 Upload 的只读导航关系（写入统一显式构造 Upload）。
    """

    __tablename__ = "publish_pos"

    authorId = Column(String, primary_key=True)  # 作者标识（站点内）
    website = Column(String, primary_key=True)
    addTime = Column(String)
    state = Column(String, default="inQueue")  # inQueue / stopped，stopped 的位点不参与更新

    # 与 upload 关联（同 works，只读导航）
    uploads = relationship("Upload", back_populates="pos", viewonly=True)

    def __repr__(self):
        """返回便于日志排查的对象摘要。"""
        return f"<PublishPos(authorId={self.authorId}, website={self.website})>"


class Upload(Base):
    """作者↔作品关联表：一个作者（位点）与一个作品的同步关系。

    两条复合外键共享 website 列，均设为 DEFERRABLE INITIALLY DEFERRED：
    ORM 同批次 flush 时无法保证父表先插入，把约束检查推迟到 commit，
    插入顺序不再敏感，孤儿数据依然会被拒绝。

    Attributes:
        website: 站点名，联合主键之一，同时是两条外键的共享列。
        authorId: 作者标识，联合主键之一。
        workNumber: 作品编号，联合主键之一。
        pos: 指向 PublishPos 的只读导航关系。
        work: 指向 Works 的只读导航关系。
    """

    __tablename__ = "upload"

    # 联合主键
    website = Column(String, primary_key=True)
    authorId = Column(String, primary_key=True)
    workNumber = Column(String, primary_key=True)

    # 复合外键：引用必须覆盖父表的完整主键 (id, website)，单列外键在严格外键模式下不合法。
    # DEFERRABLE：两条外键共享 website 列，ORM 同批次 flush 时无法保证父表先插入，
    # 把约束检查推迟到 commit，插入顺序不再敏感，孤儿数据依然会被拒绝
    __table_args__ = (
        ForeignKeyConstraint(['authorId', 'website'], ['publish_pos.authorId', 'publish_pos.website'],
                             deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(['workNumber', 'website'], ['works.workNumber', 'works.website'],
                             deferrable=True, initially="DEFERRED"),
    )

    # ORM 关系
    pos = relationship("PublishPos", back_populates="uploads", viewonly=True)
    work = relationship("Works", back_populates="uploads", viewonly=True)

    def __repr__(self):
        """返回便于日志排查的对象摘要。"""
        return f"<Upload(website={self.website}, authorId={self.authorId}, workNumber={self.workNumber})>"
