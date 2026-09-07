"""First-party credentials/session persistence; never return hashes to HTTP clients."""
from psycopg import Connection


class AuthRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def find_user(self, email: str):
        return self.connection.execute(
            "SELECT * FROM public.auth_users WHERE email = %s", (email,)
        ).fetchone()

    def insert_user(self, user_id: str, email: str, password_hash: str, name: str, workspace_id):
        self.connection.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
        self.connection.execute("SELECT public.provision_workspace(%s, %s)", (workspace_id, f"{name}'s workspace"))
        self.connection.execute(
            """INSERT INTO public.auth_users(id,email,password_hash,name,initial_workspace_id)
               VALUES (%s,%s,%s,%s,%s)""",
            (user_id, email, password_hash, name, workspace_id),
        )

    def insert_session(self, token_hash: str, user_id: str, workspace_id, lifetime: int):
        self.connection.execute(
            """INSERT INTO public.auth_sessions(token_hash,user_id,workspace_id,expires_at)
               VALUES (%s,%s,%s,now() + %s * interval '1 second')""",
            (token_hash, user_id, workspace_id, lifetime),
        )

    def resolve_session(self, token_hash: str, idle_seconds: int):
        return self.connection.execute(
            """SELECT s.user_id, s.workspace_id, u.email, u.name
               FROM public.auth_sessions s JOIN public.auth_users u ON u.id=s.user_id
               WHERE s.token_hash=%s AND s.revoked_at IS NULL
                 AND s.expires_at > now() AND NOT u.disabled
                 AND s.last_seen_at > now() - %s * interval '1 second'""",
            (token_hash, idle_seconds),
        ).fetchone()

    def touch(self, token_hash: str):
        self.connection.execute(
            "UPDATE public.auth_sessions SET last_seen_at=now() WHERE token_hash=%s AND revoked_at IS NULL",
            (token_hash,),
        )

    def revoke(self, token_hash: str):
        self.connection.execute(
            "UPDATE public.auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL",
            (token_hash,),
        )
