from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    # Keitaro API
    KEITARO_API_URL: str
    KEITARO_API_KEY: str
    # Database
    DATABASE_URL: str = "sqlite:///./keitaro.db"
    # App
    DEBUG: bool = False
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
