"""merge sales role into accounts

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10 18:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("owner", "store", "supervisor", "qc", "dispatch", "accounts", "sales")
NEW = ("owner", "store", "supervisor", "qc", "dispatch", "accounts")


def _check(roles: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    listed = ", ".join(f"'{r}'" for r in roles)
    op.create_check_constraint(op.f("ck_users_role"), "users", f"role IN ({listed})")


# one desk takes buyer orders and keeps the books: sales users become accounts
def upgrade() -> None:
    op.execute("UPDATE users SET role = 'accounts' WHERE role = 'sales'")
    _check(NEW)


# widens the check only; merged users stay accounts
def downgrade() -> None:
    _check(OLD)
