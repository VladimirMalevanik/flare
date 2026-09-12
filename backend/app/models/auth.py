"""First-party credentials/session persistence; never return hashes to HTTP clients."""

from psycopg import Connection


class AuthRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def find_user(self, email: str, *, lock: bool = False):
        suffix = " FOR UPDATE" if lock else ""
        return self.connection.execute(
            f"SELECT * FROM public.auth_users WHERE email = %s{suffix}", (email,)
        ).fetchone()

    def insert_user(
        self,
        user_id: str,
        email: str,
        password_hash: str,
        name: str,
        workspace_id,
    ) -> None:
        self.connection.execute(
            "SELECT set_config('app.user_id', %s, true)", (user_id,)
        )
        self.connection.execute(
            "SELECT public.provision_workspace(%s, %s)",
            (workspace_id, f"{name}'s workspace"),
        )
        self.connection.execute(
            """INSERT INTO public.auth_users(id,email,password_hash,name,initial_workspace_id)
               VALUES (%s,%s,%s,%s,%s)""",
            (user_id, email, password_hash, name, workspace_id),
        )

    def insert_session(
        self, token_hash: str, user_id: str, workspace_id, lifetime: int
    ) -> None:
        self.connection.execute(
            """INSERT INTO public.auth_sessions(token_hash,user_id,workspace_id,expires_at)
               VALUES (%s,%s,%s,now() + %s * interval '1 second')""",
            (token_hash, user_id, workspace_id, lifetime),
        )

    def resolve_session(self, token_hash: str, idle_seconds: int):
        return self.connection.execute(
            """SELECT s.user_id, s.workspace_id, u.email, u.name,
                      u.email_verified_at IS NOT NULL AS email_verified
               FROM public.auth_sessions s
               JOIN public.auth_users u ON u.id=s.user_id
               WHERE s.token_hash=%s AND s.revoked_at IS NULL
                 AND s.expires_at > now() AND NOT u.disabled
                 AND s.last_seen_at > now() - %s * interval '1 second'""",
            (token_hash, idle_seconds),
        ).fetchone()

    def touch(self, token_hash: str) -> None:
        self.connection.execute(
            "UPDATE public.auth_sessions SET last_seen_at=now() "
            "WHERE token_hash=%s AND revoked_at IS NULL",
            (token_hash,),
        )

    def revoke(self, token_hash: str) -> None:
        self.connection.execute(
            "UPDATE public.auth_sessions SET revoked_at=now() "
            "WHERE token_hash=%s AND revoked_at IS NULL",
            (token_hash,),
        )

    def insert_email_verification(
        self, token_hash: str, user_id: str, email: str, ttl_seconds: int
    ) -> None:
        self.connection.execute(
            "DELETE FROM public.auth_email_verifications "
            "WHERE user_id=%s AND consumed_at IS NULL",
            (user_id,),
        )
        self.connection.execute(
            """INSERT INTO public.auth_email_verifications(
                   token_hash,user_id,email,expires_at
               ) VALUES (%s,%s,%s,now() + %s * interval '1 second')""",
            (token_hash, user_id, email, ttl_seconds),
        )

    def remove_email_verification(self, token_hash: str) -> None:
        self.connection.execute(
            "DELETE FROM public.auth_email_verifications "
            "WHERE token_hash=%s AND consumed_at IS NULL",
            (token_hash,),
        )

    def consume_and_verify_email(self, token_hash: str):
        return self.connection.execute(
            """WITH consumed AS (
                   UPDATE public.auth_email_verifications
                   SET consumed_at=now()
                   WHERE token_hash=%s
                     AND consumed_at IS NULL
                     AND expires_at > now()
                   RETURNING user_id, email
               )
               UPDATE public.auth_users AS users
               SET email_verified_at=COALESCE(users.email_verified_at, now())
               FROM consumed
               WHERE users.id=consumed.user_id
                 AND users.email=consumed.email
                 AND NOT users.disabled
               RETURNING users.id""",
            (token_hash,),
        ).fetchone()

    def mark_email_verified(self, user_id: str) -> None:
        self.connection.execute(
            "UPDATE public.auth_users SET email_verified_at=now() "
            "WHERE id=%s AND email_verified_at IS NULL",
            (user_id,),
        )

    def last_verification_created_at(self, user_id: str):
        row = self.connection.execute(
            "SELECT created_at FROM public.auth_email_verifications "
            "WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["created_at"] if row else None
