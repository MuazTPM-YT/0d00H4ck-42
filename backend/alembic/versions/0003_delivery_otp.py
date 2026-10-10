"""delivery link and otp on dispatches

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 22:00:00

"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# every truck gets a driver link; trucks already out also get a code, so they can be closed too
def upgrade() -> None:
    op.add_column("dispatches", sa.Column("delivery_token", sa.String(length=64), nullable=True))
    op.add_column("dispatches", sa.Column("delivery_otp", sa.String(length=6), nullable=True))
    op.add_column(
        "dispatches",
        sa.Column("otp_tries", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "dispatches", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("dispatches", sa.Column("received_by", sa.String(length=80), nullable=True))
    op.add_column("dispatches", sa.Column("delivery_note", sa.String(length=500), nullable=True))

    conn = op.get_bind()
    for d_id, status in conn.execute(sa.text("SELECT id, status FROM dispatches")).all():
        otp = f"{secrets.randbelow(10**6):06d}" if status == "confirmed" else None
        conn.execute(
            sa.text("UPDATE dispatches SET delivery_token = :t, delivery_otp = :o WHERE id = :i"),
            {"t": secrets.token_urlsafe(24), "o": otp, "i": d_id},
        )

    op.alter_column("dispatches", "delivery_token", nullable=False)
    op.create_unique_constraint(
        op.f("uq_dispatches_delivery_token"), "dispatches", ["delivery_token"]
    )
    op.create_check_constraint(
        op.f("ck_dispatches_delivered_after_it_left"),
        "dispatches",
        "delivered_at IS NULL OR (status = 'confirmed' AND received_by IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_dispatches_otp_tries_not_negative"), "dispatches", "otp_tries >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_dispatches_otp_tries_not_negative"), "dispatches", type_="check")
    op.drop_constraint(op.f("ck_dispatches_delivered_after_it_left"), "dispatches", type_="check")
    op.drop_constraint(op.f("uq_dispatches_delivery_token"), "dispatches", type_="unique")
    for col in (
        "delivery_note",
        "received_by",
        "delivered_at",
        "otp_tries",
        "delivery_otp",
        "delivery_token",
    ):
        op.drop_column("dispatches", col)
