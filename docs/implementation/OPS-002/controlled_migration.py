"""Operator-only, exact-source migration. Never installed as an API component.

Run in the existing Azure App Service container with its existing managed identity.
Stage the pinned git archive separately. Default action is read-only preflight.
The apply action requires the temporary 503 maintenance process and a drained,
stopped worker verified separately by the operator. Output contains aggregates and
status only; credentials and raw exception/subprocess output are never written.
"""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import psycopg
from psycopg.conninfo import conninfo_to_dict

SOURCE_SHA = "453ebec4b6592d1e089a3f5d04da0f35a78a4f09"
ARCHIVE_SHA256 = "dd7d86072eb1095832137697928f24240edd5c5edfa0e6e10a591ecc8e5311dc"
ARCHIVE = Path("/home/LogFiles/flare-ops002-migration-source.tar.gz")
SOURCE_ROOT = Path("/home/data/flare-ops002-migration")
RESULT = Path("/home/LogFiles/flare-ops002-migration-result.json")
HOST = "flare-dev-pg-vm-260914.postgres.database.azure.com"
TABLES = ("auth_users", "auth_sessions", "workspaces", "workspace_members",
          "documents", "document_versions", "chunks", "insights", "insight_sources")


def migration_credential():
    endpoint = os.environ["IDENTITY_ENDPOINT"]
    parsed = urllib.parse.urlsplit(endpoint)
    local = parsed.hostname in {"localhost", "127.0.0.1"}
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_link_local
    except ValueError:
        pass
    if parsed.scheme != "http" or not local or parsed.username or parsed.password:
        raise RuntimeError("unexpected identity endpoint")
    parameters = urllib.parse.urlencode({"resource": "https://vault.azure.net",
                                        "api-version": "2019-08-01"})
    request = urllib.request.Request(endpoint + "?" + parameters,
                                    headers={"X-IDENTITY-HEADER": os.environ["IDENTITY_HEADER"]})
    with urllib.request.urlopen(request, timeout=15) as response:
        token = json.load(response)["access_token"]
    request = urllib.request.Request(
        "https://flare-dev-kv-260914.vault.azure.net/secrets/migration-database-url?api-version=7.4",
        headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=15) as response:
        credential = json.load(response)["value"]
    token = ""
    native = credential.replace("postgresql+psycopg://", "postgresql://", 1)
    info = conninfo_to_dict(native)
    if info.get("host") != HOST or info.get("user") != "flare_admin":
        raise RuntimeError("unexpected migration database")
    if info.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError("migration requires existing TLS configuration")
    return credential, native


def snapshot(native):
    with psycopg.connect(native, connect_timeout=10,
                         options="-c default_transaction_read_only=on -c statement_timeout=10000") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM public.alembic_version ORDER BY version_num")
            heads = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT current_user, rolsuper, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            role = cursor.fetchone()
            if role != ("flare_admin", False, True, True):
                raise RuntimeError("unexpected administrator restrictions")
            counts = {}
            for table in TABLES:
                cursor.execute('SELECT count(*) FROM public."' + table + '"')
                counts[table] = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM public.analysis_jobs WHERE status='processing'")
            jobs = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM public.flare_generation_runs WHERE status='processing'")
            runs = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM public.analysis_cycles WHERE refresh_status='refreshing'")
            refreshes = cursor.fetchone()[0]
            return {"heads": heads, "preservedTableCounts": counts,
                    "activeAnalysisJobs": jobs, "activeFlareRuns": runs,
                    "activeRefreshes": refreshes, "administratorRestrictionsVerified": True}


def exact_source():
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("source archive checksum mismatch")
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if SOURCE_ROOT.is_symlink():
        raise RuntimeError("unexpected migration source root")
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() and not member.isdir():
                raise RuntimeError("unexpected source archive member")
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or path.name == ".env":
                raise RuntimeError("unsafe source archive path")
        source = Path(tempfile.mkdtemp(prefix=SOURCE_SHA + "-", dir=SOURCE_ROOT))
        try:
            archive.extractall(source, filter="data")
        except Exception:
            shutil.rmtree(source)
            raise
    return source / "backend"


