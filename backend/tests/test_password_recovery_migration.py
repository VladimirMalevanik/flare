import os

import psycopg
from psycopg.errors import CheckViolation
import pytest

from app.models.database import _connection_is_ready
from test_auth_service import auth, account  # noqa: F401
from test_password_recovery import recovery, link  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.mark.parametrize('mutation', [
    'GRANT SELECT ON auth_password_resets TO flare_worker',
    'GRANT SELECT(token_hash) ON auth_password_resets TO flare_worker',
    'GRANT SELECT ON auth_password_resets TO PUBLIC',
    'GRANT SELECT(token_hash) ON auth_password_resets TO PUBLIC',
    'GRANT TRUNCATE ON auth_password_resets TO flare_app',
    'GRANT SELECT ON auth_password_resets TO flare_app WITH GRANT OPTION',
    'REVOKE DELETE ON auth_password_resets FROM flare_app',
    'ALTER TABLE auth_password_resets OWNER TO flare_app',
])
def test_readiness_rejects_reset_privilege_drift(auth, mutation):
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        try:
            c.execute('SET LOCAL ROLE flare_app')
            assert _connection_is_ready(c)
            c.execute('RESET ROLE')
            c.execute(mutation)
            c.execute('SET LOCAL ROLE flare_app')
            assert not _connection_is_ready(c)
        finally:
            c.rollback()


def test_reset_constraints_and_cascade_are_real_database_guards(auth, recovery):
    service, _ = recovery
    email, session = account(auth)
    user = auth.current(session)
    link(recovery, email)
    invalid = [
        ('r'*43, email, "clock_timestamp()+interval '1 hour'"),
        ('a'*64, email.upper(), "clock_timestamp()+interval '1 hour'"),
        ('b'*64, email, "clock_timestamp()-interval '1 hour'"),
    ]
    for digest, address, expiry in invalid:
        with service.database.connection() as c:
            with pytest.raises(CheckViolation), c.transaction():
                c.execute(f'INSERT INTO auth_password_resets(token_hash,user_id,email,expires_at) VALUES(%s,%s,%s,{expiry})', (digest, user.user_id, address))
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        c.execute('DELETE FROM auth_users WHERE id=%s', (user.user_id,))
        assert c.execute('SELECT count(*) FROM auth_password_resets WHERE user_id=%s', (user.user_id,)).fetchone() == (0,)
        c.execute('DELETE FROM workspaces WHERE id=%s', (user.workspace_id,))
