"""Staging security and 0021 -> head preservation checks in disposable CI.

Optionally run ``prepare --snapshot /tmp/staging-upgrade.json`` at 0021, upgrade
to head, then run ``verify --snapshot /tmp/staging-upgrade.json``. The snapshot
contains schema metadata and row digests, never source content or credentials.
Corruption probes use temporary grants/DDL inside rolled-back savepoints. Do not
run this fixture checker against a live customer database.
"""

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.database import (
    CURRENT_SCHEMA_REVISION,
    IMPORT_STAGING_FUNCTIONS,
    IMPORT_STAGING_TABLES,
    _connection_is_ready,
    database_is_ready,
)


ORIGINAL_TABLES = (
    "documents", "document_versions", "chunks", "import_packages",
    "import_package_entries", "import_objects", "import_publications",
    "analysis_jobs", "analysis_runs", "flare_generation_runs",
    "analysis_daily_quotas",
)
ORIGINAL_FUNCTIONS = (
    "public.import_api(text,uuid,jsonb)",
    "public.claim_import_package(integer)",
    "public.import_worker_step(uuid,uuid,bigint,text,jsonb)",
    "public.import_cleanup(text,uuid,text)",
)


def preservation_snapshot(connection, columns=None):
    """Bound fixture work and compare original columns, including additive upgrades."""
    result = {"tables": {}, "functions": {}, "gates": {}}
    for table in ORIGINAL_TABLES:
        count = connection.execute(
            sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
        ).fetchone()[0]
        if count > 10_000:
            raise RuntimeError("Fixture checker permits at most 10,000 rows per original table")
        names = columns[table] if columns else [row[0] for row in connection.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass "
            "AND attnum>0 AND NOT attisdropped ORDER BY attnum", ("public." + table,)
        ).fetchall()]
        digest = connection.execute(
            sql.SQL("""SELECT md5(coalesce(string_agg(row_digest, '' ORDER BY row_digest),''))
                FROM (SELECT md5((SELECT jsonb_object_agg(key,value)
                         FROM jsonb_each(to_jsonb(t)) WHERE key=ANY(%s))::text) row_digest
                      FROM public.{} t) rows""").format(sql.Identifier(table)),
            (names,),
        ).fetchone()[0]
        result["tables"][table] = {"columns": names, "count": count, "digest": digest}
    for signature in ORIGINAL_FUNCTIONS:
        result["functions"][signature] = connection.execute(
            "SELECT pg_get_functiondef(%s::regprocedure)", (signature,)
        ).fetchone()[0]
    for table in ("documents", "document_versions", "chunks"):
        result["gates"][table] = connection.execute(
            "SELECT permissive,roles,cmd,qual,with_check FROM pg_policies "
            "WHERE schemaname='public' AND tablename=%s AND policyname='import_gate'", (table,)
        ).fetchone()
    return result


def verify(connection):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == [CURRENT_SCHEMA_REVISION]
    assert connection.execute("SELECT version_num FROM public.alembic_version").fetchone() == (CURRENT_SCHEMA_REVISION,)
    assert database_is_ready(os.environ["DATABASE_URL"])

    for table in IMPORT_STAGING_TABLES:
        assert connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
            ("public." + table,),
        ).fetchone() == (True, True)
        for role in ("public", "flare_app", "flare_worker"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),"
                "has_any_column_privilege(%s,%s,'SELECT,INSERT,UPDATE,REFERENCES')",
                (role, "public." + table, role, "public." + table),
            ).fetchone() == (False, False)

    for signature, callers in IMPORT_STAGING_FUNCTIONS.items():
        signature = "public." + signature
        for role in ("public", "flare_app", "flare_worker"):
            allowed = role in callers
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (allowed,), (signature, role)

    # Readiness must fail closed even for a column-only grant on private bytes.
    # All intentional corruption is inside savepoints and rolled back together.
    with connection.transaction(force_rollback=True):
        connection.execute("GRANT SELECT(key) ON public.import_staging_blocks TO flare_app")
        connection.execute("SET LOCAL ROLE flare_app")
        assert _connection_is_ready(connection) is False
    with connection.transaction(force_rollback=True):
        connection.execute("ALTER TABLE public.import_staging_blocks NO FORCE ROW LEVEL SECURITY")
        connection.execute("SET LOCAL ROLE flare_app")
        assert _connection_is_ready(connection) is False
    with connection.transaction(force_rollback=True):
        connection.execute("GRANT EXECUTE ON FUNCTION public.import_staging_read(text,uuid,uuid,bigint,integer) TO flare_app")
        connection.execute("SET LOCAL ROLE flare_app")
        assert _connection_is_ready(connection) is False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"), nargs="?", default="verify")
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if args.phase == "prepare" and args.snapshot is None:
        parser.error("prepare requires --snapshot")
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        if args.phase == "prepare":
            assert connection.execute("SELECT version_num FROM public.alembic_version").fetchone() == ("0021",)
            snapshot = preservation_snapshot(connection)
            descriptor = os.open(args.snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as target:
                json.dump(snapshot, target, sort_keys=True)
            print("PASS: bounded schema21 preservation snapshot; no content or credentials")
        else:
            verify(connection)
            if args.snapshot:
                baseline = json.loads(args.snapshot.read_text())
                columns = {table: data["columns"] for table, data in baseline["tables"].items()}
                actual = preservation_snapshot(connection, columns)
                # Normalize PostgreSQL tuples to the JSON list representation.
                assert json.loads(json.dumps(actual)) == baseline
            print(f"PASS: head {CURRENT_SCHEMA_REVISION}; private staging capabilities, forced RLS, fail-closed readiness"
                  + ("; original ZIP gate/dedupe/provenance/Analyze rows preserved" if args.snapshot else ""))
        connection.rollback()


if __name__ == "__main__":
    main()
