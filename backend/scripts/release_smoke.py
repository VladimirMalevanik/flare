#!/usr/bin/env python3
"""Non-destructive HTTP smoke for a deployed Flare release candidate."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
import json
import os
import sys


class SmokeFailure(RuntimeError):
    pass


def _base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise SmokeFailure("BASE_URL must be an http(s) origin without a path")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SmokeFailure("Non-local release smoke requires HTTPS")
    return candidate


def _request(opener, base: str, path: str, timeout: float, *, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": "flare-release-smoke/1"}
    if data is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    request = Request(
        urljoin(base + "/", path.lstrip("/")),
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except HTTPError as error:
        raise SmokeFailure(f"{path} returned HTTP {error.code}") from None
    except (URLError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        raise SmokeFailure(f"{path} is unavailable: {reason}") from None


def _json(opener, base: str, path: str, timeout: float, *, payload=None):
    status, content_type, body = _request(opener, base, path, timeout, payload=payload)
    if status != 200 or "application/json" not in content_type.lower():
        raise SmokeFailure(f"{path} did not return HTTP 200 JSON")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise SmokeFailure(f"{path} returned malformed JSON") from None


def run(base: str, timeout: float, email: str | None, password: str | None,
        expected_support_email: str | None) -> list[str]:
    # A release origin must be reached directly; operator shell proxy variables can
    # otherwise route even localhost checks through an unrelated proxy.
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    checks: list[str] = []

    status, _, _ = _request(opener, base, "/login", timeout)
    if status != 200:
        raise SmokeFailure("/login did not return HTTP 200")
    checks.append("frontend")

    if _json(opener, base, "/api/health", timeout) != {"status": "ok"}:
        raise SmokeFailure("/api/health returned an unexpected payload")
    checks.append("health")
    if _json(opener, base, "/api/ready", timeout) != {"status": "ready"}:
        raise SmokeFailure("/api/ready returned an unexpected payload")
    checks.append("readiness")

    if email is None:
        return checks

    _json(opener, base, "/api/auth/login", timeout, payload={"email": email, "password": password})
    try:
        session = _json(opener, base, "/api/auth/me", timeout)
        actual_email = session.get("user", {}).get("email") if isinstance(session, dict) else None
        if actual_email != email.strip().lower():
            raise SmokeFailure("/api/auth/me did not return the smoke account")
        for path in ("/api/items?limit=1", "/api/flares?limit=1"):
            if not isinstance(_json(opener, base, path, timeout), list):
                raise SmokeFailure(f"{path} did not return a list")
        checks.extend(["authentication", "item-read", "flare-read"])

        if expected_support_email:
            status, _, body = _request(opener, base, "/settings", timeout)
            expected = f"mailto:{expected_support_email}".encode("utf-8")
            if status != 200 or expected not in body:
                raise SmokeFailure("/settings does not expose the expected support address")
            checks.append("support")
    finally:
        _request(opener, base, "/api/auth/logout", timeout, payload={})
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BASE_URL"))
    parser.add_argument("--email", default=os.getenv("SMOKE_EMAIL"))
    parser.add_argument("--expected-support-email", default=os.getenv("EXPECTED_SUPPORT_EMAIL"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("SMOKE_TIMEOUT_SECONDS", "10")))
    args = parser.parse_args()
    password = os.getenv("SMOKE_PASSWORD")
    try:
        if not args.base_url:
            raise SmokeFailure("Set BASE_URL or pass --base-url")
        if (args.email is None) != (password is None):
            raise SmokeFailure("SMOKE_EMAIL and SMOKE_PASSWORD must be supplied together")
        if args.expected_support_email and args.email is None:
            raise SmokeFailure("Support verification requires smoke credentials")
        if args.timeout <= 0:
            raise SmokeFailure("Timeout must be positive")
        checks = run(_base_url(args.base_url), args.timeout, args.email, password,
                     args.expected_support_email)
    except (SmokeFailure, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: " + ", ".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
