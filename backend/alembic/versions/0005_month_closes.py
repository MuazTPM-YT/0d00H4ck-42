"""month closes

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11 05:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# one row per closed month (first day of it); reopening deletes the row, the audit log keeps why
def upgrade() -> None:
    op.create_table(
        "month_closes",
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("closed_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "extract(day from month) = 1", name=op.f("ck_month_closes_first_of_month")
        ),
        sa.ForeignKeyConstraint(
            ["closed_by"], ["users.id"], name=op.f("fk_month_closes_closed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_month_closes")),
        sa.UniqueConstraint("month", name=op.f("uq_month_closes_month")),
    )


def downgrade() -> None:
    op.drop_table("month_closes")
