import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

KITA_DB_PATH = os.environ.get("KITA_DB_PATH", "data/kita.db")


class Base(DeclarativeBase):
    pass


class KitaSettings(Base):
    __tablename__ = "kita_settings"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    open_time = Column(String(5), nullable=False, default="07:00")
    close_time = Column(String(5), nullable=False, default="17:00")
    core_start = Column(String(5), nullable=False, default="09:00")
    core_end = Column(String(5), nullable=False, default="15:00")


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    area = Column(String(20), nullable=False)  # "krippe" or "elementar"
    min_children = Column(Integer, nullable=False, default=0)
    max_children = Column(Integer, nullable=False)
    ratio_num = Column(Integer, nullable=False, default=1)
    ratio_den = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    attendances = relationship("ChildAttendance", back_populates="group", cascade="all, delete-orphan")
    shifts = relationship("Shift", back_populates="group")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    role = Column(String(20), nullable=False)  # "erstkraft" or "zweitkraft"
    area = Column(String(20), nullable=False)  # "krippe", "elementar", or "both"
    contract_hours = Column(Float, nullable=False)
    days_per_week = Column(Integer, nullable=False, default=5)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    restrictions = relationship("EmployeeRestriction", back_populates="employee", cascade="all, delete-orphan")
    absences = relationship("Absence", back_populates="employee", cascade="all, delete-orphan")
    shifts = relationship("Shift", back_populates="employee")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class EmployeeRestriction(Base):
    __tablename__ = "employee_restrictions"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    restriction_type = Column(String(30), nullable=False)
    value = Column(String(100), nullable=False)

    employee = relationship("Employee", back_populates="restrictions")


class Absence(Base):
    __tablename__ = "absences"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    absence_type = Column(String(20), nullable=False)  # "urlaub", "krank", "fortbildung", "sonstig"
    note = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    employee = relationship("Employee", back_populates="absences")


class ChildAttendance(Base):
    __tablename__ = "child_attendance"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    weekday = Column(Integer, nullable=False)  # 0=Mon..4=Fri
    expected_children = Column(Integer, nullable=False)
    arrival_time = Column(String(5), nullable=False, default="07:00")
    departure_time = Column(String(5), nullable=False, default="17:00")

    group = relationship("Group", back_populates="attendances")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True)
    week_start = Column(Date, nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="draft")
    score_compliance = Column(Integer, default=0)
    score_coverage = Column(Integer, default=0)
    score_fairness = Column(Integer, default=0)
    score_preference = Column(Integer, default=0)
    score_continuity = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    published_at = Column(DateTime, nullable=True)

    shifts = relationship("Shift", back_populates="schedule", cascade="all, delete-orphan")


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    weekday = Column(Integer, nullable=False)  # 0=Mon..4=Fri
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    break_start = Column(String(5), nullable=True)
    break_minutes = Column(Integer, default=0)
    is_manual = Column(Boolean, default=False, nullable=False)

    schedule = relationship("Schedule", back_populates="shifts")
    employee = relationship("Employee", back_populates="shifts")
    group = relationship("Group", back_populates="shifts")


# Database engine management

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        os.makedirs(os.path.dirname(KITA_DB_PATH) or ".", exist_ok=True)
        _engine = create_engine(f"sqlite:///{KITA_DB_PATH}", echo=False)
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()
