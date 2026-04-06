"""SQLAlchemy ORM models based on ERD PP TUNAS - Tim 2 Agentic AI + RAG + MVP."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.sql import Base


class SystemUser(Base):
    """Platform users: admin, analyst, or parent."""

    __tablename__ = "app_user"  # 'system_user' is a reserved SQL function in PostgreSQL 14+

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    role: Mapped[str | None] = mapped_column(
        String(50),
        comment="admin / analis / orang_tua",
    )
    password_hash: Mapped[str | None] = mapped_column(String(255))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)

    # Relationships
    reports: Mapped[list[Report]] = relationship("Report", back_populates="user")
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        "ChatSession", back_populates="user"
    )


class Report(Base):
    """Generated analysis reports per user."""

    __tablename__ = "report"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("system_user.user_id", ondelete="CASCADE"), nullable=False
    )
    report_title: Mapped[str | None] = mapped_column(String(500))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    report_content: Mapped[str | None] = mapped_column(Text)
    report_type: Mapped[str | None] = mapped_column(
        String(50),
        comment="harian / mingguan / bulanan / custom",
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped[SystemUser] = relationship("SystemUser", back_populates="reports")


class AiAgent(Base):
    """AI agents: keyword model, classifier, chatbot, crawler."""

    __tablename__ = "ai_agent"

    agent_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str | None] = mapped_column(String(255))
    agent_type: Mapped[str | None] = mapped_column(
        String(100),
        comment="keyword_model / classifier / chatbot / crawler",
    )
    model_version: Mapped[str | None] = mapped_column(String(100))
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(
        String(50),
        comment="aktif / nonaktif / maintenance",
    )
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        "ChatSession", back_populates="agent"
    )
    execution_logs: Mapped[list[AgentExecutionLog]] = relationship(
        "AgentExecutionLog", back_populates="agent"
    )
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="agent"
    )
    trending_keywords: Mapped[list[TrendingKeyword]] = relationship(
        "TrendingKeyword", back_populates="agent"
    )


class ChatSession(Base):
    """A conversation session between a user and an AI agent."""

    __tablename__ = "chat_session"

    session_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("system_user.user_id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_agent.agent_id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_rating: Mapped[int | None] = mapped_column(
        Integer, comment="1-5"
    )
    session_status: Mapped[str | None] = mapped_column(
        String(50),
        comment="aktif / selesai",
    )

    # Relationships
    user: Mapped[SystemUser] = relationship("SystemUser", back_populates="chat_sessions")
    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="chat_sessions")
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage", back_populates="session"
    )


class ChatMessage(Base):
    """Individual message within a chat session."""

    __tablename__ = "chat_message"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_session.session_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str | None] = mapped_column(
        String(50),
        comment="user / assistant",
    )
    message_content: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")
    citations: Mapped[list[MessageCitation]] = relationship(
        "MessageCitation", back_populates="message"
    )


class RegulationDocument(Base):
    """Official government regulation documents (PP, UU, Peraturan Menteri)."""

    __tablename__ = "regulation_document"

    regulation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    document_name: Mapped[str | None] = mapped_column(String(500))
    document_type: Mapped[str | None] = mapped_column(
        String(100),
        comment="PP / UU / Peraturan Menteri",
    )
    document_number: Mapped[str | None] = mapped_column(String(100))
    full_text: Mapped[str | None] = mapped_column(Text)
    official_source_url: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    rag_chunks: Mapped[list[RagChunk]] = relationship(
        "RagChunk", back_populates="regulation"
    )
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="regulation"
    )


class RagChunk(Base):
    """Text chunks from regulation documents used for RAG retrieval."""

    __tablename__ = "rag_chunk"

    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    regulation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("regulation_document.regulation_id", ondelete="CASCADE"),
        nullable=False,
    )
    vector_id: Mapped[str | None] = mapped_column(
        String(255), comment="ID di Vector Database"
    )
    chunk_content: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    article_reference: Mapped[str | None] = mapped_column(
        String(255), comment="Pasal referensi"
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    regulation: Mapped[RegulationDocument] = relationship(
        "RegulationDocument", back_populates="rag_chunks"
    )
    citations: Mapped[list[MessageCitation]] = relationship(
        "MessageCitation", back_populates="chunk"
    )


class MessageCitation(Base):
    """Citation linking a chat message to a specific RAG chunk."""

    __tablename__ = "message_citation"

    citation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("chat_message.message_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rag_chunk.chunk_id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float | None] = mapped_column(
        Float, comment="0.0 - 1.0"
    )

    # Relationships
    message: Mapped[ChatMessage] = relationship("ChatMessage", back_populates="citations")
    chunk: Mapped[RagChunk] = relationship("RagChunk", back_populates="citations")


class AgentExecutionLog(Base):
    """Execution log for AI agent runs."""

    __tablename__ = "agent_execution_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_agent.agent_id", ondelete="CASCADE"), nullable=False
    )
    execution_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(
        String(50),
        comment="success / failed / running",
    )
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Relationships
    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="execution_logs")


class Platform(Base):
    """Social media or digital platforms being monitored."""

    __tablename__ = "platform"

    platform_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_name: Mapped[str | None] = mapped_column(
        String(100),
        comment="Facebook / TikTok / X / YouTube / Game",
    )
    base_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    accounts: Mapped[list[Account]] = relationship("Account", back_populates="platform")


class Account(Base):
    """Social media accounts being tracked and risk-scored."""

    __tablename__ = "account"

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("platform.platform_id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(Text)
    account_category: Mapped[str | None] = mapped_column(
        String(100),
        comment="berbahaya / edukasi / netral",
    )
    risk_score: Mapped[float | None] = mapped_column(Float, comment="0.0 - 1.0")
    content_count: Mapped[int | None] = mapped_column(Integer, default=0)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    platform: Mapped[Platform] = relationship("Platform", back_populates="accounts")
    contents: Mapped[list[Content]] = relationship("Content", back_populates="account")


class Content(Base):
    """Crawled content items from social media accounts."""

    __tablename__ = "content"

    content_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(
        String(50),
        comment="text / gambar / video",
    )
    title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    crawl_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="contents")
    classifications: Mapped[list[Classification]] = relationship(
        "Classification", back_populates="content"
    )
    content_keywords: Mapped[list[ContentKeyword]] = relationship(
        "ContentKeyword", back_populates="content"
    )


class TrendingKeyword(Base):
    """Trending keywords detected by the AI keyword model agent."""

    __tablename__ = "trending_keyword"

    keyword_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_agent.agent_id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(
        String(100),
        comment="trends24 / google_trend / sosmed",
    )
    trend_score: Mapped[float | None] = mapped_column(Float)
    trend_status: Mapped[str | None] = mapped_column(
        String(50),
        comment="akan_tren / sedang_tren / sudah_tren",
    )
    embedding_vector: Mapped[str | None] = mapped_column(
        String(255), comment="disimpan di Vector DB"
    )
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="trending_keywords")
    content_keywords: Mapped[list[ContentKeyword]] = relationship(
        "ContentKeyword", back_populates="keyword"
    )


class ContentKeyword(Base):
    """Many-to-many join table between Content and TrendingKeyword."""

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

    # Relationships
    content: Mapped[Content] = relationship("Content", back_populates="content_keywords")
    keyword: Mapped[TrendingKeyword] = relationship(
        "TrendingKeyword", back_populates="content_keywords"
    )


class Classification(Base):
    """AI classification result for a piece of content."""

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
    regulation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("regulation_document.regulation_id", ondelete="SET NULL"),
    )
    category: Mapped[str | None] = mapped_column(
        String(100),
        comment="berbahaya / netral / rekomendasi",
    )
    subcategory: Mapped[str | None] = mapped_column(
        String(100),
        comment="pornografi / bullying / grooming / kekerasan",
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, comment="0.0 - 1.0")
    reasoning_text: Mapped[str | None] = mapped_column(Text)
    classification_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    review_status: Mapped[str | None] = mapped_column(
        String(50),
        comment="pending / approved / rejected",
    )

    # Relationships
    content: Mapped[Content] = relationship("Content", back_populates="classifications")
    agent: Mapped[AiAgent] = relationship("AiAgent", back_populates="classifications")
    regulation: Mapped[RegulationDocument | None] = relationship(
        "RegulationDocument", back_populates="classifications"
    )
