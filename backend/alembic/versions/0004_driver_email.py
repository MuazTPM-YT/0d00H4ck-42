"""driver email on dispatches

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 00:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# optional: where the driver link is emailed when the truck leaves
def upgrade() -> None:
    op.add_column("dispatches", sa.Column("driver_email", sa.String(length=254), nullable=True))


def downgrade() -> None:
    op.drop_column("dispatches", "driver_email")