def require_maintenance():
    try:
        urllib.request.urlopen("http://127.0.0.1:" + os.environ.get("PORT", "8000") + "/health", timeout=5)
    except urllib.error.HTTPError as response:
        if response.code == 503 and response.read() == b"Flare maintenance: OPS-002\n":
            return
    raise RuntimeError("API must be in explicit OPS-002 maintenance")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "apply"), nargs="?", default="preflight")
    args = parser.parse_args()
    result = {"sourceSha": SOURCE_SHA, "action": args.action,
              "operatorScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "completed": False, "migrationAttempted": False}
    credential = native = ""
    backend = None
    try:
        result["phase"] = "verify_and_extract_exact_source"
        backend = exact_source()
        result["phase"] = "read_existing_migration_credential"
        credential, native = migration_credential()
        result["phase"] = "readonly_database_snapshot"
        result["before"] = snapshot(native)
        if result["before"]["heads"] not in (["0018"], ["0021"]):
            raise RuntimeError("unexpected migration head")
        child_env = {name: os.environ[name] for name in ("PATH", "PYTHONPATH", "LANG", "LC_ALL") if name in os.environ}
        # Role only: no credential is written. The explicit file prevents parent
        # dotenv discovery even with an older python-dotenv lacking the flag.
        role_file = backend.parent / "migration-role.env"
        role_file.write_text("FLARE_PROCESS_ROLE=migration\n", encoding="ascii")
        role_file.chmod(0o600)
        child_env.update(FLARE_PROCESS_ROLE="migration", FLARE_DATABASE_PROVIDER="self-managed",
                         MIGRATION_DATABASE_URL=credential, PYTHONDONTWRITEBYTECODE="1",
                         PYTHON_DOTENV_DISABLED="1", FLARE_DOTENV_PATH=str(role_file))
        result["phase"] = "verify_import_provenance"
        probe_code = "import json, os, app; from app.environment import load_project_dotenv; load_project_dotenv(allowed_roles={'migration'}); assert os.environ.get('MIGRATION_DATABASE_URL') and os.environ['FLARE_PROCESS_ROLE']=='migration'; from alembic.config import Config; from alembic.script import ScriptDirectory; print(json.dumps({'app':app.__file__,'heads':ScriptDirectory.from_config(Config('alembic.ini')).get_heads(),'migrationRoleVerified':True}))"
        probe = subprocess.run([sys.executable, "-c", probe_code],
                               cwd=backend, env=child_env, capture_output=True, timeout=20)
        if probe.returncode:
            raise RuntimeError("migration source probe failed")
        provenance = json.loads(probe.stdout)
        if Path(provenance["app"]).resolve() != backend / "app/__init__.py" or provenance["heads"] != ["0021"]:
            raise RuntimeError("migration imports stale application source")
        result["exactSourceImportVerified"] = True
        result["migrationGraphHeadVerified"] = True
        result["explicitMigrationRoleVerified"] = provenance["migrationRoleVerified"]
        if args.action == "apply":
            result["phase"] = "verify_maintenance_and_drain"
            require_maintenance()
            result["before"] = snapshot(native)
            if result["before"]["heads"] not in (["0018"], ["0021"]):
                raise RuntimeError("unexpected head immediately before migration")
            if any(result["before"][key] for key in ("activeAnalysisJobs", "activeFlareRuns", "activeRefreshes")):
                raise RuntimeError("background work must drain before migration")
            result["migrationAttempted"] = True
            for iteration in range(2):
                result["phase"] = "upgrade" if iteration == 0 else "repeat_upgrade"
                process = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                                         cwd=backend, env=child_env, capture_output=True, timeout=300)
                result["upgrade" if iteration == 0 else "repeatUpgrade"] = {"returnCode": process.returncode}
                result["after"] = snapshot(native)
                if process.returncode or result["after"]["heads"] != ["0021"]:
                    raise RuntimeError("migration failed; inspect sanitized head before recovery")
            if result["before"]["preservedTableCounts"] != result["after"]["preservedTableCounts"]:
                raise RuntimeError("existing row counts changed during migration")
            result["preservedCountsVerified"] = True
        result["phase"] = "complete"
        result["completed"] = True
    except Exception as exc:
        result.update(errorType=type(exc).__name__, sqlstate=getattr(exc, "sqlstate", None),
                      rawErrorOmitted=True)
        if native and result["migrationAttempted"]:
            try:
                result["afterFailure"] = snapshot(native)
            except Exception as followup:
                result["afterFailure"] = {"statusUnknown": True, "errorType": type(followup).__name__}
    finally:
        credential = native = ""
        if backend is not None:
            try:
                shutil.rmtree(backend.parent)
                result["temporarySourceRemoved"] = True
            except Exception as cleanup:
                result["temporarySourceRemoved"] = False
                result["cleanupErrorType"] = type(cleanup).__name__
        fd = os.open(RESULT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(result, output)
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
