"""Release smoke orchestration without network or product-data mutations."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "release_smoke.py"
SPEC = importlib.util.spec_from_file_location("release_smoke", SCRIPT)
assert SPEC and SPEC.loader
release_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_smoke)


def test_release_smoke_uses_only_health_and_safe_authenticated_reads(monkeypatch):
    calls = []

    def request(_opener, _base, path, _timeout, *, payload=None):
        calls.append((path, payload))
        if path == "/settings":
            return 200, "text/html", b'<a href="mailto:help@flare.example">Contact support</a>'
        if path == "/api/auth/logout":
            return 204, "application/json", b""
        return 200, "text/html", b"Flare"

    def json_request(_opener, _base, path, _timeout, *, payload=None):
        calls.append((path, payload))
        return {
            "/api/health": {"status": "ok"},
            "/api/ready": {"status": "ready"},
            "/api/auth/login": {"ok": True},
            "/api/auth/me": {"user": {"email": "smoke@example.com"}},
            "/api/items?limit=1": [],
            "/api/flares?limit=1": [],
        }[path]

    monkeypatch.setattr(release_smoke, "_request", request)
    monkeypatch.setattr(release_smoke, "_json", json_request)
    checks = release_smoke.run(
        "https://flare.example",
        10,
        "smoke@example.com",
        "test-only",
        "help@flare.example",
    )

    assert checks == [
        "frontend",
        "health",
        "readiness",
        "authentication",
        "item-read",
        "flare-read",
        "support",
    ]
    assert calls[-1] == ("/api/auth/logout", {})
    assert not any(path in {"/api/items", "/api/analyze"} for path, _ in calls)


def test_release_smoke_requires_https_except_on_loopback():
    assert release_smoke._base_url("http://127.0.0.1:3000/") == "http://127.0.0.1:3000"
    assert release_smoke._base_url("https://flare.example") == "https://flare.example"
    with pytest.raises(release_smoke.SmokeFailure, match="requires HTTPS"):
        release_smoke._base_url("http://flare.example")
