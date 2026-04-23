from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    app_env: str = "development"
    secret_key: str = "dev-secret"

    class Config:
        env_file = ".env"

settings = Settings()
