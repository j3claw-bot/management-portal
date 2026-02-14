import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
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


class LocalMail(Base):
    __tablename__ = "local_mail"

    id = Column(Integer, primary_key=True)
    to_email = Column(String(255), nullable=False, index=True)
    subject = Column(String(500), nullable=False)
    body_text = Column(Text, nullable=False)
    sent_via_smtp = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    actor = Column(String(80), nullable=False)
    action = Column(String(50), nullable=False, index=True)
    target = Column(String(120), nullable=True)
    detail = Column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False, default="")


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


def audit(actor: str, action: str, target: str | None = None, detail: str | None = None):
    session = get_session()
    try:
        session.add(AuditLog(actor=actor, action=action, target=target, detail=detail))
        session.commit()
    finally:
        session.close()


def get_setting(key: str, default: str = "") -> str:
    session = get_session()
    try:
        row = session.query(Setting).get(key)
        return row.value if row else default
    finally:
        session.close()


def set_setting(key: str, value: str):
    session = get_session()
    try:
        row = session.query(Setting).get(key)
        if row:
            row.value = value
        else:
            session.add(Setting(key=key, value=value))
        session.commit()
    finally:
        session.close()
