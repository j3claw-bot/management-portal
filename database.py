import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

DB_PATH = os.environ.get("DB_PATH", "data/portal.db")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_login = Column(DateTime, nullable=True)
    login_count = Column(Integer, default=0, nullable=False)

    login_history = relationship(
        "LoginEvent", back_populates="user", order_by="LoginEvent.logged_in_at.desc()"
    )


class LoginEvent(Base):
    __tablename__ = "login_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    logged_in_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    ip_address = Column(String(45), nullable=True)

    user = relationship("User", back_populates="login_history")


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()
