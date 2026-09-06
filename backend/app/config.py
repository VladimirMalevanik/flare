"""Environment-backed application configuration."""

import os
from dataclasses import dataclass
from uuid import UUID

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    database_url: str | None
    cors_origins: list[str]
    dev_mode: bool = False
    dev_workspace_id: UUID | None = None
    dev_user_id: str | None = None
    dev_workspace_name: str | None = None

    def require_dev_identity(self) -> tuple[UUID, str, str]:
        """Return the server-owned development identity or fail closed."""
        if not self.dev_mode:
            raise RuntimeError("Development identity is disabled")
        if (
            not self.dev_workspace_id
            or not self.dev_user_id
            or not self.dev_user_id.strip()
            or not self.dev_workspace_name
            or not self.dev_workspace_name.strip()
        ):
            raise RuntimeError(
                "FLARE_DEV_WORKSPACE_ID, FLARE_DEV_USER_ID and "
                "FLARE_DEV_WORKSPACE_NAME are required when FLARE_DEV_MODE=true"
            )
        return (
            self.dev_workspace_id,
            self.dev_user_id.strip(),
            self.dev_workspace_name.strip(),
        )


def _optional_uuid(name: str) -> UUID | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a UUID") from error


def load_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    configured = Settings(
        database_url=os.getenv("DATABASE_URL"),
        cors_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
        dev_mode=os.getenv("FLARE_DEV_MODE", "false").strip().lower() == "true",
        dev_workspace_id=_optional_uuid("FLARE_DEV_WORKSPACE_ID"),
        dev_user_id=os.getenv("FLARE_DEV_USER_ID"),
        dev_workspace_name=os.getenv("FLARE_DEV_WORKSPACE_NAME"),
    )
    if configured.dev_mode:
        configured.require_dev_identity()
    return configured


settings = load_settings()
