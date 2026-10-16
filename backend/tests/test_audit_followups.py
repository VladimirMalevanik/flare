"""Approved audit follow-ups on isolated PostgreSQL; no live AI or mail."""
from uuid import UUID, uuid4

import pytest

from app.models.database import WorkspaceIdentity, WritePermissionRequiredError
from app.models.tables import ItemRepository
from app.services.import_service import ChunkSpec
from app.services.item_service import ItemService
from test_items_api import api_environment  # noqa: F401
from test_flare_runs import stage, jobs, admin_url, processor, Detector  # noqa: F401
from test_flares_api import client_for


def legacy_note(client, monkeypatch, text):
    with monkeypatch.context() as patch:
        patch.setattr(ItemService, '_capture_chunks', staticmethod(
            lambda kind, content, locator: (ChunkSpec(content=content, locator=locator),)))
        response = client.post('/items', json={'type': 'note', 'title': 'Original title', 'content': text})
    assert response.status_code == 201
    return response.json()


def identity_for(environment):
    return WorkspaceIdentity(next(iter(environment.workspace_ids)), next(iter(environment.user_ids)))


def test_exact_version_read_is_private_published_and_preserves_original_metadata(api_environment):
    with api_environment.client() as client:
        old = client.post('/items', json={'type':'note','title':'Original title','content':'Original release decision.'}).json()
        new = client.patch('/items/'+old['id'], json={'expectedCurrentVersionId':old['currentVersionId'],
            'title':'Edited title','content':'Changed release decision.'}).json()
        path = f"/items/{old['id']}/versions/{old['currentVersionId']}"
        response = client.get(path)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        snapshot = response.json()
        assert snapshot['item']['content'] == old['content']
        assert snapshot['item']['title'] == old['title']
        assert snapshot['item']['createdBy'] == old['createdBy']
        assert snapshot['item']['versionNumber'] == 1
        assert snapshot['isCurrent'] is False and snapshot['savedAt']
        assert client.get(f"/items/{old['id']}/versions/{new['currentVersionId']}").json()['isCurrent'] is True
        wrong = client.get(f"/items/{old['id']}/versions/{uuid4()}")
        assert wrong.status_code == 404
        processing_id = uuid4()
        api_environment.execute_admin('''INSERT INTO document_versions(id,workspace_id,document_id,
            version_number,content_hash,parser_version,snapshot_title,snapshot_source_url,snapshot_metadata,state)
            SELECT %s,workspace_id,document_id,3,content_hash,parser_version,snapshot_title,
                   snapshot_source_url,snapshot_metadata,'processing' FROM document_versions WHERE id=%s''',
            (processing_id,old['currentVersionId']))
        assert client.get(f"/items/{old['id']}/versions/{processing_id}").status_code == 404
        with api_environment.client() as outsider:
            denied = outsider.get(path)
            assert denied.status_code == 404 and denied.json() == wrong.json()
        assert client.post(path, json={}).status_code == 405
        assert client.patch(path, json={'content':'Overwrite history'}).status_code == 405
        assert client.delete('/items/'+old['id']).status_code == 204
        assert client.get(path).status_code == 404


def test_flare_evidence_identifies_the_immutable_version_after_edit(stage, jobs):
    import asyncio
    assert asyncio.run(processor(stage, Detector()).process_one()) == 'completed'
    with client_for(jobs) as client:
        flare = client.get('/flares').json()[0]
        evidence = flare['evidence'][0]
        assert evidence['documentVersionId'] and evidence['versionNumber'] >= 1 and evidence['versionCreatedAt']
        item = client.get('/items/'+evidence['itemId']).json()
        assert item['currentVersionId'] == evidence['documentVersionId']
        changed = client.patch('/items/'+item['id'], headers={'Origin':'http://testserver'},
            json={'expectedCurrentVersionId':item['currentVersionId'],'content':'An entirely different decision.'})
        assert changed.status_code == 200
        assert client.get('/flares/'+flare['id']).json()['evidence'] == flare['evidence']
        snapshot = client.get(f"/items/{item['id']}/versions/{evidence['documentVersionId']}").json()
        assert evidence['excerpt'] in snapshot['item']['content']
        assert snapshot['isCurrent'] is False


