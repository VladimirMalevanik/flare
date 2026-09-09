"""Read persisted workspace Flares; generation is a separate worker capability."""
from uuid import UUID
from app.models.database import Database, WorkspaceIdentity
from app.models.flares import FlareRepository


class FlareNotFound(Exception): pass


class FlareService:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self.database,self.identity=database,identity

    def list(self, limit: int):
        with self.database.workspace_transaction(self.identity) as conn:
            return FlareRepository(conn).list(limit)

    def get(self, flare_id: UUID):
        with self.database.workspace_transaction(self.identity) as conn:
            row=FlareRepository(conn).get(flare_id)
            if row is None: raise FlareNotFound
            return row
