"""Controlled loading of local dotenv files."""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


_ROLE_SECRETS = {
    "api": {
        "DATABASE_URL",
        "EMAIL_VERIFICATION_REQUIRED",
        "EMAIL_VERIFICATION_TTL_SECONDS",
        "EMAIL_VERIFICATION_RESEND_SECONDS",
        "APP_PUBLIC_URL",
        "SMTP_URL",
        "EMAIL_FROM",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_CLIENT_SECRET",
        "VOICE_GROQ_API_KEY",
    },
    "worker": {"WORKER_DATABASE_URL", "GROQ_API_KEY"},
    "migration": {"MIGRATION_DATABASE_URL"},
}
_PROCESS_SECRETS = {
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "WORKER_DATABASE_URL",
    "POSTGRES_PASSWORD",
    "OWNER_PASSWORD",
    "APP_PASSWORD",
    "WORKER_PASSWORD",
    "GROQ_API_KEY",
    "VOICE_GROQ_API_KEY",
    "EMAIL_VERIFICATION_REQUIRED",
    "EMAIL_VERIFICATION_TTL_SECONDS",
    "EMAIL_VERIFICATION_RESEND_SECONDS",
    "APP_PUBLIC_URL",
    "SMTP_URL",
    "EMAIL_FROM",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_CLIENT_SECRET",
}


def load_project_dotenv(*, allowed_roles: set[str] | None = None) -> None:
    """Load the explicitly selected file, or preserve default discovery."""
    configured_path = os.getenv("FLARE_DOTENV_PATH")
    if not configured_path:
        load_dotenv()
        if allowed_roles is not None:
            process_role = os.getenv("FLARE_PROCESS_ROLE")
            selected_roles = (
                {process_role} if process_role in allowed_roles else allowed_roles
            )
            allowed_secrets = set().union(
                *(_ROLE_SECRETS[role] for role in selected_roles)
            )
            for variable in _PROCESS_SECRETS - allowed_secrets:
                os.environ.pop(variable, None)
        return

    dotenv_path = Path(configured_path).expanduser()
    if not dotenv_path.is_file():
        raise RuntimeError(f"FLARE_DOTENV_PATH is not a file: {dotenv_path}")

    selected_values = dotenv_values(dotenv_path)
    process_role = selected_values.get("FLARE_PROCESS_ROLE")
    if process_role not in _ROLE_SECRETS:
        raise RuntimeError(
            "An explicit dotenv file must set FLARE_PROCESS_ROLE to "
            "api, worker or migration"
        )
    if allowed_roles is not None and process_role not in allowed_roles:
        expected = ", ".join(sorted(allowed_roles))
        raise RuntimeError(
            f"FLARE_PROCESS_ROLE={process_role} cannot start this process; "
            f"expected one of: {expected}"
        )

    # An explicit file is authoritative. This also prevents values exported by
    # an earlier `source .env` from silently selecting another database.
    load_dotenv(dotenv_path=dotenv_path, override=True)
    for variable in _PROCESS_SECRETS - _ROLE_SECRETS[process_role]:
        os.environ.pop(variable, None)
