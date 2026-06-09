"""parent_advice (saran ortu)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parent_advice",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("saran", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parent_advice_rating", "parent_advice", ["rating"])


def downgrade() -> None:
    op.drop_index("ix_parent_advice_rating", table_name="parent_advice")
    op.drop_table("parent_advice")
