"""Readiness detects loosened source credential/capability grants."""
import os
import psycopg
import pytest
from app.models.database import _source_storage_is_safe

pytestmark=pytest.mark.integration


@pytest.mark.parametrize('change',[
    'GRANT SELECT(credential_blob) ON source_connections TO flare_app',
    'GRANT EXECUTE ON FUNCTION source_worker_step(uuid,uuid,bigint,text,jsonb) TO flare_app',
    'GRANT SELECT ON source_worker_health TO flare_worker',
    'ALTER TABLE source_auth_states NO FORCE ROW LEVEL SECURITY',
    'GRANT EXECUTE ON FUNCTION source_api(text,uuid,jsonb) TO PUBLIC',
])
def test_source_readiness_rejects_private_boundary_regressions(change):
    url=os.getenv('TEST_DATABASE_URL')
    if not url: pytest.skip('Disposable database required')
    with psycopg.connect(url) as connection:
        try:
            connection.execute('SET LOCAL ROLE flare_app')
            assert _source_storage_is_safe(connection)
            connection.execute('RESET ROLE'); connection.execute(change)
            connection.execute('SET LOCAL ROLE flare_app')
            assert not _source_storage_is_safe(connection)
        finally: connection.rollback()
