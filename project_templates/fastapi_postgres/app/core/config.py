from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/appdb"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
