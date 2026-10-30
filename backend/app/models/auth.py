"""First-party credentials/session persistence; never return hashes to HTTP clients."""

from psycopg import Connection

from app.legal import (
    CURRENT_PRIVACY_CONTENT_ID,
    CURRENT_PRIVACY_VERSION,
    CURRENT_TERMS_CONTENT_ID,
    CURRENT_TERMS_VERSION,
)


class AuthRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def find_user(self, email: str, *, lock: bool = False):
        suffix = " FOR UPDATE" if lock else ""
        return self.connection.execute(
            f"SELECT * FROM public.auth_users WHERE email = %s{suffix}", (email,)
        ).fetchone()

    def reset_target(self, token_hash: str):
        return self.connection.execute(
            """SELECT u.email FROM public.auth_password_resets r
               JOIN public.auth_users u ON u.id=r.user_id AND u.email=r.email
               WHERE r.token_hash=%s AND r.expires_at>clock_timestamp() AND NOT u.disabled""",
            (token_hash,),
        ).fetchone()

    def insert_password_reset(self, token_hash: str, user) -> bool:
        # Caller holds the user lock. Preserve already delivered valid links and
        # cap both stored state and inbox traffic, including after SMTP failure.
        self.connection.execute(
            """DELETE FROM public.auth_password_resets WHERE user_id=%s AND (
               expires_at<=clock_timestamp() OR
               (sent_at IS NULL AND created_at<=clock_timestamp()-interval '60 seconds'))""",
            (user["id"],),
        )
        admitted = self.connection.execute(
            """UPDATE public.auth_users SET password_reset_requested_at=clock_timestamp()
               WHERE id=%s AND (password_reset_requested_at IS NULL OR
                   password_reset_requested_at<=clock_timestamp()-interval '60 seconds')
                 AND (SELECT count(*) FROM public.auth_password_resets WHERE user_id=%s)<5
               RETURNING id""", (user["id"], user["id"]),
        ).fetchone()
        if admitted is None:
            return False
        self.connection.execute(
            """INSERT INTO public.auth_password_resets(token_hash,user_id,email,expires_at)
               VALUES(%s,%s,%s,clock_timestamp()+interval '30 minutes')""",
            (token_hash, user["id"], user["email"]),
        )
        return True

    def change_password(self, token_hash: str, user, password_hash: str) -> bool:
        # User-before-token lock order matches requests and session creation.
        token = self.connection.execute(
            """SELECT token_hash FROM public.auth_password_resets
               WHERE token_hash=%s AND user_id=%s AND email=%s FOR UPDATE""",
            (token_hash, user["id"], user["email"]),
        ).fetchone()
        if token is None:
            return False
        # Check wall-clock expiry after acquiring both locks, including if a
        # transaction waited past the deadline for the token row itself.
        updated = self.connection.execute(
            """UPDATE public.auth_users SET password_hash=%s WHERE id=%s AND EXISTS(
               SELECT 1 FROM public.auth_password_resets WHERE token_hash=%s
                 AND expires_at>clock_timestamp()) RETURNING id""",
            (password_hash, user["id"], token_hash),
        ).fetchone()
        if updated is None:
            return False
        self.connection.execute(
            "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE user_id=%s AND revoked_at IS NULL",
            (user["id"],),
        )
        self.connection.execute("DELETE FROM public.auth_password_resets WHERE user_id=%s", (user["id"],))
        return True

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
            """INSERT INTO public.auth_users(id,email,password_hash,name,initial_workspace_id,verification_provenance)
               VALUES (%s,%s,%s,%s,%s,'pending')""",
            (user_id, email, password_hash, name, workspace_id),
        )
        self.accept_current_legal(user_id)

    def accept_current_legal(self, user_id: str) -> None:
        self.connection.execute(
            """INSERT INTO public.auth_legal_acceptances(
                   user_id,terms_version,privacy_version,
                   terms_content_id,privacy_content_id
               ) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING""",
            (
                user_id,
                CURRENT_TERMS_VERSION,
                CURRENT_PRIVACY_VERSION,
                CURRENT_TERMS_CONTENT_ID,
                CURRENT_PRIVACY_CONTENT_ID,
            ),
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
                      u.email_verified_at IS NOT NULL AS email_verified,
                      EXISTS (
                          SELECT 1
                          FROM public.auth_legal_acceptances legal
                          WHERE legal.user_id=u.id
                            AND legal.terms_version=%s
                            AND legal.privacy_version=%s
                            AND legal.terms_content_id=%s
                            AND legal.privacy_content_id=%s
                      ) AS legal_accepted
               FROM public.auth_sessions s
               JOIN public.auth_users u ON u.id=s.user_id
               WHERE s.token_hash=%s AND s.revoked_at IS NULL
                 AND s.expires_at > now() AND NOT u.disabled
                 AND s.last_seen_at > now() - %s * interval '1 second'""",
            (
                CURRENT_TERMS_VERSION,
                CURRENT_PRIVACY_VERSION,
                CURRENT_TERMS_CONTENT_ID,
                CURRENT_PRIVACY_CONTENT_ID,
                token_hash,
                idle_seconds,
            ),
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
               SET email_verified_at=COALESCE(users.email_verified_at, now()), verification_provenance='actual'
               FROM consumed
               WHERE users.id=consumed.user_id
                 AND users.email=consumed.email
                 AND NOT users.disabled
               RETURNING users.id""",
            (token_hash,),
        ).fetchone()

    def mark_email_verified(self, user_id: str) -> None:
        self.connection.execute(
            "UPDATE public.auth_users SET email_verified_at=now(), verification_provenance='bypassed' "
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
