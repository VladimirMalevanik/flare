"""Validate the pinned temporary core fallback on a private Unix-only PostgreSQL17.

Never reads ambient database URLs, dotenv, cloud credentials or provider keys.
From the repository: python backend/scripts/check_schema21_core_fallback.py --pg-bin /path/to/bin
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import tempfile
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pwdlib import PasswordHash


def load_builder(repository):
    spec = importlib.util.spec_from_file_location("fallback_builder", repository / "backend/deploy/build_schema21_core_fallback.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_sources(repository, target, revision, paths):
    archive = subprocess.check_output(["git", "archive", revision, *paths], cwd=repository)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(target, filter="data")


TABLES = ("workspaces", "workspace_members", "auth_users", "auth_sessions", "auth_legal_acceptances",
          "documents", "document_versions", "chunks", "analysis_jobs", "analysis_job_sources", "analysis_runs",
          "analysis_cycles", "analysis_cycle_sources", "analysis_daily_quotas", "insights", "insight_sources",
          "flare_generation_runs")


def snapshot(connection, workspace_ids):
    result = {}
    for table in TABLES:
        column = "id" if table == "workspaces" else "initial_workspace_id" if table == "auth_users" else "workspace_id"
        predicate = sql.SQL("user_id IN (SELECT id FROM auth_users WHERE initial_workspace_id=ANY(%s))") if table == "auth_legal_acceptances" else sql.SQL("{}=ANY(%s)").format(sql.Identifier(column))
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) FROM public.{} t WHERE {} ORDER BY to_jsonb(t)::text").format(sql.Identifier(table), predicate), (workspace_ids,)).fetchall()
        result[table] = [row[0] for row in rows]
    return result


def assert_preserved(before, after):
    for table, old_rows in before.items():
        new_rows = after[table]
        assert len(old_rows) == len(new_rows), (table, "row count changed")
        columns = old_rows[0].keys() if old_rows else ()
        old = sorted(json.dumps(row, sort_keys=True) for row in old_rows)
        new = sorted(json.dumps({key: row[key] for key in columns}, sort_keys=True) for row in new_rows)
        assert old == new, (table, "original column changed")


def seed_0018(admin):
    from app.legal import CURRENT_TERMS_VERSION, CURRENT_PRIVACY_VERSION, CURRENT_TERMS_CONTENT_ID, CURRENT_PRIVACY_CONTENT_ID
    from app.config import AISettings
    from app.ai_engine.flare_config import FlareSettings
    from app.workers.config import pipeline_revision
    wid, foreign, document, version, chunk = [uuid4() for _ in range(5)]
    user, foreign_user = "auth:" + str(uuid4()), "auth:" + str(uuid4())
    token = secrets.token_urlsafe(32)
    password = "disposable-recovery-password"
    with psycopg.connect(admin) as connection:
        for workspace, actor, email in [(wid, user, "owner@recovery.invalid"), (foreign, foreign_user, "foreign@recovery.invalid")]:
            connection.execute("INSERT INTO workspaces(id,name) VALUES(%s,'Preserved recovery workspace')", (workspace,))
            connection.execute("INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'owner')", (workspace, actor))
            connection.execute("INSERT INTO auth_users(id,email,password_hash,name,initial_workspace_id,email_verified_at) VALUES(%s,%s,%s,'Recovery',%s,now())", (actor, email, PasswordHash.recommended().hash(password), workspace))
            connection.execute("INSERT INTO auth_legal_acceptances(user_id,terms_version,privacy_version,terms_content_id,privacy_content_id) VALUES(%s,%s,%s,%s,%s)", (actor, CURRENT_TERMS_VERSION, CURRENT_PRIVACY_VERSION, CURRENT_TERMS_CONTENT_ID, CURRENT_PRIVACY_CONTENT_ID))
        connection.execute("INSERT INTO auth_sessions(token_hash,user_id,workspace_id,expires_at) VALUES(%s,%s,%s,now()+interval '1 day')", (sha256(token.encode()).hexdigest(), user, wid))
        content = "Our goal is to ship the MVP this week, but the core analysis flow is unfinished."
        connection.execute("INSERT INTO documents(id,workspace_id,title,source_type) VALUES(%s,%s,'Preserved goal','note')", (document, wid))
        connection.execute("INSERT INTO document_versions(id,workspace_id,document_id,version_number,content_hash,parser_version,state) VALUES(%s,%s,%s,1,%s,'manual-note-v1','processing')", (version, wid, document, sha256(content.encode()).hexdigest()))
        connection.execute("INSERT INTO chunks(id,workspace_id,document_version_id,ordinal,content,locator) VALUES(%s,%s,%s,0,%s,'{}')", (chunk, wid, version, content))
        connection.execute("UPDATE document_versions SET state='ready' WHERE id=%s", (version,))
        connection.execute("UPDATE documents SET current_version_id=%s WHERE id=%s", (version, document))
        connection.execute("SET LOCAL ROLE flare_app")
        connection.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)", (str(wid), user))
        ai = AISettings()
        run = connection.execute("SELECT public.start_daily_analysis_run(%s,%s,%s,%s,%s,3,%s,%s)", (uuid4(), [chunk], "recovery-preserved", pipeline_revision(ai), FlareSettings().revision(ai), ai.max_sources, ai.max_input_bytes)).fetchone()[0]
        connection.execute("RESET ROLE")
        job = connection.execute("SELECT analysis_job_id FROM analysis_runs WHERE id=%s", (run,)).fetchone()[0]
        before = snapshot(connection, [wid, foreign])
    return dict(workspace=wid, foreign=foreign, user=user, foreign_user=foreign_user, document=document,
                chunk=chunk, token=token, password=password, job=job, run=run, before=before)


def transfer_to_restricted_admin(admin):
    with psycopg.connect(admin) as connection:
        connection.execute("GRANT USAGE,CREATE ON SCHEMA public TO flare_admin WITH GRANT OPTION")
        for name, kind in connection.execute("SELECT relname,relkind FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN('r','S')").fetchall():
            connection.execute(sql.SQL("ALTER {} {} OWNER TO flare_admin").format(sql.SQL("SEQUENCE" if kind == "S" else "TABLE"), sql.Identifier("public", name)))
        for (signature,) in connection.execute("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace='public'::regnamespace AND proowner='recovery_bootstrap'::regrole AND NOT EXISTS(SELECT 1 FROM pg_depend WHERE objid=pg_proc.oid AND deptype='e')").fetchall():
            connection.execute(sql.SQL("ALTER FUNCTION {} OWNER TO flare_admin").format(sql.SQL(signature)))


def recovery_behavior(admin, app_url, worker_url, fixture):
    from fastapi.testclient import TestClient
    from app.config import Settings, AISettings
    from app.main import create_app
    from app.models.database import Database, WorkspaceIdentity, database_is_ready
    from app.models.analysis_jobs import WorkerJobs
    from app.models.flare_runs import FlareRuns
    from app.ai_engine.flare_config import FlareSettings
    from app.services.analysis_jobs import AnalysisProcessor
    from app.services.flare_generation import FlareProcessor
    from app.workers.config import WorkerSettings
    from test_analysis_jobs import FakeAnalyzer
    from test_flare_runs import Detector
    from test_email_verification import CapturingSender, message_token

    assert database_is_ready(app_url)
    # A privilege error cannot be hidden by the fallback's old readiness.
    with psycopg.connect(admin) as connection:
        connection.execute("GRANT SELECT ON public.billing_webhook_events TO flare_app")
    try:
        assert not database_is_ready(app_url), "private billing ledger leakage accepted"
    finally:
        with psycopg.connect(admin) as connection:
            connection.execute("REVOKE SELECT ON public.billing_webhook_events FROM flare_app")
    assert database_is_ready(app_url)
    ai, worker = AISettings(), WorkerSettings()
    assert asyncio.run(AnalysisProcessor(WorkerJobs(worker_url), FakeAnalyzer(), ai, worker).process_one()) == "completed"
    assert asyncio.run(FlareProcessor(FlareRuns(worker_url), Detector(), ai, FlareSettings(), worker).process_one()) == "completed"
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT status FROM analysis_jobs WHERE id=%s", (fixture["job"],)).fetchone() == ("completed",)
        assert connection.execute("SELECT count(*) FROM insights WHERE source_analysis_job_id=%s", (fixture["job"],)).fetchone() == (1,)
        assert connection.execute("SELECT content FROM chunks WHERE id=%s", (fixture["chunk"],)).fetchone()[0] == fixture["before"]["chunks"][0]["content"]
        # Ready-looking but unpublished ZIP source must remain hidden from all
        # old readers, export and source selection.
        package, document, version, chunk = [uuid4() for _ in range(4)]
        connection.execute("INSERT INTO import_packages(id,workspace_id,requested_by_user_id,source_kind,file_name,file_size,request_key,policy,status,expires_at) VALUES(%s,%s,%s,'obsidian','pending.zip',10,%s,'{}','processing',now()+interval '1 day')", (package, fixture["workspace"], fixture["user"], uuid4()))
        connection.execute("INSERT INTO documents(id,workspace_id,title,source_type,import_package_id) VALUES(%s,%s,'HIDDEN_PENDING_ZIP','file',%s)", (document, fixture["workspace"], package))
        connection.execute("INSERT INTO document_versions(id,workspace_id,document_id,version_number,content_hash,parser_version,state) VALUES(%s,%s,%s,1,%s,'fixture','processing')", (version, fixture["workspace"], document, "a"*64))
        connection.execute("INSERT INTO chunks(id,workspace_id,document_version_id,ordinal,content,locator) VALUES(%s,%s,%s,0,'HIDDEN_PENDING_ZIP','{}')", (chunk, fixture["workspace"], version))
        connection.execute("UPDATE document_versions SET state='ready' WHERE id=%s", (version,))
        connection.execute("UPDATE documents SET current_version_id=%s WHERE id=%s", (version, document))

    sender = CapturingSender()
    configured = Settings(database_url=app_url, environment="test", cors_origins=["http://testserver"],
                          email_verification_required=True, app_public_url="http://localhost:3000")
    with TestClient(create_app(configured, email_sender=sender), headers={"Origin": "http://testserver"}) as client:
        client.cookies.set("flare_session", fixture["token"])
        assert client.get("/auth/me").json()["user"]["emailVerified"] is True
        assert client.get("/items/" + str(fixture["document"])).status_code == 200
        assert client.get("/items/" + str(document)).status_code == 404
        assert "HIDDEN_PENDING_ZIP" not in client.get("/items").text
        blocked = client.post("/analyze", json={}, headers={"Idempotency-Key": str(uuid4())})
        assert blocked.status_code == 409 and blocked.json() == {"detail": "daily_limit"}
        archive = client.get("/export")
        assert archive.status_code == 200
        with ZipFile(io.BytesIO(archive.content)) as zipped:
            assert "HIDDEN_PENDING_ZIP" not in zipped.read("raw/export.json").decode()
            assert len(json.loads(zipped.read("raw/export.json"))["flares"]) == 1
        client.cookies.clear()
        payload = dict(email="new@recovery.invalid", password=fixture["password"], name="Recovered signup", termsAccepted=True, privacyAccepted=True)
        assert client.post("/auth/register", json=payload).status_code == 201
        assert client.post("/items", json={"type": "note", "content": "blocked"}).status_code == 403
        assert client.post("/auth/verify-email", json={"token": message_token(sender)}).status_code == 200
        assert client.post("/items", json={"type": "note", "content": "Verified recovery"}).status_code == 201
        assert client.get("/items/" + str(fixture["document"])).status_code == 404
        assert client.delete("/items/" + str(fixture["document"])).status_code == 404
        assert client.get("/billing/status").status_code == 404
        assert client.post("/billing/paddle/webhook", headers={"Origin": ""}, json={}).status_code == 403
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT verification_provenance FROM auth_users WHERE email='new@recovery.invalid'").fetchone() == ("legacy_unknown",)
    database = Database(app_url)
    database.open()
    try:
        identity = WorkspaceIdentity(fixture["workspace"], fixture["user"])
        with database.workspace_transaction(identity) as connection:
            assert connection.execute("SELECT id FROM documents WHERE id=%s", (document,)).fetchall() == []
            assert connection.execute("SELECT id FROM document_versions WHERE id=%s", (version,)).fetchall() == []
            assert connection.execute("SELECT id FROM chunks WHERE id=%s", (chunk,)).fetchall() == []
            assert connection.execute("SELECT workspace_id FROM documents WHERE workspace_id=%s", (fixture["foreign"],)).fetchall() == []
            try:
                with connection.transaction():
                    connection.execute("SELECT token_hash FROM billing_checkout_intents")
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError("private checkout token readable")
        # Migration0019 now rejects this malicious parent reference at its
        # restrictive RLS gate, before the historical composite FK check.
        foreign_identity = WorkspaceIdentity(fixture["foreign"], fixture["foreign_user"])
        with database.workspace_transaction(foreign_identity) as connection:
            try:
                with connection.transaction():
                    connection.execute("INSERT INTO document_versions(workspace_id,document_id,version_number,content_hash,parser_version) VALUES(%s,%s,2,%s,'recovery-denied')", (fixture["foreign"], fixture["document"], "b"*64))
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError("cross-workspace parent reference was accepted")
        with psycopg.connect(admin) as connection:
            assert connection.execute("SELECT count(*) FROM document_versions WHERE workspace_id=%s AND document_id=%s", (fixture["foreign"], fixture["document"])).fetchone() == (0,)
    finally:
        database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    builder = load_builder(repository)
    binary = lambda name: str(Path(args.pg_bin) / name)
    with tempfile.TemporaryDirectory(prefix="flare-core-recovery-", dir="/tmp") as temporary:
        root = Path(temporary)
        candidate, migrations, historical = root / "candidate", root / "migration", root / "historical"
        manifest = builder.build_sources(repository, candidate)
        archive_sources(repository, migrations, builder.ACCEPTED_DATABASE_SHA, ["backend"])
        archive_sources(repository, historical, builder.LEGACY_CORE_SHA, ["backend/tests"])
        backend = candidate / "backend"
        sys.dont_write_bytecode = True
        sys.path[:0] = [str(backend), str(historical / "backend/tests")]
        # Deny every TCP provider call in this process and its Python children.
        offline = root / "offline"
        offline.mkdir()
        (offline / "sitecustomize.py").write_text("import os,sys\nfrom pathlib import Path\ndef offline(event,args):\n if event=='socket.connect' and isinstance(args[1],tuple): raise RuntimeError('Recovery check forbids TCP/provider calls')\n if event=='subprocess.Popen' and args[3] is not None:\n  args[3]['PYTHONPATH']=str(Path(__file__).parent)+os.pathsep+args[3].get('PYTHONPATH','')\nsys.addaudithook(offline)\n")
        (offline / "recovery_pytest_roles.py").write_text("import os,pytest\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_call(item):\n old=os.environ.get('FLARE_PROCESS_ROLE')\n if item.name=='test_independent_worker_process': os.environ['FLARE_PROCESS_ROLE']='worker'\n try: yield\n finally:\n  if old is None: os.environ.pop('FLARE_PROCESS_ROLE',None)\n  else: os.environ['FLARE_PROCESS_ROLE']=old\n")
        env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C", "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "FLARE_ENV": "test", "FLARE_PROCESS_ROLE": "migration", "FLARE_DATABASE_PROVIDER": "self-managed",
               "APP_PASSWORD": "disposable-only", "WORKER_PASSWORD": "disposable-only", "PYTHONPATH": str(offline) + os.pathsep + str(backend)}
        os.environ.clear()
        os.environ.update(env)
        def forbid_tcp(event, values):
            if event == "socket.connect" and isinstance(values[1], tuple):
                raise RuntimeError("Recovery check forbids TCP/provider calls")
        sys.addaudithook(forbid_tcp)
        run = lambda command, **kw: subprocess.run(command, check=True, stdout=subprocess.DEVNULL, **kw)
        data = str(root / "data")
        run([binary("initdb"), "-D", data, "-U", "recovery_bootstrap", "--auth=trust", "--encoding=UTF8", "--no-locale"])
        start = [binary("pg_ctl"), "-D", data, "-l", str(root / "postgres.log"), "-o", f"-h '' -k {root}", "-w", "start"]
        try:
            run(start)
        except subprocess.CalledProcessError:
            print((root / "postgres.log").read_text(), file=sys.stderr)
            subprocess.run([binary("pg_ctl"), "-D", data, "-m", "immediate", "-w", "stop"], stdout=subprocess.DEVNULL, check=False)
            raise
        try:
            admin = make_conninfo(host=str(root), dbname="postgres", user="recovery_bootstrap")
            run([binary("psql"), admin, "-v", "ON_ERROR_STOP=1", "-f", str(migrations / "backend/db/init-role.sql")], env=env)
            with psycopg.connect(admin) as connection:
                assert int(connection.execute("SHOW server_version_num").fetchone()[0]) // 10000 == 17
                connection.execute("CREATE ROLE flare_admin LOGIN NOSUPERUSER NOCREATEDB CREATEROLE INHERIT BYPASSRLS")
            migrate = [sys.executable, "-m", "alembic", "-c", str(migrations / "backend/alembic.ini"), "upgrade"]
            migration_env = dict(env, PYTHONPATH=str(offline)+os.pathsep+str(migrations / "backend"), MIGRATION_DATABASE_URL=f"postgresql+psycopg://recovery_bootstrap@/postgres?host={root}")
            run(migrate + ["0018"], env=migration_env, cwd=migrations / "backend")
            fixture = seed_0018(admin)
            app_url = f"postgresql://flare_app@/postgres?host={root}"
            worker_url = f"postgresql://flare_worker@/postgres?host={root}"
            from app.models.database import database_is_ready
            assert not database_is_ready(app_url), "0021 fallback accepted0018"
            with psycopg.connect(admin) as connection:
                connection.execute("GRANT flare_job_executor TO flare_admin WITH ADMIN TRUE,INHERIT TRUE,SET TRUE")
            transfer_to_restricted_admin(admin)
            migration_env["MIGRATION_DATABASE_URL"] = f"postgresql+psycopg://flare_admin@/postgres?host={root}"
            run(migrate + ["0021"], env=migration_env, cwd=migrations / "backend")
            run(migrate + ["0021"], env=migration_env, cwd=migrations / "backend")
            with psycopg.connect(admin) as connection:
                assert_preserved(fixture["before"], snapshot(connection, [fixture["workspace"], fixture["foreign"]]))
            recovery_behavior(admin, app_url, worker_url, fixture)
            with psycopg.connect(admin) as connection:
                before_restart = snapshot(connection, [fixture["workspace"], fixture["foreign"]])
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0021",)
            run([binary("pg_ctl"), "-D", data, "-m", "fast", "-w", "stop"])
            run(start)
            with psycopg.connect(admin) as connection:
                assert snapshot(connection, [fixture["workspace"], fixture["foreign"]]) == before_restart
            assert database_is_ready(app_url)
            from fastapi.testclient import TestClient
            from app.config import Settings
            from app.main import create_app
            restart_settings = Settings(database_url=app_url, environment="test", cors_origins=["http://testserver"], email_verification_required=True, app_public_url="http://localhost:3000")
            with TestClient(create_app(restart_settings), headers={"Origin": "http://testserver"}) as client:
                client.cookies.set("flare_session", fixture["token"])
                assert client.get("/auth/me").json()["user"]["emailVerified"] is True
                assert client.get("/items/" + str(fixture["document"])).status_code == 200
            # Historical migrations create cluster-wide roles. Use an entirely
            # separate Unix-only cluster, not a second DB sharing those roles or
            # the preserved queue and tenants.
            test_root = root / "core-tests"
            test_root.mkdir(mode=0o700)
            test_data = str(test_root / "data")
            run([binary("initdb"), "-D", test_data, "-U", "recovery_bootstrap", "--auth=trust", "--encoding=UTF8", "--no-locale"])
            run([binary("pg_ctl"), "-D", test_data, "-l", str(test_root / "postgres.log"), "-o", f"-h '' -k {test_root}", "-w", "start"])
            test_admin = make_conninfo(host=str(test_root), dbname="postgres", user="recovery_bootstrap")
            run([binary("psql"), test_admin, "-v", "ON_ERROR_STOP=1", "-f", str(migrations / "backend/db/init-role.sql")], env=env)
            migration_env["MIGRATION_DATABASE_URL"] = f"postgresql+psycopg://recovery_bootstrap@/postgres?host={test_root}"
            run(migrate + ["0021"], env=migration_env, cwd=migrations / "backend")
            tests = ["test_database.py", "test_auth_api.py", "test_email_verification.py", "test_items_api.py", "test_imports_api.py",
                     "test_export_api.py", "test_analysis_runs.py", "test_analysis_jobs.py", "test_flare_runs.py",
                     "test_daily_analysis_schedule_integration.py", "test_analysis_worker.py"]
            test_env = dict(env, PYTHONPATH=str(offline)+os.pathsep+str(backend)+os.pathsep+str(historical / "backend/tests"), FLARE_PROCESS_ROLE="api", DATABASE_URL=f"postgresql://flare_app@/postgres?host={test_root}",
                            TEST_DATABASE_URL=test_admin, WORKER_DATABASE_URL=f"postgresql://flare_worker@/postgres?host={test_root}")
            try:
                obsolete = "tests/test_database.py::test_cross_tenant_parent_reference_is_rejected"
                results = root / "historical-core-results.xml"
                subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "recovery_pytest_roles", "-o", "markers=integration: disposable PostgreSQL runtime check", "--rootdir", str(historical / "backend"), "--junitxml", str(results), "--deselect", obsolete, *[str(historical / "backend/tests" / test) for test in tests]], cwd=backend, env=test_env, check=True)
                cases = list(ElementTree.parse(results).getroot().iter("testcase"))
                assert cases and all(not list(case) for case in cases), "Historical core suite must have no skipped/failed cases"
            finally:
                subprocess.run([binary("pg_ctl"), "-D", test_data, "-m", "immediate", "-w", "stop"], stdout=subprocess.DEVNULL, check=False)
            builder.verify_sources(repository, candidate)
            report = {"status": "passed", "sources_sha256": manifest["sources_sha256"], "legacy_core_sha": builder.LEGACY_CORE_SHA,
                      "accepted_database_sha": builder.ACCEPTED_DATABASE_SHA, "schema_revision": "0021", "postgres_major": 17,
                      "migration_principal": "NOSUPERUSER CREATEROLE BYPASSRLS (fixture only)", "core_test_files": tests, "historical_core_tests_passed": len(cases),
                      "preserved_0018_upgrade": True, "accepted_readiness_negative": True, "pending_zip_invisible": True,
                      "stored_fake_provider_flare": True, "same_schema_restart": True, "provider_calls": False,
                      "billing_zip_privacy_ui_available": False, "cloud_mutations": False,
                      "excluded_historical_cases": ["test_database.py::test_cross_tenant_parent_reference_is_rejected (FK-only expectation obsolete; replaced by explicit import_gate RLS denial and zero inserted rows)"],
                      "worker_fixture_environment": "test_independent_worker_process runs with explicit FLARE_PROCESS_ROLE=worker; legacy assertion unchanged"}
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
            print("PASS: preserved0018→restricted0021; legacy verified auth/queue/Flare/isolation; authoritative readiness; ZIP fence; restart; historical core suite", flush=True)
        finally:
            if (root / "core-tests/data/postmaster.pid").exists():
                subprocess.run([binary("pg_ctl"), "-D", str(root / "core-tests/data"), "-m", "immediate", "-w", "stop"], stdout=subprocess.DEVNULL, check=False)
            subprocess.run([binary("pg_ctl"), "-D", data, "-m", "immediate", "-w", "stop"], stdout=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    main()
