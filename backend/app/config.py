"""Environment-backed application configuration."""

import math
import os
import re
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

    email_verification_required: bool | None = None
    email_verification_ttl_seconds: int = 86_400
    email_verification_resend_seconds: int = 60
    app_public_url: str | None = None
    smtp_url: str | None = field(default=None, repr=False)
    email_from: str | None = None

    def __post_init__(self) -> None:
        if self.email_verification_required is None:
            self.email_verification_required = self.environment == "production"

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
        if self.email_verification_ttl_seconds <= 0:
            raise RuntimeError("EMAIL_VERIFICATION_TTL_SECONDS must be positive")
        if self.email_verification_resend_seconds <= 0:
            raise RuntimeError("EMAIL_VERIFICATION_RESEND_SECONDS must be positive")
        if self.email_verification_required:
            if not self.app_public_url:
                raise RuntimeError("Email verification requires APP_PUBLIC_URL")
            public_url = urlsplit(self.app_public_url)
            if (
                public_url.scheme not in {"http", "https"}
                or not public_url.netloc
                or public_url.path not in {"", "/"}
                or public_url.query
                or public_url.fragment
                or public_url.username
                or public_url.password
            ):
                raise RuntimeError("APP_PUBLIC_URL must be an HTTP(S) origin")
            if self.secure_cookies:
                if (
                    public_url.scheme != "https"
                    or not self.smtp_url
                    or not self.email_from
                ):
                    raise RuntimeError(
                        "Production email verification requires an HTTPS APP_PUBLIC_URL, SMTP_URL and EMAIL_FROM"
                    )
            elif public_url.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise RuntimeError(
                    "Development email verification requires a localhost APP_PUBLIC_URL"
                )

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


def _optional_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return normalized == "true"


def load_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    environment = os.getenv("FLARE_ENV", "production")
    configured = Settings(
        database_url=os.getenv("DATABASE_URL"),
        environment=environment,
        session_lifetime_seconds=int(os.getenv("SESSION_LIFETIME_SECONDS", "604800")),
        session_idle_seconds=int(os.getenv("SESSION_IDLE_SECONDS", "86400")),
        cors_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
        dev_mode=os.getenv("FLARE_DEV_MODE", "false").strip().lower() == "true",
        dev_workspace_id=_optional_uuid("FLARE_DEV_WORKSPACE_ID"),
        dev_user_id=os.getenv("FLARE_DEV_USER_ID"),
        dev_workspace_name=os.getenv("FLARE_DEV_WORKSPACE_NAME"),
        email_verification_required=_optional_bool("EMAIL_VERIFICATION_REQUIRED"),
        email_verification_ttl_seconds=int(os.getenv("EMAIL_VERIFICATION_TTL_SECONDS", "86400")),
        email_verification_resend_seconds=int(os.getenv("EMAIL_VERIFICATION_RESEND_SECONDS", "60")),
        app_public_url=os.getenv("APP_PUBLIC_URL"),
        smtp_url=os.getenv("SMTP_URL"),
        email_from=os.getenv("EMAIL_FROM"),
    )
    if configured.dev_mode:
        configured.require_dev_identity()
    return configured


settings = load_settings()


@dataclass(frozen=True)
class GitHubSettings:
    app_id: int
    app_slug: str
    private_key: str = field(repr=False)
    frontend_return_url: str = ""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    state_ttl_seconds: int = 600

    def validate(self) -> None:
        if type(self.app_id) is not int or self.app_id <= 0:
            raise ValueError("GITHUB_APP_ID must be a positive integer")
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.app_slug):
            raise ValueError("GITHUB_APP_SLUG is invalid")
        if "PRIVATE KEY-----" not in self.private_key:
            raise ValueError("GITHUB_APP_PRIVATE_KEY is invalid")
        if not self.client_id.strip() or len(self.client_id) > 255:
            raise ValueError("GITHUB_CLIENT_ID is invalid")
        if not self.client_secret.strip() or len(self.client_secret) > 255:
            raise ValueError("GITHUB_CLIENT_SECRET is invalid")
        parsed = urlsplit(self.frontend_return_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("GITHUB_FRONTEND_RETURN_URL must be an absolute HTTP(S) URL")
        if type(self.state_ttl_seconds) is not int or not 60 <= self.state_ttl_seconds <= 1800:
            raise ValueError("GITHUB_STATE_TTL_SECONDS must be between 60 and 1800")


def load_github_settings() -> GitHubSettings:
    try:
        configured = GitHubSettings(
            app_id=int(os.getenv("GITHUB_APP_ID", "0")),
            app_slug=os.getenv("GITHUB_APP_SLUG", ""),
            private_key=os.getenv("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n"),
            frontend_return_url=os.getenv("GITHUB_FRONTEND_RETURN_URL", ""),
            client_id=os.getenv("GITHUB_CLIENT_ID", ""),
            client_secret=os.getenv("GITHUB_CLIENT_SECRET", ""),
            state_ttl_seconds=int(os.getenv("GITHUB_STATE_TTL_SECONDS", "600")),
        )
        configured.validate()
        return configured
    except (TypeError, ValueError):
        raise ValueError("Invalid GitHub App configuration") from None


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
