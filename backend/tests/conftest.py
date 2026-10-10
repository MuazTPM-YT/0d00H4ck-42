from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.core.db import Base, get_db
from app.core.enums import Stage
from app.core.security import create_token, hash_password
from app.main import app
from app.modules.auth.models import Role, User
from app.modules.masters.models import Buyer, FabricRecipe, FabricType, FabricTypeStage

PASSWORD = "demo1234"


# fresh test DB built by the real migration, once per run
@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    s = get_settings()
    admin = create_engine(s.db_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": s.postgres_test_db}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{s.postgres_test_db}"'))
    admin.dispose()

    url = s.db_url(s.postgres_test_db)
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


# each test runs inside one outer transaction that is rolled back; service commits are savepoints
@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    conn = engine.connect()
    outer = conn.begin()
    session = Session(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False, autoflush=False
    )
    yield session
    session.close()
    outer.rollback()
    conn.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def password_hash() -> str:
    return hash_password(PASSWORD)


@pytest.fixture
def make_user(db: Session, password_hash: str) -> Callable[..., User]:
    def make(role: Role, active: bool = True) -> User:
        user = User(
            name=f"Test {role}",
            email=f"{role}@test.local",
            role=role,
            password_hash=password_hash,
            active=active,
        )
        db.add(user)
        db.commit()
        return user

    return make


@pytest.fixture
def client_as(client: TestClient, make_user) -> Callable[[Role], TestClient]:
    def as_role(role: Role) -> TestClient:
        user = make_user(role)
        client.headers["Authorization"] = f"Bearer {create_token(user.id, user.role)}"
        return client

    return as_role


@pytest.fixture
def buyer(db: Session) -> Buyer:
    row = Buyer(code="TEST", name="Test Buyer", gstin="29AAGFG9753P1Z4")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def dyed_fabric(db: Session) -> FabricType:
    row = FabricType(
        code="TPOP",
        name="Test Poplin",
        width_cm=Decimal(150),
        gsm=Decimal(120),
        process_loss_pct=Decimal(10),
        stages=[
            FabricTypeStage(seq=1, stage=Stage.weaving),
            FabricTypeStage(seq=2, stage=Stage.dyeing),
        ],
        recipe=[
            FabricRecipe(fibre="Cotton", count="Ne 40/1", share_pct=Decimal(60)),
            FabricRecipe(fibre="Cotton", count="Ne 30/1", share_pct=Decimal(40)),
        ],
    )
    db.add(row)
    db.commit()
    return row


# concurrency tests: real commits on separate connections, every table emptied after
@pytest.fixture
def committed(engine: Engine) -> Iterator[Engine]:
    yield engine
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
