"""Environment-backed application configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    database_url: str | None
    cors_origins: list[str]


def load_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    return Settings(
        database_url=os.getenv("DATABASE_URL"),
        cors_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
    )


settings = load_settings()
