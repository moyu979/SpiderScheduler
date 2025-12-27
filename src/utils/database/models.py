from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Works(Base):
    """
    作品表
    """
    __tablename__ = "works"

    workNumber = Column(String, primary_key=True)  # 唯一标识
    upTime = Column(String, default="")
    title = Column(String)
    kind = Column(String)
    state = Column(String)
    downloadDate = Column(String)
    downloadPriority = Column(Integer, default=0)

    # 与 upload 关联
    uploads = relationship("Upload", back_populates="work")

    def __repr__(self):
        return f"<Works(workNumber={self.workNumber}, title={self.title})>"


class User(Base):
    __tablename__ = "user"

    userId = Column(String, primary_key=True)  # 唯一标识
    addTime = Column(String)
    state = Column(String, default="inQueue")

    # 与 upload 关联
    uploads = relationship("Upload", back_populates="user")

    def __repr__(self):
        return f"<User(userId={self.userId})>"


class Upload(Base):
    __tablename__ = "upload"

    # 联合主键
    userId = Column(String, ForeignKey("user.userId"), primary_key=True, nullable=False)
    workNumber = Column(String, ForeignKey("works.workNumber"), primary_key=True)
    
    # 可选：保留唯一约束，但联合主键已经保证唯一性
    __table_args__ = (
        UniqueConstraint("userId", "workNumber", name="uix_user_work"),
    )

    # ORM 关系
    user = relationship("User", back_populates="uploads")
    work = relationship("Works", back_populates="uploads")

    def __repr__(self):
        return f"<Upload(userId={self.userId}, workNumber={self.workNumber})>"

