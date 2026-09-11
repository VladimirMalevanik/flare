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
    migration = load_migration('0008_github_connections.py')
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
