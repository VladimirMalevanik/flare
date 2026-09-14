"""Fast checks for the Yandex migration path without a cloud database."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def load_migration(filename: str):
    spec = spec_from_file_location("test_" + filename.removesuffix(".py"), VERSIONS / filename)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class FakeBind:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute(self, query):
        self.queries.append(str(query))
        return FakeResult(self.row)


class FakeOp:
    def __init__(self, row=None):
        self.bind = FakeBind(row)
        self.statements = []

    def get_bind(self):
        return self.bind

    def execute(self, statement):
        self.statements.append(str(statement))


SAFE_PREREQUISITES = (
    "flare_owner",
    "flare_owner",
    False,
    False,
    False,
    False,
    True,
    True,
    True,
    True,
)


def test_yandex_initial_migration_requires_control_plane_prerequisites(monkeypatch):
    migration = load_migration("0001_initial.py")
    operation = FakeOp(SAFE_PREREQUISITES)
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "yandex")

    migration.upgrade()

    sql = "\n".join(operation.statements)
    assert "CREATE EXTENSION" not in sql
    assert "CREATE TABLE public.workspaces" in sql
    assert "pg_auth_members" in operation.bind.queries[0]
    assert "to_regtype('vector')" in operation.bind.queries[0]


def test_yandex_initial_migration_fails_before_schema_ddl(monkeypatch):
    migration = load_migration("0001_initial.py")
    unsafe = (*SAFE_PREREQUISITES[:-1], False)
    operation = FakeOp(unsafe)
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "yandex")

    with pytest.raises(RuntimeError, match="Yandex migrations require"):
        migration.upgrade()

    assert operation.statements == []


def test_yandex_initial_migration_rejects_owner_role_membership(monkeypatch):
    migration = load_migration("0001_initial.py")
    unsafe = list(SAFE_PREREQUISITES)
    unsafe[6] = False
    operation = FakeOp(tuple(unsafe))
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "yandex")

    with pytest.raises(RuntimeError, match="membership-free flare_owner"):
        migration.upgrade()

    assert operation.statements == []


@pytest.mark.parametrize("filename", ["0004_auth.py", "0005_analysis_jobs.py"])
def test_yandex_migrations_do_not_manage_cluster_roles(monkeypatch, filename):
    migration = load_migration(filename)
    operation = FakeOp()
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "yandex")

    migration.upgrade()

    sql = "\n".join(operation.statements)
    assert "CREATE ROLE" not in sql
    assert "flare_onboarding" not in sql
    assert "flare_job_executor" not in sql
    if filename == "0005_analysis_jobs.py":
        assert "TO flare_owner" in sql
        assert "TO flare_worker" in sql


@pytest.mark.parametrize("filename", ["0004_auth.py", "0005_analysis_jobs.py"])
def test_self_managed_migrations_keep_existing_role_provisioning(monkeypatch, filename):
    migration = load_migration(filename)
    operation = FakeOp()
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "self-managed")

    migration.upgrade()

    sql = "\n".join(operation.statements)
    assert "CREATE ROLE" in sql
    expected_owner = "flare_onboarding" if filename == "0004_auth.py" else "flare_job_executor"
    assert "OWNER TO " + expected_owner in sql


@pytest.mark.parametrize('provider,owner', [
    ('self-managed', 'flare_job_executor'), ('yandex', 'flare_owner'),
])
def test_flare_migration_uses_selected_capability_owner(monkeypatch, provider, owner):
    migration = load_migration('0006_real_flares.py')
    operation = FakeOp()
    monkeypatch.setattr(migration, 'op', operation)
    monkeypatch.setenv('FLARE_DATABASE_PROVIDER', provider)
    migration.upgrade()
    sql = '\n'.join(operation.statements)
    assert 'CREATE ROLE' not in sql
    if provider == 'yandex':
        assert 'flare_job_executor' not in sql
    for fragment in (
        'GRANT SELECT,INSERT,UPDATE ON public.flare_generation_runs TO ',
        'CREATE POLICY flare_run_executor ON public.flare_generation_runs TO ',
        'GRANT SELECT,INSERT ON public.insights,public.insight_sources TO ',
        'CREATE POLICY flare_writer ON public.insights AS RESTRICTIVE TO ',
        'CREATE POLICY flare_writer ON public.insight_sources AS RESTRICTIVE TO ',
    ):
        assert fragment + owner in sql
    assert sql.count('OWNER TO ' + owner) == 6
    assert sql.count('FROM PUBLIC') == 7


@pytest.mark.parametrize('provider', ['self-managed', 'yandex'])
def test_github_migration_is_provider_agnostic_and_keeps_rls(monkeypatch, provider):
    migration = load_migration('0009_github_connections.py')
    operation = FakeOp()
    monkeypatch.setattr(migration, 'op', operation)
    monkeypatch.setenv('FLARE_DATABASE_PROVIDER', provider)
    migration.upgrade()
    sql = '\n'.join(operation.statements)
    assert 'CREATE ROLE' not in sql
    assert 'github_connection_states' in sql
    assert 'github_connections' in sql
    assert 'authorized_user_id' in sql
    assert 'authorized_user_login' in sql
    assert sql.count('ENABLE ROW LEVEL SECURITY') == 2
    assert sql.count('FORCE ROW LEVEL SECURITY') == 2
    assert "m.role IN ('owner', 'editor')" in sql


@pytest.mark.parametrize('provider', ['self-managed', 'yandex'])
def test_post_github_queue_analytics_and_import_migrations_keep_worker_isolated(monkeypatch, provider):
    queue = load_migration('0011_queue_ops_maintenance.py')
    analytics = load_migration('0012_activity_events_and_source_types.py')
    imports = load_migration('0013_import_batches.py')
    editing = load_migration('0014_versioned_source_editing.py')
    operations = []
    for migration in (queue, analytics, imports, editing):
        operation = FakeOp()
        monkeypatch.setattr(migration, 'op', operation)
        monkeypatch.setenv('FLARE_DATABASE_PROVIDER', provider)
        migration.upgrade()
        operations.append('\n'.join(operation.statements))

    queue_sql, analytics_sql, import_sql, editing_sql = operations
    assert all('CREATE ROLE' not in sql for sql in operations)
    assert 'queue_maintenance' in queue_sql
    assert 'GRANT EXECUTE ON FUNCTION public.queue_maintenance' in queue_sql
    assert 'GRANT DELETE ON public.analysis_jobs, public.flare_generation_runs TO ' in queue_sql
    assert 'IF p_recover_stale AND NOT p_dry_run THEN' in queue_sql
    assert 'FROM public.flare_generation_runs r' in queue_sql
    if provider == 'self-managed':
        assert 'OWNER TO flare_job_executor' in queue_sql
    else:
        assert 'OWNER TO flare_job_executor' not in queue_sql
    assert 'activity_events' in analytics_sql
    assert analytics_sql.count('FORCE ROW LEVEL SECURITY') == 1
    assert 'CREATE POLICY activity_event_member_access' in analytics_sql
    assert 'CREATE POLICY activity_event_actor_insert' in analytics_sql
    assert "actor_id = nullif(current_setting('app.user_id', true), '')" in analytics_sql
    assert 'import_batches' in import_sql
    assert import_sql.count('FORCE ROW LEVEL SECURITY') == 1
    assert "GRANT SELECT, INSERT, UPDATE ON public.import_batches TO flare_app" in import_sql
    assert "ADD COLUMN updated_at" in editing_sql
    assert "document_version_id" in editing_sql
    assert "import_batches_active_hash_unique" in editing_sql
    assert "superseded_at" in editing_sql
    assert "item_updated" in editing_sql
    assert "source_replaced" in editing_sql


@pytest.mark.parametrize('provider,owner', [
    ('self-managed', 'flare_job_executor'), ('yandex', 'flare_owner'),
])
def test_daily_schedule_migration_uses_execute_only_worker_capabilities(monkeypatch, provider, owner):
    migration = load_migration('0015_daily_analysis_schedule.py')
    operation = FakeOp()
    monkeypatch.setattr(migration, 'op', operation)
    monkeypatch.setenv('FLARE_DATABASE_PROVIDER', provider)
    migration.upgrade()
    sql = '\n'.join(operation.statements)
    assert 'CREATE ROLE' not in sql
    assert 'analysis_cycles_workspace_local_date_key UNIQUE (workspace_id, local_date)' in sql
    assert sql.count('FORCE ROW LEVEL SECURITY') == 3
    assert f'CREATE POLICY cycle_executor ON public.analysis_cycles TO {owner}' in sql
    assert f'OWNER TO {owner}' in sql
    assert 'GRANT EXECUTE ON FUNCTION public.claim_analysis_cycle_refresh' in sql
    assert 'TO flare_worker' in sql
    assert 'GRANT SELECT ON public.analysis_cycles TO flare_worker' not in sql
