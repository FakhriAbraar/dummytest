"""add reviewed_by and reviewed_at to content

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Menambahkan kolom reviewed_by dan reviewed_at ke tabel content
    op.add_column("content", sa.Column("reviewed_by", sa.String(length=255), nullable=True))
    op.add_column("content", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Menghapus kolom reviewed_by dan reviewed_at dari tabel content
    op.drop_column("content", "reviewed_at")
    op.drop_column("content", "reviewed_by")
