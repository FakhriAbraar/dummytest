from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.sql import Base


class SystemUser(Base):
    __tablename__ = "app_user"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)


class AiAgent(Base):
    __tablename__ = "ai_agent"

    agent_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str | None] = mapped_column(String(255))
    agent_type: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(String(50))
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    execution_logs: Mapped[list[AgentExecutionLog]] = relationship(
        "AgentExecutionLog", back_populates="agent"
    )
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="agent"
    )
    trending_keywords: Mapped[list[TrendingKeyword]] = relationship(
        "TrendingKeyword", back_populates="agent"
    )


class RegulationDocument(Base):
    __tablename__ = "regulation_document"

    regulation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    document_name: Mapped[str | None] = mapped_column(String(500))
    document_type: Mapped[str | None] = mapped_column(String(100))
    document_number: Mapped[str | None] = mapped_column(String(100))
    full_text: Mapped[str | None] = mapped_column(Text)
    official_source_url: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rag_chunks: Mapped[list[RagChunk]] = relationship(
        "RagChunk", back_populates="regulation"
    )
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="regulation"
    )


class RagChunk(Base):
    __tablename__ = "rag_chunk"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    regulation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("regulation_document.regulation_id", ondelete="CASCADE"),
        nullable=False,
    )
    vector_id: Mapped[str | None] = mapped_column(String(255))
    chunk_content: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    article_reference: Mapped[str | None] = mapped_column(String(255))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    regulation: Mapped[RegulationDocument] = relationship(
        "RegulationDocument", back_populates="rag_chunks"
    )


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_agent.agent_id", ondelete="CASCADE"), nullable=False
    )
    execution_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(50))
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="execution_logs")


class Platform(Base):
    __tablename__ = "platform"

    platform_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_name: Mapped[str | None] = mapped_column(String(100))
    base_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list[Account]] = relationship("Account", back_populates="platform")


class Account(Base):
    __tablename__ = "account"

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("platform.platform_id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(Text)
    account_category: Mapped[str | None] = mapped_column(String(100))
    risk_score: Mapped[float | None] = mapped_column(Float)
    content_count: Mapped[int | None] = mapped_column(Integer, default=0)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    platform: Mapped[Platform] = relationship("Platform", back_populates="accounts")
    contents: Mapped[list[Content]] = relationship("Content", back_populates="account")


class Content(Base):
    __tablename__ = "content"

    content_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    crawl_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    account: Mapped[Account] = relationship("Account", back_populates="contents")
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="content"
    )
    content_keywords: Mapped[list[ContentKeyword]] = relationship(
        "ContentKeyword", back_populates="content"
    )


class TrendingKeyword(Base):
    __tablename__ = "trending_keyword"

    keyword_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_agent.agent_id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(100))
    trend_score: Mapped[float | None] = mapped_column(Float)
    trend_status: Mapped[str | None] = mapped_column(String(50))
    embedding_vector: Mapped[str | None] = mapped_column(String(255))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="trending_keywords")
    content_keywords: Mapped[list[ContentKeyword]] = relationship(
        "ContentKeyword", back_populates="keyword"
    )


class ContentKeyword(Base):
    __tablename__ = "content_keyword"
    __table_args__ = (
        UniqueConstraint("content_id", "keyword_id", name="uq_content_keyword"),
    )

    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content.content_id", ondelete="CASCADE"), primary_key=True
    )
    keyword_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("trending_keyword.keyword_id", ondelete="CASCADE"),
        primary_key=True,
    )

    content: Mapped[Content] = relationship("Content", back_populates="content_keywords")
    keyword: Mapped[TrendingKeyword] = relationship(
        "TrendingKeyword", back_populates="content_keywords"
    )


class IGRSRules(Base):
    __tablename__ = "igrs_rules"
    __table_args__ = (
        UniqueConstraint(
            "kategori_ai", "age_rating_minimal", "dominant_modality",
            name="uq_igrs_rule",
        ),
        Index("ix_igrs_rules_kategori_age", "kategori_ai", "age_rating_minimal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kategori_ai: Mapped[str] = mapped_column(String(100), nullable=False)
    age_rating_minimal: Mapped[str] = mapped_column(String(10), nullable=False)
    dominant_modality: Mapped[str] = mapped_column(String(50), nullable=False, default="VISUAL")

    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="igrs_rule"
    )


class Classification(Base):
    __tablename__ = "classification"

    classification_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content.content_id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_agent.agent_id", ondelete="CASCADE"), nullable=False
    )
    igrs_rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("igrs_rules.id", ondelete="RESTRICT"), nullable=False
    )
    regulation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("regulation_document.regulation_id", ondelete="SET NULL")
    )
    category: Mapped[str | None] = mapped_column(String(10))
    reasoning_category: Mapped[str | None] = mapped_column(String(200))
    unsafe_reason: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    classification_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    content: Mapped[Content] = relationship("Content", back_populates="classifications")
    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="classifications")
    igrs_rule: Mapped[IGRSRules] = relationship(
        "IGRSRules", back_populates="classifications"
    )
    regulation: Mapped[RegulationDocument | None] = relationship(
        "RegulationDocument", back_populates="classifications"
    )
