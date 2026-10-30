"""Disposable CI probe: preserve credentials/sessions across 0026 -> current head."""
import argparse
from hashlib import sha256
import os
from uuid import UUID

import psycopg

from app.models.database import CURRENT_SCHEMA_REVISION

USER = "auth:00000000-0000-4000-8000-000000000027"
WORKSPACE = UUID("00000000-0000-4000-8000-000000000027")
EMAIL = "recovery-migration@test.invalid"
SESSION = sha256(b"disposable-migration-session").hexdigest()
VERIFICATION = sha256(b"disposable-migration-verification").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "verify"])
    phase = parser.parse_args().phase
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as c:
        revision = c.execute("SELECT version_num FROM public.alembic_version").fetchone()
        if phase == "prepare":
            assert revision == ("0026",), revision
            c.execute("INSERT INTO public.workspaces(id,name) VALUES(%s,'Recovery migration probe')", (WORKSPACE,))
            c.execute("""INSERT INTO public.auth_users(id,email,password_hash,name,initial_workspace_id,verification_provenance)
                VALUES(%s,%s,'preserved-migration-hash','Recovery migration',%s,'pending')""", (USER, EMAIL, WORKSPACE))
            c.execute("""INSERT INTO public.auth_sessions(token_hash,user_id,workspace_id,expires_at)
                VALUES(%s,%s,%s,'2099-01-01T00:00:00Z')""", (SESSION, USER, WORKSPACE))
            c.execute("""INSERT INTO public.auth_email_verifications(token_hash,user_id,email,expires_at)
                VALUES(%s,%s,%s,'2099-01-01T00:00:00Z')""", (VERIFICATION, USER, EMAIL))
            return
        assert revision == (CURRENT_SCHEMA_REVISION,), revision
        assert c.execute("""SELECT password_hash,disabled,email_verified_at,verification_provenance,password_reset_requested_at
            FROM public.auth_users WHERE id=%s""", (USER,)).fetchone() == ('preserved-migration-hash', False, None, 'pending', None)
        assert c.execute("""SELECT revoked_at,expires_at='2099-01-01T00:00:00Z'::timestamptz
            FROM public.auth_sessions WHERE token_hash=%s""", (SESSION,)).fetchone() == (None, True)
        assert c.execute("SELECT consumed_at FROM public.auth_email_verifications WHERE token_hash=%s", (VERIFICATION,)).fetchone() == (None,)
        assert c.execute("SELECT count(*) FROM public.auth_password_resets WHERE user_id=%s", (USER,)).fetchone() == (0,)
        c.execute("DELETE FROM public.auth_users WHERE id=%s", (USER,))
        c.execute("DELETE FROM public.workspaces WHERE id=%s", (WORKSPACE,))
    print(f"PASS: 0026 -> {CURRENT_SCHEMA_REVISION}; password, sessions and pending verification preserved")


if __name__ == "__main__":
    main()
