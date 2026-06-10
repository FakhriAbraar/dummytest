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
    engine_decisions: Mapped[list[EngineDecision]] = relationship(
        "EngineDecision", back_populates="regulation"
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
    engine_status: Mapped[str | None] = mapped_column(String(20))
    final_rating: Mapped[str | None] = mapped_column(String(10))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship("Account", back_populates="contents")
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="content"
    )
    content_keywords: Mapped[list[ContentKeyword]] = relationship(
        "ContentKeyword", back_populates="content"
    )
    engine_decision: Mapped[EngineDecision | None] = relationship(
        "EngineDecision", back_populates="content", uselist=False
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

    engine_decisions: Mapped[list[EngineDecision]] = relationship(
        "EngineDecision", back_populates="igrs_rule"
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
    kategori_tebakan_ai: Mapped[str | None] = mapped_column(String(100))
    reasoning_category: Mapped[str | None] = mapped_column(String(200))
    unsafe_reason: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    classification_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    content: Mapped[Content] = relationship("Content", back_populates="classifications")
    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="classifications")


class EngineDecision(Base):
    __tablename__ = "engine_decision"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("content.content_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    igrs_rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("igrs_rules.id", ondelete="RESTRICT")
    )
    regulation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("regulation_document.regulation_id", ondelete="SET NULL")
    )
    final_kategori: Mapped[str | None] = mapped_column(String(100))
    final_rating: Mapped[str | None] = mapped_column(String(10))
    is_vetoed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    content: Mapped[Content] = relationship("Content", back_populates="engine_decision")
    igrs_rule: Mapped[IGRSRules | None] = relationship(
        "IGRSRules", back_populates="engine_decisions"
    )
    regulation: Mapped[RegulationDocument | None] = relationship(
        "RegulationDocument", back_populates="engine_decisions"
    )


class CrawlerSchedule(Base):
    """Singleton config (row id=1) for the auto-crawler scheduler.

    Holds everything the Komdigi admin can tune on the Auto-Crawler settings page:
    the schedule (mode + timing), how many trending keywords to pull, and the
    per-platform content limits. The live APScheduler job in
    ``app.services.scheduler`` reads this row to decide when and how to crawl.
    """

    __tablename__ = "crawler_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Master ON/OFF for automatic crawling.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Schedule: "interval" | "daily" | "monthly".
    mode: Mapped[str] = mapped_column(String(20), default="interval", nullable=False)
    interval_hours: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    # Patokan jam untuk mode interval (anchor) & fallback bila `times` kosong.
    start_hour: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    start_minute: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Beberapa jam eksekusi untuk mode harian & bulanan: [{"hour":8,"minute":0}, ...].
    times: Mapped[list[dict[str, int]] | None] = mapped_column(JSONB)
    # Mode bulanan: "specific" (pilih beberapa tanggal) | "range" (rentang tanggal).
    monthly_mode: Mapped[str] = mapped_column(String(10), default="specific", nullable=False)
    # Daftar tanggal spesifik untuk monthly_mode="specific", mis. [1, 5, 20].
    days_of_month: Mapped[list[int] | None] = mapped_column(JSONB)
    # Rentang tanggal untuk monthly_mode="range" (1..28).
    day_range_start: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    day_range_end: Mapped[int] = mapped_column(Integer, default=28, nullable=False)

    # Crawl parameters.
    trends_keyword_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_content_x: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_content_instagram: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_content_tiktok: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    custom_keywords: Mapped[list[str] | None] = mapped_column(JSONB)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicCheck(Base):
    """A single content check submitted by the public via the Content Checker.

    Distinct from crawled ``Content``: these are one-off URL/file checks people
    run on the landing page. Persisted so the landing page can surface the most
    recent submissions ("top 10") and so the history survives restarts.
    """

    __tablename__ = "public_check"
    __table_args__ = (Index("ix_public_check_checked_at", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_url: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(String(50))
    username: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    final_kategori: Mapped[str | None] = mapped_column(String(100))
    final_rating: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str | None] = mapped_column(String(20))
    reason_ai: Mapped[str | None] = mapped_column(Text)
    legal_context: Mapped[str | None] = mapped_column(Text)
    classifications_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ParentAdvice(Base):
    """Saran/anjuran untuk orang tua per rating usia (sumber: tim konten).

    Tabel sederhana: hanya ``rating`` + ``saran``. Rating disimpan dalam skala
    sistem (SU/7+/13+/17+/PRC). Ketika Content Checker menghasilkan rating final,
    satu saran dengan rating yang cocok dipilih acak untuk ditampilkan di modal
    hasil pemeriksaan ("Saran untuk Orang Tua").
    """

    __tablename__ = "parent_advice"
    __table_args__ = (Index("ix_parent_advice_rating", "rating"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    saran: Mapped[str] = mapped_column(Text, nullable=False)
