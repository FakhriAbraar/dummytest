"""create_all_tables

Revision ID: 0001
Revises:
Create Date: 2026-05-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("user_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "ai_agent",
        sa.Column("agent_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=True),
        sa.Column("agent_type", sa.String(100), nullable=True),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("agent_id"),
    )

    op.create_table(
        "regulation_document",
        sa.Column("regulation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_name", sa.String(500), nullable=True),
        sa.Column("document_type", sa.String(100), nullable=True),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("official_source_url", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("regulation_id"),
    )

    op.create_table(
        "rag_chunk",
        sa.Column("chunk_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("regulation_id", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.String(255), nullable=True),
        sa.Column("chunk_content", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("article_reference", sa.String(255), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["regulation_id"], ["regulation_document.regulation_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )

    op.create_table(
        "agent_execution_log",
        sa.Column("log_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("execution_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("log_id"),
    )

    op.create_table(
        "platform",
        sa.Column("platform_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_name", sa.String(100), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("platform_id"),
    )

    op.create_table(
        "account",
        sa.Column("account_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("account_category", sa.String(100), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("content_count", sa.Integer(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["platform_id"], ["platform.platform_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )

    op.create_table(
        "content",
        sa.Column("content_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(50), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("crawl_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("engine_status", sa.String(20), nullable=True),
        sa.Column("final_rating", sa.String(10), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.account_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("content_id"),
    )

    op.create_table(
        "trending_keyword",
        sa.Column("keyword_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(500), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("trend_status", sa.String(50), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("keyword_id"),
    )

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

    op.create_table(
        "igrs_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kategori_ai", sa.String(100), nullable=False),
        sa.Column("age_rating_minimal", sa.String(10), nullable=False),
        sa.Column("dominant_modality", sa.String(50), nullable=False, server_default="VISUAL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "kategori_ai", "age_rating_minimal", "dominant_modality",
            name="uq_igrs_rule",
        ),
    )
    op.create_index(
        "ix_igrs_rules_kategori_age",
        "igrs_rules",
        ["kategori_ai", "age_rating_minimal"],
    )

    op.create_table(
        "classification",
        sa.Column("classification_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("kategori_tebakan_ai", sa.String(100), nullable=True),
        sa.Column("reasoning_category", sa.String(200), nullable=True),
        sa.Column("unsafe_reason", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("classification_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["content_id"], ["content.content_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["ai_agent.agent_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("classification_id"),
    )

    op.create_table(
        "engine_decision",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("igrs_rule_id", sa.Integer(), nullable=True),
        sa.Column("regulation_id", sa.Integer(), nullable=True),
        sa.Column("final_kategori", sa.String(100), nullable=True),
        sa.Column("final_rating", sa.String(10), nullable=True),
        sa.Column("is_vetoed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["content_id"], ["content.content_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["igrs_rule_id"], ["igrs_rules.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["regulation_id"], ["regulation_document.regulation_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_id", name="uq_engine_decision_content"),
    )


def downgrade() -> None:
    op.drop_table("engine_decision")
    op.drop_table("classification")
    op.drop_index("ix_igrs_rules_kategori_age", table_name="igrs_rules")
    op.drop_table("igrs_rules")
    op.drop_table("content_keyword")
    op.drop_table("trending_keyword")
    op.drop_table("content")
    op.drop_table("account")
    op.drop_table("platform")
    op.drop_table("agent_execution_log")
    op.drop_table("rag_chunk")
    op.drop_table("regulation_document")
    op.drop_table("ai_agent")
    op.drop_table("app_user")
