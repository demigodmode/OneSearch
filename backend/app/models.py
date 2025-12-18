# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
SQLAlchemy ORM models for OneSearch
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Source(Base):
    """
    Source configuration table
    Stores information about configured search sources
    """
    __tablename__ = "sources"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False)
    include_patterns = Column(Text, nullable=True)  # JSON array as text
    exclude_patterns = Column(Text, nullable=True)  # JSON array as text
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship to indexed files
    indexed_files = relationship("IndexedFile", back_populates="source", cascade="all, delete-orphan")

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
    indexed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    hash = Column(String, nullable=True)  # File content hash for change detection
    status = Column(String, default="success", nullable=False)  # success, failed, skipped
    error_message = Column(Text, nullable=True)

    # Relationship to source
    source = relationship("Source", back_populates="indexed_files")

    def __repr__(self):
        return f"<IndexedFile(id={self.id}, source={self.source_id}, path={self.path}, status={self.status})>"
