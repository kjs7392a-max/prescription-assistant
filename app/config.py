from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    app_env: str = "development"
    secret_key: str = "dev-secret"
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @field_validator("database_url", "test_database_url", mode="before")
    @classmethod
    def _ensure_asyncpg_dialect(cls, v: str) -> str:
        # Railway·Heroku 등은 DATABASE_URL을 'postgresql://...' 또는 'postgres://...' 형태로 제공.
        # SQLAlchemy async 엔진은 'postgresql+asyncpg://...'를 요구하므로 자동 변환.
        if not v:
            return v
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


settings = Settings()