@pytest.mark.parametrize('text', ['Release decision.\n'*3000, 'Решение о выпуске 🌍\n'*2000], ids=['ascii','utf8'])
def test_repair_is_exact_bounded_idempotent_and_does_not_queue_analysis(api_environment, monkeypatch, text):
    from app.services.note_repair import NoteRepair
    with api_environment.client() as client:
        old = legacy_note(client, monkeypatch, text)
        db, identity = client.app.state.database, identity_for(api_environment)
        service = NoteRepair(db, identity)
        before = api_environment.fetchone_admin('SELECT count(*) FROM analysis_jobs WHERE workspace_id=%s', (identity.workspace_id,))[0]
        plan = service.plan(limit=1)
        assert len(plan) == 1 and plan[0]['versionId'] == old['currentVersionId']
        assert 'content' not in plan[0] and 'title' not in plan[0]
        assert client.get('/items/'+old['id']).json()['currentVersionId'] == old['currentVersionId']
        result = service.apply(plan)
        assert result == {'repaired':1,'skipped':0}
        new = client.get('/items/'+old['id']).json()
        assert new['content'] == old['content'] and new['title'] == old['title']
        assert new['createdBy'] == old['createdBy'] and new.get('author') == old.get('author')
        assert new['versionNumber'] == old['versionNumber']+1
        maximum = api_environment.fetchone_admin('SELECT max(octet_length(content)) FROM chunks WHERE document_version_id=%s',(new['currentVersionId'],))[0]
        assert maximum <= 4000
        assert client.get(f"/items/{old['id']}/versions/{old['currentVersionId']}").json()['item']['content'] == old['content']
        assert service.plan(limit=1) == []
        assert service.apply(plan) == {'repaired':0,'skipped':1}
        assert api_environment.fetchone_admin('SELECT count(*) FROM analysis_jobs WHERE workspace_id=%s',(identity.workspace_id,))[0] == before


