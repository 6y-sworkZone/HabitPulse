from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Time, Text, DateTime, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./habit_pulse.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    avatar = Column(String, default="default.png")
    nickname = Column(String)
    bio = Column(Text)
    webhook_url = Column(String)
    webhook_type = Column(String, default="custom")
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    habits = relationship("Habit", back_populates="owner")
    checkins = relationship("Checkin", back_populates="user")
    reminder_logs = relationship("ReminderLog", back_populates="user")
    created_groups = relationship("HabitGroup", back_populates="creator")
    group_memberships = relationship("GroupMember", back_populates="user")
    group_messages = relationship("GroupMessage", back_populates="user")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, index=True)
    target = Column(String)
    frequency = Column(String)
    reminder_time = Column(Time)
    icon = Column(String)
    color = Column(String, default="#4CAF50")
    start_date = Column(Date)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="habits")
    checkins = relationship("Checkin", back_populates="habit")


class Checkin(Base):
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    habit_id = Column(Integer, ForeignKey("habits.id"))
    checkin_date = Column(Date, index=True)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="checkins")
    habit = relationship("Habit", back_populates="checkins")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    habit_id = Column(Integer, ForeignKey("habits.id"))
    message = Column(String)
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)

    user = relationship("User", back_populates="reminder_logs")


class HabitGroup(Base):
    __tablename__ = "habit_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    description = Column(Text)
    creator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="created_groups")
    members = relationship("GroupMember", back_populates="group")
    messages = relationship("GroupMessage", back_populates="group")


class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("habit_groups.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    joined_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("HabitGroup", back_populates="members")
    user = relationship("User", back_populates="group_memberships")


class GroupMessage(Base):
    __tablename__ = "group_messages"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("habit_groups.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("HabitGroup", back_populates="messages")
    user = relationship("User", back_populates="group_messages")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
