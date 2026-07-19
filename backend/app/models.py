# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
SQLAlchemy ORM models for OneSearch
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


def _utcnow():
    """Return current UTC time as naive datetime (for SQLite Column defaults)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

Base = declarative_base()


class Agent(Base):
    """A remote indexing agent enrolled with this OneSearch server."""

    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(
            "default_processing_mode IN ('on_agent', 'on_server')",
            name="ck_agents_default_processing_mode",
        ),
    )

    id = Column(String, primary_key=True)
    name = Column(String(120), nullable=False)
    platform = Column(String(80), nullable=False)
    version = Column(String(40), nullable=False)
    protocol_version = Column(Integer, nullable=False)
    token_hash = Column(String(64), unique=True, nullable=True)
    allowed_roots = Column(Text, nullable=False, default="[]", server_default="[]")
    default_processing_mode = Column(
        String, nullable=False, default="on_agent", server_default="on_agent"
    )
    auto_update = Column(Boolean, nullable=False, default=False, server_default="0")
    status = Column(String, nullable=False, default="pending", server_default="pending")
    approved_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    sources = relationship("Source", back_populates="agent", passive_deletes=True)
    jobs = relationship("AgentJob", back_populates="agent", passive_deletes=True)


class AgentEnrollment(Base):
    """Single-use enrollment code metadata; plaintext codes are never stored."""

    __tablename__ = "agent_enrollments"

    id = Column(String, primary_key=True)
    code_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    created_by_user = relationship("User", back_populates="agent_enrollments")


class Source(Base):
    """
    Source configuration table
    Stores information about configured search sources
    """
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "location_type IN ('local', 'agent')",
            name="ck_sources_location_type",
        ),
        CheckConstraint(
            "processing_mode IS NULL OR processing_mode IN ('on_agent', 'on_server')",
            name="ck_sources_processing_mode",
        ),
        CheckConstraint(
            "(location_type = 'local' AND agent_id IS NULL) OR "
            "(location_type = 'agent' AND agent_id IS NOT NULL)",
            name="ck_sources_location_agent",
        ),
    )

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False)
    location_type = Column(String, nullable=False, default="local", server_default="local")
    agent_id = Column(
        String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    processing_mode = Column(String, nullable=True)
    include_patterns = Column(Text, nullable=True)  # JSON array as text
    exclude_patterns = Column(Text, nullable=True)  # JSON array as text
    scan_schedule = Column(String, nullable=True)  # Cron expression or preset (@hourly, @daily, @weekly)
    schedule_type = Column(String, nullable=False, default="cron", server_default="cron")  # "cron" or "interval"
    interval_value = Column(Integer, nullable=True)  # Used when schedule_type == "interval"
    interval_unit = Column(String, nullable=True)  # "minutes" | "hours" | "days"
    use_default_schedule = Column(Boolean, nullable=False, default=False, server_default="0")
    last_scan_at = Column(DateTime, nullable=True)
    next_scan_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relationship to indexed files
    indexed_files = relationship("IndexedFile", back_populates="source", cascade="all, delete-orphan")
    agent = relationship("Agent", back_populates="sources")
    agent_jobs = relationship("AgentJob", back_populates="source", passive_deletes=True)

    def __repr__(self):
        return f"<Source(id={self.id}, name={self.name}, path={self.root_path})>"


class IndexedFile(Base):
    """
    Indexed files tracking table
    Tracks metadata for incremental indexing
    """
    __tablename__ = "indexed_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String, nullable=False, index=True)
    size_bytes = Column(Integer, nullable=True)
    modified_at = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, nullable=False, default=_utcnow)
    hash = Column(String, nullable=True)  # File content hash for change detection
    status = Column(String, default="success", nullable=False)  # success, failed, skipped
    error_message = Column(Text, nullable=True)

    # Relationship to source
    source = relationship("Source", back_populates="indexed_files")

    def __repr__(self):
        return f"<IndexedFile(id={self.id}, source={self.source_id}, path={self.path}, status={self.status})>"


class AgentJob(Base):
    """Durable unit of work leased to an agent."""

    __tablename__ = "agent_jobs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('scan', 'browse', 'extract_file', 'stream_file')",
            name="ck_agent_jobs_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'leased', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_jobs_status",
        ),
        CheckConstraint(
            "processing_mode IS NULL OR processing_mode IN ('on_agent', 'on_server')",
            name="ck_agent_jobs_processing_mode",
        ),
        UniqueConstraint("active_key", name="uq_agent_jobs_active_key"),
    )

    id = Column(String, primary_key=True)
    agent_id = Column(
        String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id = Column(
        String, ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending", server_default="pending")
    processing_mode = Column(String, nullable=True)
    active_key = Column(String, nullable=True)
    payload = Column(Text, nullable=False, default="{}", server_default="{}")
    checkpoint = Column(Text, nullable=False, default="{}", server_default="{}")
    lease_token_hash = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    progress_current = Column(Integer, nullable=False, default=0, server_default="0")
    progress_total = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    agent = relationship("Agent", back_populates="jobs")
    source = relationship("Source", back_populates="agent_jobs")
    batches = relationship(
        "AgentBatch", back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class AgentBatch(Base):
    """Receipt for an idempotently accepted batch from an agent job."""

    __tablename__ = "agent_batches"
    __table_args__ = (
        UniqueConstraint("job_id", "idempotency_key", name="uq_agent_batches_job_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(
        String, ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key = Column(String(80), nullable=False)
    checksum = Column(String(64), nullable=False)
    accepted_at = Column(DateTime, default=_utcnow, nullable=False)

    job = relationship("AgentJob", back_populates="batches")


class AppSetting(Base):
    """
    Backend-managed application setting override.
    """
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)

    def __repr__(self):
        return f"<AppSetting(key={self.key})>"


class User(Base):
    """
    User authentication table
    Stores admin credentials for OneSearch
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    agent_enrollments = relationship(
        "AgentEnrollment", back_populates="created_by_user", passive_deletes=True
    )

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username})>"