def test_repair_skips_concurrent_edit_and_rolls_back_a_partial_version(api_environment, monkeypatch):
    from app.services.note_repair import NoteRepair
    with api_environment.client() as client:
        old = legacy_note(client, monkeypatch, 'Release decision.\n'*3000)
        service = NoteRepair(client.app.state.database, identity_for(api_environment))
        plan = service.plan(limit=1)
        client.patch('/items/'+old['id'], json={'expectedCurrentVersionId':old['currentVersionId'],'content':'New decision.'})
        assert service.apply(plan) == {'repaired':0,'skipped':1}
        assert client.get('/items/'+old['id']).json()['content'] == 'New decision.'
        other = legacy_note(client, monkeypatch, 'Another release.\n'*3000)
        plan = service.plan(limit=1)
        original = ItemRepository.insert_chunk
        def fail_second(repository, **kwargs):
            if kwargs['ordinal'] == 1:
                raise RuntimeError('Synthetic interrupted repair')
            return original(repository, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(ItemRepository, 'insert_chunk', fail_second)
            with pytest.raises(RuntimeError):
                service.apply(plan)
        assert client.get('/items/'+other['id']).json()['currentVersionId'] == other['currentVersionId']
        assert api_environment.fetchone_admin('SELECT count(*) FROM document_versions WHERE document_id=%s',(other['id'],))[0] == 1


def test_repair_requires_owner_and_keeps_workspace_isolation(api_environment, monkeypatch):
    from app.services.note_repair import NoteRepair
    with api_environment.client() as client:
        old = legacy_note(client, monkeypatch, 'Release decision.\n'*3000)
        identity = identity_for(api_environment)
        service = NoteRepair(client.app.state.database, identity)
        with api_environment.client() as other:
            other_identity = WorkspaceIdentity(
                next(w for w in api_environment.workspace_ids if w != identity.workspace_id),
                next(u for u in api_environment.user_ids if u != identity.user_id))
            assert NoteRepair(other.app.state.database, other_identity).plan(limit=1) == []
        plan = service.plan(limit=1)
        api_environment.execute_admin("UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(identity.workspace_id,identity.user_id))
        with pytest.raises(WritePermissionRequiredError): service.plan(limit=1)
        with pytest.raises(WritePermissionRequiredError): service.apply(plan)
        assert client.get('/items/'+old['id']).json()['currentVersionId'] == old['currentVersionId']


def test_two_repairs_of_the_same_plan_publish_only_one_new_version(api_environment, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.services.note_repair import NoteRepair
    with api_environment.client() as client:
        old = legacy_note(client, monkeypatch, 'Release decision.\n'*3000)
        service = NoteRepair(client.app.state.database, identity_for(api_environment))
        plan = service.plan(limit=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: service.apply(plan), range(2)))
        assert sum(result['repaired'] for result in results) == 1
        assert sum(result['skipped'] for result in results) == 1
        assert api_environment.fetchone_admin('SELECT count(*) FROM document_versions WHERE document_id=%s',(old['id'],))[0] == 2


def test_repair_cli_is_dry_run_by_default_and_explicit_apply_is_repeatable(api_environment, monkeypatch, capsys):
    import importlib.util
    import json
    from pathlib import Path
    path=Path(__file__).parents[1]/'scripts/repair_note_chunks.py'
    spec=importlib.util.spec_from_file_location('repair_notes_cli',path)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with api_environment.client() as client:
        old=legacy_note(client,monkeypatch,'A private release decision.\n'*2000)
        identity=identity_for(api_environment)
        argv=['--workspace',str(identity.workspace_id),'--user',identity.user_id,'--limit','1']
        monkeypatch.delenv('NOTE_REPAIR_DATABASE_URL',raising=False)
        assert cli.main(argv)==2
        assert 'Set NOTE_REPAIR_DATABASE_URL' in capsys.readouterr().out
        monkeypatch.setenv('NOTE_REPAIR_DATABASE_URL',api_environment.runtime_url)
        monkeypatch.setenv('FLARE_DOTENV_PATH','not-a-file-and-must-not-be-read')
        assert cli.main(argv)==0
        report=capsys.readouterr().out
        assert json.loads(report)['mode']=='dry-run' and json.loads(report)['planned']==1
        assert 'private release decision' not in report and api_environment.runtime_url not in report
        assert client.get('/items/'+old['id']).json()['currentVersionId']==old['currentVersionId']
        assert cli.main([*argv,'--apply'])==0
        assert json.loads(capsys.readouterr().out)['repaired']==1
        assert cli.main(argv)==0
        assert json.loads(capsys.readouterr().out)['planned']==0


def test_eligible_legacy_notes_are_not_reversioned(api_environment, monkeypatch):
    from app.services.note_repair import NoteRepair
    from app.config import AISettings
    from app.ai_engine.analysis import Evidence
    from app.ai_engine.text_analysis_prompts import build_bounded_request
    with api_environment.client() as client:
        old=legacy_note(client,monkeypatch,'A clear release decision. '*300)
        build_bounded_request((Evidence(source_id=str(uuid4()),content=old['content']),),AISettings())
        service=NoteRepair(client.app.state.database,identity_for(api_environment))
        assert service.plan(limit=1)==[]
        assert client.get('/items/'+old['id']).json()['currentVersionId']==old['currentVersionId']


def test_repair_uses_the_complete_serialized_budget_not_only_raw_bytes(api_environment, monkeypatch):
    from app.services.note_repair import NoteRepair
    from app.config import AISettings
    from app.ai_engine.analysis import Evidence
    from app.ai_engine.text_analysis_prompts import build_bounded_request
    with api_environment.client() as client:
        old=legacy_note(client,monkeypatch,'"\\\n'*5000)
        assert len(old['content'].encode('utf-8'))<AISettings().max_input_bytes
        with pytest.raises(ValueError):
            build_bounded_request((Evidence(source_id=str(uuid4()),content=old['content']),),AISettings())
        service=NoteRepair(client.app.state.database,identity_for(api_environment))
        plan=service.plan(limit=1)
        assert len(plan)==1 and plan[0]['itemId']==old['id']
        assert service.apply(plan)=={'repaired':1,'skipped':0}
