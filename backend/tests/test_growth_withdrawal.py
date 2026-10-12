"""Privacy removal remains accessible to authenticated unverified accounts."""
import os
from uuid import uuid4
import psycopg
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthService
from test_acquisition import growth, enabled_growth_policy  # noqa: F401


def test_unverified_account_can_withdraw_but_cannot_use_verified_product(growth):
    db, environment, _, _ = growth
    class Mail:
        def send(self, **kwargs):
            pass
    auth = AuthService(db, email_verification_required=True, email_sender=Mail(), app_public_url="http://testserver")
    token = auth.register(uuid4().hex + "@growth.invalid", "synthetic-long-password", "Synthetic")
    user = auth.current(token)
    environment.user_ids.add(user.user_id); environment.workspace_ids.add(user.workspace_id)
    settings = Settings(database_url=None, environment="test", cors_origins=["http://testserver"], email_verification_required=True,
        app_public_url="http://localhost", email_from="synthetic@growth.invalid")
    with TestClient(create_app(settings, database=db), headers={"Origin": "http://testserver"}) as client:
        assert client.post("/analytics/withdraw").status_code == 401
        client.cookies.set(settings.session_cookie_name, token)
        assert client.get("/items").status_code == 403
        assert client.post("/analytics/withdraw", headers={"Origin": "http://evil.invalid"}).status_code == 403
        assert client.post("/analytics/withdraw").status_code == 204
        assert client.post("/analytics/withdraw").status_code == 204
        assert client.get("/items").status_code == 403
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        saved = connection.execute("SELECT eligibility,first_touch,last_touch FROM public.signup_attribution WHERE user_id=%s", (user.user_id,)).fetchone()
        assert saved == ("withdrawn", None, None)
