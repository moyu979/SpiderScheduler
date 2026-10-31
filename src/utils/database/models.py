from sqlalchemy import Column, String, Integer, ForeignKeyConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Works(Base):
    """
    作品表
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
        return f"<Works(workNumber={self.workNumber}, website={self.website}, title={self.title})>"


class PublishPos(Base):
    """
    发布位点：对某站点某作者的追踪位点（原 user 表）。
    更新器以位点为单位遍历作者的作品流，upload 关联隐式记录已同步到哪里。
    """
    __tablename__ = "publish_pos"

    authorId = Column(String, primary_key=True)  # 作者标识（站点内）
    website = Column(String, primary_key=True)
    addTime = Column(String)
    state = Column(String, default="inQueue")  # inQueue / stopped，stopped 的位点不参与更新

    # 与 upload 关联（同 works，只读导航）
    uploads = relationship("Upload", back_populates="pos", viewonly=True)

    def __repr__(self):
        return f"<PublishPos(authorId={self.authorId}, website={self.website})>"


class Upload(Base):
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
        return f"<Upload(website={self.website}, authorId={self.authorId}, workNumber={self.workNumber})>"
