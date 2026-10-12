"""Team capabilities run as the restricted API role, with server-owned actor context."""
from uuid import UUID
from psycopg.types.json import Jsonb
from app.models.database import Database


class TeamService:
    def __init__(self, database: Database, user_id: str):
        self.database, self.user_id = database, user_id

    def call(self, operation: str, *args):
        # Only these fixed statements are callable; client strings never form SQL.
        statements = {
            'projects': 'SELECT public.team_projects_list() AS result',
            'capability': 'SELECT public.team_capability() AS result',
            'create': 'SELECT public.team_project_create(%s,%s) AS result',
            'members': 'SELECT public.team_members_list(%s) AS result',
            'invite': 'SELECT public.team_invite(%s,%s,%s,%s) AS result',
            'invitations': 'SELECT public.team_invitations_list(%s) AS result',
            'cancel': 'SELECT public.team_invitation_cancel(%s,%s) AS result',
            'accept': 'SELECT public.team_invitation_accept(%s) AS result',
            'membership': 'SELECT public.team_membership_change(%s,%s,%s,%s) AS result',
            'tasks': 'SELECT public.team_tasks_list(%s,%s,%s) AS result',
            'task': 'SELECT public.team_task_write(%s,%s,%s,%s,%s) AS result',
            'history': 'SELECT public.team_task_history_list(%s,%s) AS result',
            'license': 'SELECT public.team_license_snapshots(%s) AS result',
        }
        with self.database.connection(timeout=3) as connection, connection.transaction():
            connection.execute("SET LOCAL statement_timeout='5s'")
            connection.execute("SET LOCAL lock_timeout='2s'")
            connection.execute("SELECT set_config('app.user_id',%s,true)", (self.user_id,))
            return connection.execute(statements[operation], args).fetchone()['result']

    def projects(self):
        return self.call('projects')

    def capability(self):
        return self.call('capability')

    def write_task(self, workspace_id: UUID, task_id: UUID, expected: int, payload: dict, remove=False):
        return self.call('task', workspace_id, task_id, expected, Jsonb(payload), remove)
