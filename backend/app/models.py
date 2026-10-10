# every table, imported once so Alembic and SQLAlchemy see the full schema
from app.core.audit import AuditLog  # noqa: F401
from app.core.codes import CodeSequence  # noqa: F401
from app.core.db import Base  # noqa: F401
from app.core.idempotency import IdempotencyKey  # noqa: F401
from app.modules.analytics.models import *  # noqa: F403
from app.modules.auth.models import *  # noqa: F403
from app.modules.dispatch.models import *  # noqa: F403
from app.modules.finance.models import *  # noqa: F403
from app.modules.inventory.models import *  # noqa: F403
from app.modules.masters.models import *  # noqa: F403
from app.modules.orders.models import *  # noqa: F403
from app.modules.production.models import *  # noqa: F403
from app.modules.quality.models import *  # noqa: F403
from app.modules.workforce.models import *  # noqa: F403
