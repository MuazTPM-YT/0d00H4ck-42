from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_test_db: str = "everest_test"
    db_host: str = "localhost"
    db_port: int = 5435

    jwt_secret: str
    jwt_expire_minutes: int = 720
    cookie_secure: bool = False

    def db_url(self, db: str | None = None) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.db_host}:{self.db_port}/{db or self.postgres_db}"
        )


# fail loud at startup, name the missing vars, never their values
@lru_cache
def get_settings() -> Settings:
    try:
        settings = Settings()
    except ValidationError as e:
        missing = ", ".join(str(err["loc"][0]).upper() for err in e.errors())
        raise SystemExit(f"Config error, check .env: {missing}") from None
    blank = [k.upper() for k in ("postgres_password", "jwt_secret") if not getattr(settings, k)]
    if blank:
        raise SystemExit(f"Config error, empty in .env: {', '.join(blank)}")
    return settings
