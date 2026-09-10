"""Environment-backed application configuration."""

import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

from app.environment import load_project_dotenv

load_project_dotenv(allowed_roles={"api", "worker"})


@dataclass
class Settings:
    database_url: str | None
    cors_origins: list[str]
    environment: str = "production"
    session_lifetime_seconds: int = 604800
    session_idle_seconds: int = 86400
    dev_mode: bool = False
    dev_workspace_id: UUID | None = None
    dev_user_id: str | None = None
    dev_workspace_name: str | None = None

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    @property
    def session_cookie_name(self) -> str:
        return "__Host-flare_session" if self.secure_cookies else "flare_session"

    def validate(self) -> None:
        if self.environment not in {"production", "development", "test"}:
            raise RuntimeError("FLARE_ENV must be production, development or test")
        if self.dev_mode and self.environment == "production":
            raise RuntimeError("Production cannot enable development identity")
        if not 0 < self.session_idle_seconds <= self.session_lifetime_seconds:
            raise RuntimeError("Session limits must be positive and idle <= lifetime")
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.path or parsed.query or parsed.fragment or parsed.username
                or parsed.password or "*" in origin):
                raise RuntimeError("CORS_ORIGINS must contain exact HTTP(S) origins")
            if self.secure_cookies and parsed.scheme != "https":
                raise RuntimeError("Production frontend origins must use HTTPS")
        if self.secure_cookies and (not self.database_url or not self.cors_origins):
            raise RuntimeError("Production requires DATABASE_URL and CORS_ORIGINS")

    def require_dev_identity(self) -> tuple[UUID, str, str]:
        """Return the server-owned development identity or fail closed."""
        if not self.dev_mode or self.environment not in {"development", "test"}:
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
        environment=os.getenv("FLARE_ENV", "production"),
        session_lifetime_seconds=int(os.getenv("SESSION_LIFETIME_SECONDS", "604800")),
        session_idle_seconds=int(os.getenv("SESSION_IDLE_SECONDS", "86400")),
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


# AI settings are loaded only by the analysis caller, never during API startup.
# Invalid/missing AI configuration must not prevent manual Note storage.
@dataclass(frozen=True)
class AISettings:
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.groq.com"
    model: str = "openai/gpt-oss-20b"
    reasoning_effort: str = "low"
    max_input_bytes: int = 4000
    max_sources: int = 5
    max_completion_tokens: int = 2000
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0
    deadline_seconds: float = 40.0

    def validate(self) -> None:
        if self.model != "openai/gpt-oss-20b" or self.reasoning_effort != "low":
            raise ValueError("Block 2 supports only the default 20B/low profile")
        # Keep backend credentials on the official origin. Tests inject a transport.
        if self.base_url.rstrip('/') != "https://api.groq.com":
            raise ValueError("GROQ_BASE_URL must be the official SDK origin")
        for value in (self.max_input_bytes, self.max_sources, self.max_completion_tokens):
            if type(value) is not int or value <= 0:
                raise ValueError("AI request limits must be positive integers")
        if self.max_completion_tokens > 65536:
            raise ValueError("AI completion limit exceeds the model limit")
        for value in (self.connect_timeout_seconds, self.request_timeout_seconds, self.deadline_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("AI timeouts must be finite and positive")


def load_ai_settings() -> AISettings:
    """Read backend-only AI configuration on demand, with safe parse errors."""
    try:
        configured = AISettings(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com"),
            model=os.getenv("LLM_DEFAULT_MODEL", "openai/gpt-oss-20b"),
            reasoning_effort=os.getenv("LLM_DEFAULT_REASONING_EFFORT", "low"),
            max_input_bytes=int(os.getenv("LLM_MAX_INPUT_BYTES", "4000")),
            max_sources=int(os.getenv("LLM_MAX_SOURCES", "5")),
            max_completion_tokens=int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "2000")),
            connect_timeout_seconds=float(os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "5")),
            request_timeout_seconds=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30")),
            deadline_seconds=float(os.getenv("LLM_DEADLINE_SECONDS", "40")),
        )
        configured.validate()
    except (ValueError, TypeError):
        raise ValueError("Invalid AI configuration") from None
    return configured
