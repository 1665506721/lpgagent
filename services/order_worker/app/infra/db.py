"""数据库连接与会话管理。"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Base

_engine = None
_session_maker = None


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url == "":
        raise RuntimeError("DATABASE_URL 未配置，请设置环境变量 DATABASE_URL")
    return url


def get_engine():
    """获取 SQLAlchemy Engine 单例。"""

    global _engine
    if _engine is None:
        _engine = create_engine(_get_database_url(), pool_pre_ping=True)
    return _engine


def get_sessionmaker():
    """获取 Session 工厂。"""

    global _session_maker
    if _session_maker is None:
        _session_maker = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_maker


def init_db() -> None:
    """初始化数据库表结构。"""

    Base.metadata.create_all(get_engine())
