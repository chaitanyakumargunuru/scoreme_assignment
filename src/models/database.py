"""
Database models using SQLAlchemy ORM.
SQLite is used for simplicity; swap connection string for Postgres in production.
"""
import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./workflow_platform.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency injection for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class WorkflowRequest(Base):
    """
    Core table tracking each incoming request through its lifecycle.
    request_id acts as the idempotency key — duplicate submissions return the same result.
    """
    __tablename__ = "workflow_requests"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    request_id   = Column(String(64), unique=True, nullable=False, index=True)
    workflow_type= Column(String(64), nullable=False)
    payload      = Column(JSON, nullable=False)
    status       = Column(String(32), nullable=False, default="PENDING")
    current_stage= Column(String(64), nullable=True)
    retry_count  = Column(Integer, default=0)
    created_at   = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at   = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))


class StateHistory(Base):
    """
    Immutable log of every status transition for a request.
    Enables full lifecycle reconstruction and debugging.
    """
    __tablename__ = "state_history"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    request_id  = Column(String(64), nullable=False, index=True)
    from_status = Column(String(32))
    to_status   = Column(String(32), nullable=False)
    stage       = Column(String(64))
    notes       = Column(Text)
    timestamp   = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))


class AuditLog(Base):
    """
    Explainable audit trail: records which rules were evaluated,
    whether they passed or failed, and the final decision with reasoning.
    """
    __tablename__ = "audit_logs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    request_id      = Column(String(64), nullable=False, index=True)
    event_type      = Column(String(64))       # e.g. RULE_EVAL, STAGE_TRANSITION, EXTERNAL_CALL
    stage           = Column(String(64))
    rules_evaluated = Column(JSON)             # [{rule_id, passed, reason, value_checked}]
    decision        = Column(String(32))       # APPROVED / REJECTED / MANUAL_REVIEW / RETRY
    details         = Column(Text)
    timestamp       = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))