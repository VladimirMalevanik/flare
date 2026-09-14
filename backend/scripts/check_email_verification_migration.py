"""Prepare or verify the existing-user backfill applied by migration 0008."""

import argparse
import os
from uuid import UUID

import psycopg

USER_ID = "auth:00000000-0000-4000-8000-000000000008"
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000008")
EMAIL = "email-verification-migration@test.invalid"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TEST_DATABASE_URL is required")

    with psycopg.connect(database_url) as connection:
        if args.phase == "prepare":
            revision = connection.execute(
                "SELECT version_num FROM public.alembic_version"
            ).fetchone()
            assert revision == ("0007",), revision
            connection.execute(
                "INSERT INTO public.workspaces(id,name) VALUES (%s,%s)",
                (WORKSPACE_ID, "Email verification migration"),
            )
            connection.execute(
                """INSERT INTO public.auth_users(
                       id,email,password_hash,name,initial_workspace_id
                   ) VALUES (%s,%s,%s,%s,%s)""",
                (USER_ID, EMAIL, "migration-test-hash", "Migration", WORKSPACE_ID),
            )
            return

        revision = connection.execute(
            "SELECT version_num FROM public.alembic_version"
        ).fetchone()
        # CI upgrades through the current repository head after preparing the
        # pre-0008 fixture. Keep this assertion aligned with the linear chain so
        # the check also detects a stale or branched migration result.
        assert revision == ("0015",), revision
        verified = connection.execute(
            "SELECT email_verified_at IS NOT NULL FROM public.auth_users WHERE id=%s",
            (USER_ID,),
        ).fetchone()
        assert verified == (True,), verified
        connection.execute("DELETE FROM public.auth_users WHERE id=%s", (USER_ID,))
        connection.execute(
            "DELETE FROM public.workspaces WHERE id=%s", (WORKSPACE_ID,)
        )
        print("PASS: 0007 -> 0015; 0008 existing-user backfill preserved")


if __name__ == "__main__":
    main()
