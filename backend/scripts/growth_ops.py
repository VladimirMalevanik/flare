"""Explicit policy activation, bounded maintenance and aggregate-only export.

Credentials come from operator-provided environment variables, never arguments,
dotenv files, output or artifacts. This tool does not provision access or schedules.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from app.services.funnel_service import aggregate_csv

NOTICE = "measurement-x-v1"
REVISION = "x-launch-2026-10-v1"
TOKENS = {
    "utm_source": ["x"], "utm_medium": ["organic_social"],
    "utm_campaign": ["launch_2026_10"],
    "utm_content": ["ilyas", "fedor", "flare"], "ref": ["ilyas", "fedor", "flare"],
    "referrer_domain": ["t.co", "x.com", "twitter.com"],
}
RETENTION = {
    "lookback_seconds": 604800, "cookie_seconds": 604800, "raw_seconds": 604800,
    "linked_seconds": 7776000, "fact_seconds": 7776000,
}
BOUNDS = {
    "global_hour": (1, 100000), "network_hour": (1, 100000),
    "reference_limit": (1, 100), "visitor_limit": (1, 1000000),
    "budget_limit": (2, 1000000), "deadline_ms": (10, 500),
    "report_window_days": (1, 30),
}


class OperatorError(Exception):
    """Safe error messages contain no connection or database details."""


def validate_policy(value):
    expected = {"revision", "notice_id", "eligibility", "cleanup_owner", "min_cohort", "report_calendar", "tokens", *RETENTION, *BOUNDS}
    if not isinstance(value, dict) or set(value) != expected:
        raise OperatorError("Policy fields do not match the reviewed notice.")
    fixed = {"revision": REVISION, "notice_id": NOTICE, "eligibility": "explicit-opt-in", "min_cohort": 5, "report_calendar": "UTC-v1"} | RETENTION
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in fixed.items()):
        raise OperatorError("Notice, revision, retention or disclosure settings do not match the reviewed UI.")
    if value["tokens"] != TOKENS:
        raise OperatorError("Only the three reviewed X link labels and referrer domains are allowed.")
    if not isinstance(value["cleanup_owner"], str) or not re.fullmatch(r"[A-Za-z0-9 /._-]{1,100}", value["cleanup_owner"]):
        raise OperatorError("An explicit cleanup owner is required.")
    for key, (low, high) in BOUNDS.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise OperatorError("A policy limit is outside its bounded range.")
    if value["network_hour"] > value["global_hour"]:
        raise OperatorError("Network limit cannot exceed the global limit.")
    return value


def read_policy(path):
    if path.stat().st_size > 8192:
        raise OperatorError("Policy file is too large.")
    def unique(pairs):
        result = {}
        for key, val in pairs:
            if key in result:
                raise OperatorError("Duplicate policy field.")
            result[key] = val
        return result
    return validate_policy(json.loads(path.read_text(), object_pairs_hook=unique))


def connect(name, *, readonly=False):
    dsn = os.getenv(name)
    if not dsn:
        raise OperatorError("Required operator connection is unavailable.")
    connection = psycopg.connect(dsn, connect_timeout=5, autocommit=True,
        options="-c statement_timeout=2000 -c lock_timeout=500 -c idle_in_transaction_session_timeout=5000")
    connection.read_only = readonly
    connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
    return connection


def restricted_role(connection, expected):
    row = connection.execute("""SELECT current_user,rolsuper,rolbypassrls,rolinherit,rolcreatedb,rolcreaterole,rolreplication
        FROM pg_roles WHERE rolname=current_user""").fetchone()
    if row != (expected, False, False, False, False, False, False):
        raise OperatorError("Use the designated restricted operator role.")
    if connection.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)").fetchone():
        raise OperatorError("The operator role must not inherit other roles.")
    if expected == "flare_growth_reporter":
        for table in ("auth_users", "signup_attribution", "funnel_facts", "acquisition_visitors", "growth_policy", "activity_events"):
            if connection.execute("SELECT has_any_column_privilege(current_user,%s,'SELECT')", ("public." + table,)).fetchone()[0]:
                raise OperatorError("Reporting access must expose aggregate functions only.")


def configure(connection, policy, *, expected_revision, approved_by, cleanup_ready):
    validate_policy(policy)
    if not cleanup_ready or approved_by != "Vova":
        raise OperatorError("Vova's activation approval and an installed cleanup schedule are required.")
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(2020,2)")
        current = connection.execute("SELECT revision,enabled FROM public.growth_policy WHERE singleton FOR UPDATE").fetchone()
        if current is None or current[0] != expected_revision or current[1]:
            raise OperatorError("Policy changed or is already enabled; re-check before activation.")
        keys = tuple(policy)
        statement = sql.SQL("UPDATE public.growth_policy SET enabled=true,{} WHERE singleton").format(
            sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(key)) for key in keys))
        connection.execute(statement, tuple(Jsonb(policy[k]) if isinstance(policy[k], dict) else policy[k] for k in keys))
    return {"enabled": True, "revision": policy["revision"], "approved_by": approved_by}


def maintenance(connection, kind, *, batch=100, max_batches=20):
    if kind not in ("cleanup", "reconcile") or type(batch) is not int or not 1 <= batch <= 1000 or type(max_batches) is not int or not 1 <= max_batches <= 100:
        raise OperatorError("Invalid bounded maintenance request.")
    restricted_role(connection, "flare_worker")
    total = 0
    for index in range(max_batches):
        with connection.transaction():
            result = connection.execute(sql.SQL("SELECT public.{}(%s)").format(sql.Identifier("growth_" + kind)), (batch,)).fetchone()[0]
        count = sum(result.values()) if isinstance(result, dict) else result
        if type(count) is not int or count < 0:
            raise OperatorError("Unexpected maintenance result.")
        total += count
        if kind == "reconcile" and count == 0:
            return {"kind": kind, "complete": True, "batches": index + 1, "processed": total, "completed_at": datetime.now(timezone.utc).isoformat(),
                "coverage": "zero new import facts in final batch; optional lock/contention loss remains unknown"}
    if kind == "cleanup":
        # The existing SQL return omits removed inspection-event counts. A zero
        # counter cannot prove expiry backlog exhaustion; schedule bounded passes.
        return {"kind": kind, "bounded_pass": True, "complete": None, "batches": max_batches, "processed": total,
            "completed_at": datetime.now(timezone.utc).isoformat(), "coverage": "bounded expiry pass; no backlog-exhaustion claim"}
    raise OperatorError("Maintenance batch budget exhausted; resume before exporting a report.")


def utc_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise OperatorError("Report times must include an explicit timezone.") from None


def report(connection, since, until, *, unit="account", basis="first"):
    if unit not in ("account", "workspace_creator") or basis not in ("first", "last") or not since < until <= datetime.now(timezone.utc) or until - since > timedelta(days=30):
        raise OperatorError("Use a past report window of at most 30 days.")
    restricted_role(connection, "flare_growth_reporter")
    with connection.transaction():
        return connection.execute("SELECT public.growth_report(%s,%s,%s,%s)", (since, until, unit, basis)).fetchone()[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("policy", type=Path)
    activate = commands.add_parser("activate")
    activate.add_argument("policy", type=Path)
    activate.add_argument("--expected-revision", required=True, help="none for an unconfigured policy")
    activate.add_argument("--approved-by", required=True)
    activate.add_argument("--cleanup-ready", action="store_true")
    maintain = commands.add_parser("maintain")
    maintain.add_argument("kind", choices=("cleanup", "reconcile"))
    maintain.add_argument("--batch", type=int, default=100)
    maintain.add_argument("--max-batches", type=int, default=20)
    export = commands.add_parser("report")
    export.add_argument("--since", required=True)
    export.add_argument("--until", required=True)
    export.add_argument("--unit", choices=("account", "workspace_creator"), default="account")
    export.add_argument("--basis", choices=("first", "last"), default="first")
    export.add_argument("--output", type=Path, required=True, help="New .csv or .json file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = {"enabled": False, "approval_required": True, "policy": read_policy(args.policy)}
        elif args.command == "activate":
            policy = read_policy(args.policy)
            with connect("GROWTH_ADMIN_DATABASE_URL") as connection:
                result = configure(connection, policy, expected_revision=None if args.expected_revision == "none" else args.expected_revision, approved_by=args.approved_by, cleanup_ready=args.cleanup_ready)
        elif args.command == "maintain":
            with connect("GROWTH_WORKER_DATABASE_URL") as connection:
                result = maintenance(connection, args.kind, batch=args.batch, max_batches=args.max_batches)
        else:
            since, until = utc_time(args.since), utc_time(args.until)
            if args.output.suffix not in (".csv", ".json") or args.output.exists():
                raise OperatorError("Choose a new CSV or JSON output file.")
            with connect("GROWTH_WORKER_DATABASE_URL") as connection:
                reconciled = maintenance(connection, "reconcile")
            with connect("GROWTH_REPORT_DATABASE_URL", readonly=True) as connection:
                value = report(connection, since, until, unit=args.unit, basis=args.basis)
            value["operator_reconciliation"] = reconciled
            payload = aggregate_csv(value) if args.output.suffix == ".csv" else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            # Restrict file permissions from creation; do not truncate an existing export.
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(payload)
            result = {"exported": True, "policy": value["policy"], "attribution_suppressed": value["attribution_suppressed"], "reconciliation": reconciled}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except OperatorError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print("Operation failed. No credentials or database error details are printed. Review the protected operator environment.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
