"""Trusted source creators and read-time legacy provenance, under runtime RLS."""
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.models.tables import ItemRepository
from test_source_sync import db, tenant, actor, api, connected, document, next_job, step
from test_import_packages import env, enqueue, checkpoint
from test_team import team
from test_zip_import import archive_bytes

pytestmark = pytest.mark.integration


def member(db, w, role='viewer', name='Reader'):
    db.execute('RESET ROLE')
    u = 'source-test|' + uuid4().hex
    db.execute('INSERT INTO auth_users(id,email,name,password_hash,initial_workspace_id) VALUES(%s,%s,%s,%s,%s)',
               (u, u+'@example.invalid', name, 'synthetic', w))
    db.execute('INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(%s,%s,%s)', (w,u,role))
    return u


def legacy(db, doc, *, metadata=None):
    """Seed the missing-author shape produced before0028, only in a rolled-back test tenant."""
    db.execute('RESET ROLE')
    db.execute("SET LOCAL session_replication_role='replica'")
    if metadata is None:
        db.execute("UPDATE documents SET metadata=metadata-'createdBy'-'createdByName' WHERE id=%s", (doc,))
        db.execute("UPDATE document_versions SET snapshot_metadata=snapshot_metadata-'createdBy'-'createdByName' WHERE document_id=%s", (doc,))
    else:
        db.execute('UPDATE documents SET metadata=%s WHERE id=%s', (Jsonb(metadata), doc))
        db.execute('UPDATE document_versions SET snapshot_metadata=%s WHERE document_id=%s', (Jsonb(metadata), doc))
    db.execute("SET LOCAL session_replication_role='origin'")


def persisted(db, doc):
    db.execute('RESET ROLE')
    return db.execute('''SELECT to_jsonb(d) AS document,
      (SELECT jsonb_agg(to_jsonb(v) ORDER BY version_number) FROM document_versions v WHERE document_id=d.id) AS versions,
      (SELECT jsonb_agg(to_jsonb(c) ORDER BY c.id) FROM chunks c JOIN document_versions v ON v.id=c.document_version_id WHERE v.document_id=d.id) AS chunks
      FROM documents d WHERE d.id=%s''', (doc,)).fetchone()


