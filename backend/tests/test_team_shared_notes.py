"""Team means one shared context and scheduled Flare feed, not per-user AI runs."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from app.ai_engine.analysis import AnalysisResult, AnalysisMetadata, TextAnalysis
from app.ai_engine.flares import FlareResult, FlareCandidates
from app.ai_engine.flare_config import FlareSettings
from app.ai_engine.text_analysis_prompts import PROMPT_VERSION, SCHEMA_VERSION
from app.config import AISettings
from app.models.analysis_jobs import WorkerJobs
from app.models.analysis_schedules import WorkerAnalysisSchedules
from app.models.flare_runs import FlareRuns
from app.services.analysis_jobs import AnalysisProcessor
from app.services.flare_generation import FlareProcessor
from app.workers.config import WorkerSettings, pipeline_revision
from test_team import team
from test_flare_runs import metadata as flare_metadata

pytestmark = pytest.mark.integration
GOAL = 'Our goal is to ship the core analysis flow this week.'
STATE = 'The core analysis flow is unfinished and evidence display is missing.'


def test_shared_notes_keep_creator_after_colleague_edit_and_reject_spoofing(team):
    owner, c = team.account(); member, m = team.account(); viewer, v = team.account()
    wid = team.create(owner, c)
    for user, client, role in [(member, m, 'editor'), (viewer, v, 'viewer')]:
        token, _ = team.invite(c, wid, user, role); assert team.accept(client, token).status_code == 200
    r = m.post('/items', params={'workspace': wid}, json={'type': 'note', 'content': STATE})
    assert r.status_code == 201, r.text
    note = r.json(); assert (note['createdBy'], note['author']) == (member.user_id, member.name)
    assert c.get('/items', params={'workspace': wid}).json() == [note]
    assert v.get('/items', params={'workspace': wid}).json() == [note]
    assert m.get('/items').json() == []
    assert m.post('/items', params={'workspace': wid}, json={'type': 'note', 'content': STATE, 'author': owner.name}).status_code == 422
    assert v.post('/items', params={'workspace': wid}, json={'type': 'note', 'content': 'No write'}).status_code == 403
    changed = c.patch('/items/' + note['id'], params={'workspace': wid}, json={
        'expectedCurrentVersionId': note['currentVersionId'], 'content': STATE + ' We are reviewing it.'})
    assert changed.status_code == 200, changed.text
    assert (changed.json()['createdBy'], changed.json()['author']) == (member.user_id, member.name)
    assert m.patch('/items/' + note['id'], params={'workspace': wid}, json={
        'expectedCurrentVersionId': note['currentVersionId'], 'content': 'Stale overwrite'}).status_code == 409


def test_text_import_records_authenticated_creator_and_dedupe_keeps_original_author(team):
    owner, c = team.account(); member, m = team.account(); wid = team.create(owner, c)
    token, _ = team.invite(c, wid, member); assert team.accept(m, token).status_code == 200
    body = {'format': 'txt', 'fileName': 'interview.txt', 'fileSize': len(STATE.encode()), 'content': STATE}
    first = m.post('/imports', params={'workspace': wid}, json=body)
    assert first.status_code == 201, first.text
    second = c.post('/imports', params={'workspace': wid}, json=body)
    assert second.status_code == 200, second.text
    assert second.json()['item']['id'] == first.json()['item']['id']
    assert (second.json()['item']['createdBy'], second.json()['item']['author']) == (member.user_id, member.name)


class SharedAnalyzer:
    def __init__(self): self.seen = []
    async def analyze(self, evidence):
        self.seen.append(evidence)
        return AnalysisResult(TextAnalysis.model_validate({'observations': [
            {'category': 'fact', 'text': e.content, 'evidence': [{'source_id': e.source_id, 'quote': e.content}]}
            for e in evidence
        ]}), AnalysisMetadata(configured_model=AISettings().model, returned_model=AISettings().model,
            prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION, validation_outcome='valid', finish_reason='stop'))


class SharedDetector:
    def __init__(self): self.seen = []
    async def detect(self, analysis, evidence):
        self.seen.append(evidence)
        by_content = {e.content: e for e in evidence}
        return FlareResult(FlareCandidates(flares=[{
            'type': 'Recommendation', 'title': 'Finish the core analysis flow',
            'statement': 'The core analysis flow is unfinished ahead of the release target.',
            'action': 'Finish the core analysis flow and evidence display before release.',
            'reason': 'The shared goal is to release this week while the core analysis flow is unfinished.',
            'evidence': [{'source_id': by_content[GOAL].source_id, 'quote': GOAL, 'supports': ['goal']},
                         {'source_id': by_content[STATE].source_id, 'quote': STATE, 'supports': ['state']}],
        }]), flare_metadata())


def test_scheduled_flare_combines_two_members_notes_is_shared_and_uses_one_project_quota(team):
    owner, c = team.account(); member, m = team.account(); viewer, v = team.account(); outsider, o = team.account()
    wid = team.create(owner, c)
    for user, client, role in [(member, m, 'editor'), (viewer, v, 'viewer')]:
        token, _ = team.invite(c, wid, user, role); assert team.accept(client, token).status_code == 200
    private = m.post('/items', json={'type': 'note', 'content': 'Private customer note. Never shared.'}).json()
    owner_note = c.post('/items', params={'workspace': wid}, json={'type': 'note', 'content': GOAL}).json()
    member_note = m.post('/items', params={'workspace': wid}, json={'type': 'note', 'content': STATE}).json()
    target = (datetime.now(timezone.utc) + timedelta(minutes=32)).replace(second=0, microsecond=0)
    schedule = c.put('/analysis-schedule', params={'workspace': wid}, json={'enabled': True, 'timezone': 'UTC', 'localTime': target.strftime('%H:%M')})
    assert schedule.status_code == 200, schedule.text
    assert m.get('/analysis-schedule', params={'workspace': wid}).json() == schedule.json()
    worker = WorkerAnalysisSchedules(os.environ['WORKER_DATABASE_URL'])
    refresh_at = datetime.fromisoformat(schedule.json()['nextRefreshAt']) + timedelta(seconds=1)
    assert worker.materialize(refresh_at) == 1
    assert worker.materialize(refresh_at) == 0
    cycle = team.query('SELECT id FROM analysis_cycles WHERE workspace_id=%s', UUID(wid))[0][0]
    team.query("UPDATE analysis_cycles SET refresh_due_at=clock_timestamp()-interval '1 second' WHERE id=%s", cycle)
    claim = worker.claim_refresh(uuid4(), 120); assert claim and claim.cycle_id == cycle
    loaded = worker.candidates(claim, 100, 100000)
    assert {r['content'] for r in loaded['candidates']} == {GOAL, STATE}, loaded
    chunks = tuple(UUID(r['id']) for r in loaded['candidates'])
    assert worker.finish_refresh(claim, chunks=chunks) == 'ready'
    enqueue_at = team.query('UPDATE analysis_cycles SET scheduled_for=clock_timestamp() WHERE id=%s RETURNING scheduled_for', cycle)[0][0]
    ai, flare, settings = AISettings(), FlareSettings(), WorkerSettings()
    args = dict(pipeline_revision=pipeline_revision(ai), generation_revision=flare.revision(ai), max_attempts=3, now=enqueue_at + timedelta(seconds=1))
    assert worker.enqueue_due(**args)[0]['status'] == 'queued'
    assert not any(row['status'] == 'queued' for row in worker.enqueue_due(**args))
    analyzer, detector = SharedAnalyzer(), SharedDetector()
    assert asyncio.run(AnalysisProcessor(WorkerJobs(os.environ['WORKER_DATABASE_URL']), analyzer, ai, settings).process_one()) == 'completed'
    assert asyncio.run(FlareProcessor(FlareRuns(os.environ['WORKER_DATABASE_URL']), detector, ai, flare, settings).process_one()) == 'completed'
    assert len(analyzer.seen) == len(detector.seen) == 1
    assert {e.content for e in detector.seen[0]} == {GOAL, STATE}
    flares = c.get('/flares', params={'workspace': wid}); assert flares.status_code == 200
    assert len(flares.json()) == 1, flares.text
    assert m.get('/flares', params={'workspace': wid}).json() == flares.json()
    assert v.get('/flares', params={'workspace': wid}).json() == flares.json()
    assert {e['itemId'] for e in flares.json()[0]['evidence']} == {owner_note['id'], member_note['id']}
    assert private['id'] not in {e['itemId'] for e in flares.json()[0]['evidence']}
    assert m.get('/flares').json() == []
    assert o.get('/flares', params={'workspace': wid}).status_code == 404
    assert team.query('SELECT count(*) FROM analysis_daily_quotas WHERE workspace_id=%s', UUID(wid))[0][0] == 1
    assert team.query('SELECT count(*) FROM analysis_jobs WHERE workspace_id=%s', UUID(wid))[0][0] == 1
    for client in [c, m, v]:
        status = client.get('/analysis/daily-status', params={'workspace': wid}).json()
        assert status['state'] == 'completed' and status['canRequestToday'] is False
        assert client.post('/analyze', params={'workspace': wid}, headers={'Idempotency-Key': str(uuid4())}, json={}).status_code == 410
