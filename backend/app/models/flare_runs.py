"""Stage 2 capabilities use only completed parent jobs and closed DB contexts."""
from uuid import UUID
from psycopg.types.json import Jsonb
from app.models.analysis_jobs import WorkerJobs


class FlareRuns(WorkerJobs):
    def enqueue(self, parent: UUID, revision: str, max_attempts: int = 3) -> UUID:
        return self._call('SELECT public.enqueue_flare_generation(%s,%s,%s) AS id',
                          (parent,revision,max_attempts))['id']

    def claim(self, owner: UUID, lease_seconds: int) -> dict | None:
        return self._call('SELECT * FROM public.claim_flare_generation(%s,%s)', (owner,lease_seconds))

    def load(self, claim: dict, max_sources: int, max_bytes: int) -> dict:
        return self._call('SELECT public.load_flare_generation(%s,%s,%s,%s) AS value',
                          (claim['id'],claim['lease_token'],max_sources,max_bytes))['value']

    def finish(self, claim: dict, *, flares=None, metadata=None, error=None, retry_seconds=None) -> str:
        return self._call('SELECT public.finish_flare_generation(%s,%s,%s,%s,%s,%s) AS value',
                          (claim['id'],claim['lease_token'],Jsonb(flares) if flares is not None else None,
                           Jsonb(metadata) if metadata is not None else None,error,retry_seconds))['value']