def test_source_actor_cannot_be_spoofed_and_original_name_survives_resync(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    record=document(job); record['metadata'].update(createdBy='attacker',createdByName='Fake author')
    assert step(db,job,'publish',documents=[record])['added']==1
    db.execute('RESET ROLE')
    doc=db.execute('SELECT document_id FROM source_items WHERE connection_id=%s',(id,)).fetchone()['document_id']
    first=persisted(db,doc)
    assert first['document']['metadata']['createdBy']==u
    assert first['versions'][0]['snapshot_metadata']['createdByName']=='Test'
    db.execute("UPDATE auth_users SET name='Renamed' WHERE id=%s",(u,))
    job=next_job(db,w,u,id)
    record=document(job,'Changed feedback'); record['metadata'].update(createdBy='attacker',createdByName='Fake author')
    assert step(db,job,'publish',documents=[record])['updated']==1
    actor(db,w,u)
    current=ItemRepository(db).get_active(doc)
    assert (current.metadata['createdBy'],current.metadata['createdByName'])==(u,'Test')
    assert current.version_number==2
    assert ItemRepository(db).get_version_snapshot(doc,first['versions'][0]['id']).item.metadata['createdByName']=='Test'


def test_legacy_source_author_readable_after_removal_without_rewriting_history(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    assert step(db,job,'publish',documents=[document(job)])['added']==1
    db.execute('RESET ROLE')
    doc=db.execute('SELECT document_id FROM source_items WHERE connection_id=%s',(id,)).fetchone()['document_id']
    legacy(db,doc); before=persisted(db,doc)
    reader=member(db,w)
    db.execute('DELETE FROM workspace_members WHERE workspace_id=%s AND user_id=%s',(w,u))
    db.execute('UPDATE auth_users SET disabled=true WHERE id=%s',(u,))
    actor(db,w,reader)
    repo=ItemRepository(db)
    for item in [repo.get_active(doc),repo.get_version_snapshot(doc,before['versions'][0]['id']).item,
                 repo.list_active(query=None,item_type=None,limit=100)[0]]:
        assert (item.metadata['createdBy'],item.metadata['createdByName'])==(u,'Test')
        assert item.content=='Feedback'
    assert persisted(db,doc)==before


def test_source_provenance_lookup_is_bounded_scoped_and_has_no_private_account_fields(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    assert step(db,job,'publish',documents=[])['added']==0
    reader=member(db,w)
    other,v=tenant(db); foreign,_=connected(db,other,v)
    actor(db,w,reader)
    creators=api(db,'creators',connectionIds=[id,foreign])
    assert creators==[{'id':id,'createdBy':u,'createdByName':'Test'}]
    assert api(db,'creators',connectionIds=[id]*101)['error']=='invalid_request'
    for invalid in (None,{},['not-a-uuid'],[1]):
        assert api(db,'creators',connectionIds=invalid)['error']=='invalid_request'
    actor(db,other,v)
    assert api(db,'creators',connectionIds=[id])==[]
    db.execute('RESET ROLE'); db.execute('DELETE FROM workspace_members WHERE workspace_id=%s AND user_id=%s',(other,v))
    actor(db,other,v)
    assert api(db,'creators',connectionIds=[id])['error']=='forbidden'


def test_arbitrary_manual_metadata_and_foreign_source_pointer_cannot_assign_an_author(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    step(db,job,'publish',documents=[document(job)])
    db.execute('RESET ROLE')
    doc=db.execute('SELECT document_id FROM source_items WHERE connection_id=%s',(id,)).fetchone()['document_id']
    legacy(db,doc)
    other,v=tenant(db); foreign,_=connected(db,other,v)
    # A legacy source snapshot must still resolve only within its own workspace.
    legacy(db,doc,metadata={'sourceConnectionId':foreign,'sourceProvider':'gmail'})
    actor(db,w,u)
    assert not ItemRepository(db).get_active(doc).metadata.get('createdBy')
    # A manually created record cannot turn arbitrary metadata into trusted provenance.
    db.execute('RESET ROLE'); db.execute("SET LOCAL session_replication_role='replica'")
    db.execute("UPDATE document_versions SET parser_version='manual-note-v1',snapshot_metadata=%s WHERE document_id=%s",(Jsonb({'sourceConnectionId':id}),doc))
    db.execute("SET LOCAL session_replication_role='origin'")
    actor(db,w,u)
    assert not ItemRepository(db).get_active(doc).metadata.get('createdBy')


@pytest.mark.parametrize('kind', ['notion', 'obsidian'])
def test_zip_creator_legacy_history_and_dedupe_stay_with_original_uploader(env,team,kind):
    e,storage,jobs=env
    owner,c=team.account(); uploader,m=team.account(); w=team.create(owner,c)
    token,_=team.invite(c,w,uploader); assert team.accept(m,token).status_code==200
    class Scoped:
        def __init__(self,client): self.client=client
        def post(self,url,**kwargs): return self.client.post(url,params={'workspace':w},**kwargs)
        def put(self,url,**kwargs): return self.client.put(url,params={'workspace':w},**kwargs)
    for client in (c,m): client.app.state.import_storage=storage
    raw=archive_bytes([('idea.md','Customer needs faster onboarding')])
    package=enqueue(Scoped(m),raw,kind); job=jobs.claim(2); assert job['id']==package
    checkpoint(jobs,storage,job); jobs.step(job,'gate')
    item=c.get('/items',params={'workspace':w}).json()[0]
    assert (item['createdBy'],item['author'])==(uploader.user_id,uploader.name)
    doc=item['id']; version=item['currentVersionId']
    # Simulate pre0028 published data; the production migration never rewrites it.
    with psycopg.connect(e.admin_url,row_factory=dict_row) as db:
        legacy(db,doc); before=persisted(db,doc)
    assert enqueue(Scoped(c),raw,kind)==package
    shared=c.get('/items/'+doc,params={'workspace':w}).json()
    assert (shared['createdBy'],shared['author'])==(uploader.user_id,uploader.name)
    assert shared['currentVersionId']==version
    historical=c.get('/items/'+doc+'/versions/'+version,params={'workspace':w})
    assert historical.status_code==200,historical.text
    assert historical.json()['item']['author']==uploader.name
    with psycopg.connect(e.admin_url,row_factory=dict_row) as db:
        assert persisted(db,doc)==before
