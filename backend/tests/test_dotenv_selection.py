"""Keep migration-owner credentials out of API and worker processes."""

from pathlib import Path

import pytest

import app.environment as environment


def test_explicit_dotenv_is_authoritative(monkeypatch, tmp_path: Path):
    selected = tmp_path / "api.env"
    selected.write_text(
        "FLARE_PROCESS_ROLE=api\n"
        "DATABASE_URL=postgresql://selected\n"
        "FLARE_DATABASE_PROVIDER=yandex\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLARE_DOTENV_PATH", str(selected))
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient")
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "self-managed")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://owner")
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker")
    monkeypatch.setenv("GROQ_API_KEY", "ambient-key")

    environment.load_project_dotenv(allowed_roles={"api", "worker"})

    assert environment.os.environ["DATABASE_URL"] == "postgresql://selected"
    assert environment.os.environ["FLARE_DATABASE_PROVIDER"] == "yandex"
    assert "MIGRATION_DATABASE_URL" not in environment.os.environ
    assert "WORKER_DATABASE_URL" not in environment.os.environ
    assert "GROQ_API_KEY" not in environment.os.environ


def test_explicit_dotenv_must_exist(monkeypatch, tmp_path: Path):
    missing = tmp_path / "missing.env"
    monkeypatch.setenv("FLARE_DOTENV_PATH", str(missing))

    with pytest.raises(RuntimeError, match="FLARE_DOTENV_PATH is not a file"):
        environment.load_project_dotenv()


def test_explicit_dotenv_role_must_match_process(monkeypatch, tmp_path: Path):
    selected = tmp_path / "migrate.env"
    selected.write_text(
        "FLARE_PROCESS_ROLE=migration\nMIGRATION_DATABASE_URL=postgresql://owner\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLARE_DOTENV_PATH", str(selected))

    with pytest.raises(RuntimeError, match="cannot start this process"):
        environment.load_project_dotenv(allowed_roles={"api", "worker"})


def test_unset_path_preserves_default_discovery(monkeypatch):
    calls = []
    monkeypatch.delenv("FLARE_DOTENV_PATH", raising=False)
    monkeypatch.setattr(
        environment,
        "load_dotenv",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    environment.load_project_dotenv()

    assert calls == [((), {})]


def test_application_scrubs_ambient_migration_credentials(monkeypatch):
    monkeypatch.delenv("FLARE_DOTENV_PATH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app")
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://worker")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://owner")
    monkeypatch.setattr(environment, "load_dotenv", lambda: None)

    environment.load_project_dotenv(allowed_roles={"api", "worker"})

    assert environment.os.environ["DATABASE_URL"] == "postgresql://app"
    assert environment.os.environ["WORKER_DATABASE_URL"] == "postgresql://worker"
    assert "MIGRATION_DATABASE_URL" not in environment.os.environ
