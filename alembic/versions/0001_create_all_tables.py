"""create_all_tables

Revision ID: 0001
Revises:
Create Date: 2026-04-06

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # app_user  (renamed from system_user – reserved SQL function in PostgreSQL 14+)
    # ------------------------------------------------------------------ #
    op.create_table(
        "app_user",
        sa.Column("user_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column(
            "role",
            sa.String(50),
            nullable=True,
            comment="admin / analis / orang_tua",
        ),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email"),
    )

    # ------------------------------------------------------------------ #
    # report
    # ------------------------------------------------------------------ #
    op.create_table(
        "report",
        sa.Column("report_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("report_title", sa.String(500), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("report_content", sa.Text(), nullable=True),
        sa.Column(
            "report_type",
            sa.String(50),
            nullable=True,
            comment="harian / mingguan / bulanan / custom",
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id"),
    )

    # ------------------------------------------------------------------ #
    # ai_agent
    # ------------------------------------------------------------------ #
    op.create_table(
        "ai_agent",
        sa.Column("agent_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=True),
        sa.Column(
            "agent_type",
            sa.String(100),
            nullable=True,
            comment="keyword_model / classifier / chatbot / crawler",
        ),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=True,
            comment="aktif / nonaktif / maintenance",
        ),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("agent_id"),
    )

    # ------------------------------------------------------------------ #
    # chat_session
    # ------------------------------------------------------------------ #
    op.create_table(
        "chat_session",
        sa.Column("session_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_rating", sa.Integer(), nullable=True, comment="1-5"),
        sa.Column(
            "session_status",
            sa.String(50),
            nullable=True,
            comment="aktif / selesai",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )

    # ------------------------------------------------------------------ #
    # chat_message
    # ------------------------------------------------------------------ #
    op.create_table(
        "chat_message",
        sa.Column("message_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(50), nullable=True, comment="user / assistant"),
        sa.Column("message_content", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_session.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )

    # ------------------------------------------------------------------ #
    # regulation_document
    # ------------------------------------------------------------------ #
    op.create_table(
        "regulation_document",
        sa.Column("regulation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_name", sa.String(500), nullable=True),
        sa.Column(
            "document_type",
            sa.String(100),
            nullable=True,
            comment="PP / UU / Peraturan Menteri",
        ),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("official_source_url", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("regulation_id"),
    )

    # ------------------------------------------------------------------ #
    # rag_chunk
    # ------------------------------------------------------------------ #
    op.create_table(
        "rag_chunk",
        sa.Column("chunk_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("regulation_id", sa.Integer(), nullable=False),
        sa.Column(
            "vector_id", sa.String(255), nullable=True, comment="ID di Vector Database"
        ),
        sa.Column("chunk_content", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column(
            "article_reference", sa.String(255), nullable=True, comment="Pasal referensi"
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["regulation_id"],
            ["regulation_document.regulation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )

    # ------------------------------------------------------------------ #
    # message_citation
    # ------------------------------------------------------------------ #
    op.create_table(
        "message_citation",
        sa.Column("citation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=True, comment="0.0 - 1.0"),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_message.message_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["rag_chunk.chunk_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("citation_id"),
    )

    # ------------------------------------------------------------------ #
    # agent_execution_log
    # ------------------------------------------------------------------ #
    op.create_table(
        "agent_execution_log",
        sa.Column("log_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("execution_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=True,
            comment="success / failed / running",
        ),
        sa.Column(
            "input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "output_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("log_id"),
    )

    # ------------------------------------------------------------------ #
    # platform
    # ------------------------------------------------------------------ #
    op.create_table(
        "platform",
        sa.Column("platform_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "platform_name",
            sa.String(100),
            nullable=True,
            comment="Facebook / TikTok / X / YouTube / Game",
        ),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("platform_id"),
    )

    # ------------------------------------------------------------------ #
    # account
    # ------------------------------------------------------------------ #
    op.create_table(
        "account",
        sa.Column("account_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column(
            "account_category",
            sa.String(100),
            nullable=True,
            comment="berbahaya / edukasi / netral",
        ),
        sa.Column("risk_score", sa.Float(), nullable=True, comment="0.0 - 1.0"),
        sa.Column("content_count", sa.Integer(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["platform_id"], ["platform.platform_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )

    # ------------------------------------------------------------------ #
    # content
    # ------------------------------------------------------------------ #
    op.create_table(
        "content",
        sa.Column("content_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "content_type",
            sa.String(50),
            nullable=True,
            comment="text / gambar / video",
        ),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("crawl_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("content_id"),
    )

    # ------------------------------------------------------------------ #
    # trending_keyword
    # ------------------------------------------------------------------ #
    op.create_table(
        "trending_keyword",
        sa.Column("keyword_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(500), nullable=True),
        sa.Column(
            "source",
            sa.String(100),
            nullable=True,
            comment="trends24 / google_trend / sosmed",
        ),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column(
            "trend_status",
            sa.String(50),
            nullable=True,
            comment="akan_tren / sedang_tren / sudah_tren",
        ),
        sa.Column(
            "embedding_vector",
            sa.String(255),
            nullable=True,
            comment="disimpan di Vector DB",
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("keyword_id"),
    )

    # ------------------------------------------------------------------ #
    # content_keyword  (many-to-many)
    # ------------------------------------------------------------------ #
    op.create_table(
        "content_keyword",
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_id"], ["content.content_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["keyword_id"], ["trending_keyword.keyword_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("content_id", "keyword_id"),
        sa.UniqueConstraint("content_id", "keyword_id", name="uq_content_keyword"),
    )

    # ------------------------------------------------------------------ #
    # classification
    # ------------------------------------------------------------------ #
    op.create_table(
        "classification",
        sa.Column("classification_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("regulation_id", sa.Integer(), nullable=True),
        sa.Column(
            "category",
            sa.String(100),
            nullable=True,
            comment="berbahaya / netral / rekomendasi",
        ),
        sa.Column(
            "subcategory",
            sa.String(100),
            nullable=True,
            comment="pornografi / bullying / grooming / kekerasan",
        ),
        sa.Column("confidence_score", sa.Float(), nullable=True, comment="0.0 - 1.0"),
        sa.Column("reasoning_text", sa.Text(), nullable=True),
        sa.Column("classification_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "review_status",
            sa.String(50),
            nullable=True,
            comment="pending / approved / rejected",
        ),
        sa.ForeignKeyConstraint(["content_id"], ["content.content_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["regulation_id"],
            ["regulation_document.regulation_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("classification_id"),
    )


def downgrade() -> None:
    op.drop_table("classification")
    op.drop_table("content_keyword")
    op.drop_table("trending_keyword")
    op.drop_table("content")
    op.drop_table("account")
    op.drop_table("platform")
    op.drop_table("agent_execution_log")
    op.drop_table("message_citation")
    op.drop_table("rag_chunk")
    op.drop_table("regulation_document")
    op.drop_table("chat_message")
    op.drop_table("chat_session")
    op.drop_table("ai_agent")
    op.drop_table("report")
    op.drop_table("app_user")
