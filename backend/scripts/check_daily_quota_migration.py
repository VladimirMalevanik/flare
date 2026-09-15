"""Prepare or verify the legacy-run quota backfill applied by migration 0015."""

import argparse
from datetime import datetime
import os
from uuid import UUID

import psycopg


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000015")
USER_ID = "auth:00000000-0000-4000-8000-000000000015"
JOB_IDS = (
    UUID("10000000-0000-4000-8000-000000000015"),
    UUID("20000000-0000-4000-8000-000000000015"),
    UUID("30000000-0000-4000-8000-000000000015"),
)
RUN_IDS = (
    UUID("40000000-0000-4000-8000-000000000015"),
    UUID("50000000-0000-4000-8000-000000000015"),
    UUID("60000000-0000-4000-8000-000000000015"),
)
CREATED_AT = (
    "2026-08-01 08:00:00+00",
    "2026-08-01 21:00:00+00",
    "2026-08-02 02:00:00+00",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TEST_DATABASE_URL is required")

    with psycopg.connect(database_url) as connection:
        revision = connection.execute(
            "SELECT version_num FROM public.alembic_version"
        ).fetchone()
        if args.phase == "prepare":
            assert revision == ("0014",), revision
            connection.execute(
                "INSERT INTO public.workspaces(id,name) VALUES (%s,%s)",
                (WORKSPACE_ID, "Daily quota migration"),
            )
            connection.execute(
                """INSERT INTO public.auth_users(
                       id,email,password_hash,name,initial_workspace_id,email_verified_at
                   ) VALUES (%s,%s,%s,%s,%s,clock_timestamp())""",
                (
                    USER_ID,
                    "daily-quota-migration@test.invalid",
                    "migration-test-hash",
                    "Migration",
                    WORKSPACE_ID,
                ),
            )
            for ordinal, (job_id, run_id, created_at) in enumerate(
                zip(JOB_IDS, RUN_IDS, CREATED_AT)
            ):
                connection.execute(
                    """INSERT INTO public.analysis_jobs(
                           id,workspace_id,requested_by_user_id,pipeline_revision,
                           dedupe_key,max_attempts,created_at,updated_at
                       ) VALUES (%s,%s,%s,'migration-v1',%s,3,%s,%s)""",
                    (
                        job_id,
                        WORKSPACE_ID,
                        USER_ID,
                        str(ordinal + 1) * 64,
                        created_at,
                        created_at,
                    ),
                )
                connection.execute(
                    """INSERT INTO public.analysis_runs(
                           id,workspace_id,requested_by_user_id,idempotency_key,
                           analysis_job_id,selection_revision,pipeline_revision,
                           generation_revision,selected_chunk_count,created_at
                       ) VALUES (%s,%s,%s,%s,%s,'migration-selection-v1',
                                 'migration-v1','migration-generation-v1',1,%s)""",
                    (run_id, WORKSPACE_ID, USER_ID, run_id, job_id, created_at),
                )
            return

        assert revision == ("0017",), revision
        quotas = connection.execute(
            """SELECT q.local_date::text,q.mode,q.scheduled_for,q.created_at
                 FROM public.analysis_daily_quotas q
                WHERE q.workspace_id=%s
                ORDER BY q.local_date""",
            (WORKSPACE_ID,),
        ).fetchall()
        expected = [
            (
                "2026-08-01",
                "manual",
                datetime.fromisoformat(CREATED_AT[1]),
                datetime.fromisoformat(CREATED_AT[1]),
            ),
            (
                "2026-08-02",
                "manual",
                datetime.fromisoformat(CREATED_AT[2]),
                datetime.fromisoformat(CREATED_AT[2]),
            ),
        ]
        assert quotas == expected, quotas
        connection.execute(
            "DELETE FROM public.analysis_jobs WHERE workspace_id=%s", (WORKSPACE_ID,)
        )
        connection.execute("DELETE FROM public.auth_users WHERE id=%s", (USER_ID,))
        connection.execute(
            "DELETE FROM public.workspaces WHERE id=%s", (WORKSPACE_ID,)
        )
        print("PASS: 0014 -> 0017; legacy analysis run consumed its UTC daily slot")


if __name__ == "__main__":
    main()
