"""A retained cookie is insufficient after decline, privacy/storage loss or expiry."""
from uuid import UUID, uuid4
import psycopg
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from test_acquisition import growth, enabled_growth_policy, POLICY  # noqa: F401


@pytest.mark.parametrize("choice", [None, False, "true", 1, {"allowed": True}, [], True])
def test_retained_cookie_requires_current_explicit_signup_assertion(growth, choice):
    db, environment, _, _ = growth
    settings = Settings(database_url=None, environment="test", cors_origins=["http://testserver"], email_verification_required=False)
    with TestClient(create_app(settings, database=db), headers={"Origin": "http://testserver"}) as client:
        response = client.post("/acquisition/touch", json={"touch": {"landing_route": "/", "utm_source": "alpha"},
            "revision": POLICY["revision"], "eligible": True})
        assert response.status_code == 202 and client.cookies.get("flare_acquisition")
        # Simulate an old cookie surviving a failed forget request/new tab. No
        # current opt-in means no signup linkage, including truthy invalid input.
        payload = {"email": uuid4().hex + "@growth.invalid", "password": "synthetic-long-password", "name": "Synthetic",
            "termsAccepted": True, "privacyAccepted": True}
        if choice is not None:
            payload["acquisitionOptIn"] = choice
        created = client.post("/auth/register", json=payload)
        assert created.status_code == 201, created.text
        user = client.get("/auth/me").json()
        environment.user_ids.add(user["user"]["id"]); environment.workspace_ids.add(UUID(user["workspace"]["id"]))
        assert not client.cookies.get("flare_acquisition")
    with psycopg.connect(environment.admin_url) as connection:
        saved = connection.execute("SELECT eligibility,first_touch->>'utm_source' FROM public.signup_attribution WHERE user_id=%s", (user["user"]["id"],)).fetchone()
        assert saved == (("eligible", "alpha") if choice is True else ("unknown", None))
