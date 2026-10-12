"""Readiness rejects weakened Team grants and managed-owner configuration."""
import os
import pytest
import psycopg
from app.models.database import _connection_is_ready

pytestmark=pytest.mark.integration


@pytest.fixture
def connection():
    if not os.getenv('TEST_DATABASE_URL'):pytest.skip('Requires disposable PostgreSQL')
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        yield c
        c.rollback()


def ready(c):
    with c.transaction():
        c.execute('SET LOCAL ROLE flare_app')
        return _connection_is_ready(c)


def test_current_team_schema_is_ready_with_capability_disabled(connection):
    assert ready(connection)


@pytest.mark.parametrize('grant',[
    'GRANT SELECT ON team_invitations TO flare_app',
    'GRANT UPDATE ON team_tasks TO flare_app',
    'GRANT SELECT ON team_projects TO flare_worker',
    'GRANT EXECUTE ON FUNCTION _team_actor() TO flare_app',
    'GRANT EXECUTE ON FUNCTION _team_workspace_paid(uuid) TO flare_worker',
    'GRANT EXECUTE ON FUNCTION team_projects_list() TO PUBLIC',
])
def test_readiness_rejects_private_or_cross_runtime_grants(connection,grant):
    connection.execute(grant)
    assert not ready(connection)


def test_readiness_rejects_missing_invitation_capability(connection):
    connection.execute('ALTER FUNCTION team_invitation_preview(text) RENAME TO disabled_invitation_preview')
    assert not ready(connection)


def test_readiness_rejects_missing_worker_entitlement_guard(connection):
    definition=connection.execute("SELECT pg_get_functiondef('materialize_analysis_cycles(timestamptz,integer)'::regprocedure)").fetchone()[0]
    assert ' AND public._team_workspace_paid(s.workspace_id)' in definition
    connection.execute(definition.replace(' AND public._team_workspace_paid(s.workspace_id)',''))
    assert not ready(connection)


def test_managed_owner_marker_cannot_be_inherited_by_other_capabilities(connection):
    owner=connection.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='team_projects_list()'::regprocedure").fetchone()[0]
    if owner!='flare_owner':pytest.skip('Managed owner only')
    settings=connection.execute("SELECT proconfig FROM pg_proc WHERE oid='provision_workspace(uuid,text)'::regprocedure").fetchone()[0]
    assert 'application_name=flare-runtime' in settings
    connection.execute('ALTER FUNCTION provision_workspace(uuid,text) RESET application_name')
    assert not ready(connection)
