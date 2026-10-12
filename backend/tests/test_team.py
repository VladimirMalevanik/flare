"""Real restricted PostgreSQL and two-account HTTP Team acceptance; no external mail."""
import os
import re
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4, UUID
import psycopg
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models.database import Database
from app.models.billing import BillingRepository
from app.services.auth_service import AuthService
from app.services.team import TeamService

pytestmark = pytest.mark.integration
TEAM_PRICE = 'pri_'+'t'*26
PRO_PRICE = 'pri_'+'p'*26


class Mail:
    def __init__(self): self.messages=[]; self.fail=False
    def send(self, **message):
        if self.fail: raise RuntimeError('PRIVATE_SMTP_DETAIL')
        self.messages.append(message)
    @property
    def token(self): return re.search(r'/join#([A-Za-z0-9_-]{43})',self.messages[-1]['text']).group(1)


@pytest.fixture
def team():
    runtime, admin = os.getenv('DATABASE_URL'), os.getenv('TEST_DATABASE_URL')
    if not runtime or not admin: pytest.skip('Requires separate migrated PostgreSQL')
    db=Database(runtime); db.open(); auth=AuthService(db)
    mail=Mail(); stack=ExitStack(); users=[]; events=[]; projects=[]
    config=Settings(database_url=runtime,environment='test',cors_origins=['http://testserver'],team_enabled=True,
        paddle_pro_price_id=PRO_PRICE,paddle_team_price_id=TEAM_PRICE,paddle_webhook_secret='synthetic-secret',app_public_url='http://localhost:8427')
    with psycopg.connect(admin) as c:
        c.execute('UPDATE team_policy SET enabled=true,price_id=%s,max_projects=1,max_members=10,max_tasks=1000,max_content_bytes=104857600,max_documents=5000,max_invites_daily=20',(TEAM_PRICE,))
    class Fixture:
        def query(self,query,*args):
            with psycopg.connect(admin) as c:
                cursor=c.execute(query,args)
                return cursor.fetchall() if cursor.description else []
        def account(self,verified=True):
            email=str(uuid4())+'@team-test.invalid'; token=auth.register(email,'long-test-password','Member '+str(len(users)))
            user=auth.current(token); users.append(user)
            if verified: self.query("UPDATE auth_users SET verification_provenance='actual' WHERE id=%s",user.user_id)
            client=stack.enter_context(TestClient(create_app(config,email_sender=mail),headers={'Origin':'http://testserver'}))
            client.cookies.set('flare_session',token)
            return user,client
        def paid(self,user,price=TEAM_PRICE,status='active'):
            repo=BillingRepository(db); digest=sha256(uuid4().bytes).hexdigest(); now=datetime.now(timezone.utc)
            repo.create_intent(user.identity,digest,price,7200)
            now=datetime.now(timezone.utc)
            event=dict(event_id='evt_'+uuid4().hex,event_type='subscription.created',occurred_at=now,
                payload_hash=sha256(uuid4().bytes).hexdigest(),subscription_id='sub_'+uuid4().hex,customer_id='ctm_'+uuid4().hex,
                price_id=price,product_id='pro_'+uuid4().hex,quantity=1,status=status,intent_hash=digest,
                trial_starts_at=now-timedelta(seconds=1),trial_ends_at=now+timedelta(days=30),
                current_period_starts_at=now-timedelta(seconds=1),current_period_ends_at=now+timedelta(days=30),
                next_billed_at=now+timedelta(days=30),scheduled_action=None,scheduled_effective_at=None)
            assert repo.apply_event(event)=='applied'; events.append(event['event_id']); return event
        def create(self,user,client):
            self.paid(user); wid=uuid4(); response=client.post('/team/projects',json={'id':str(wid),'name':'Flare Team'})
            assert response.status_code==201,response.text;projects.append(wid);return str(wid)
        def invite(self,client,wid,user,role='editor'):
            r=client.post(f'/team/projects/{wid}/invitations',json={'email':user.email,'role':role,'sharingAcknowledged':True})
            assert r.status_code==201,r.text;return mail.token,r.json()['id']
        def accept(self,client,token): return client.post('/team/invitations/accept',json={'token':token,'accept':True})
    f=Fixture(); f.projects=projects; f.db=db; f.mail=mail; f.config=config
    try: yield f
    finally:
        stack.close();db.close()
        from test_items_api import ApiEnvironment
        cleanup=ApiEnvironment(runtime,admin);cleanup.workspace_ids.update([u.workspace_id for u in users]+projects);cleanup.user_ids.update(u.user_id for u in users)
        with psycopg.connect(admin) as c:
            c.execute('SET LOCAL session_replication_role=replica')
            for table in ('team_task_history','team_member_events','team_invitations','team_tasks','team_projects'):
                c.execute(f'DELETE FROM public.{table} WHERE workspace_id=ANY(%s)',(projects,))
            c.execute('DELETE FROM billing_webhook_events WHERE event_id=ANY(%s)',(events,))
            c.execute('UPDATE team_policy SET enabled=false,price_id=NULL')
        cleanup.cleanup()


def test_team_only_project_creation_and_no_personal_data_copy(team):
    owner,c=team.account(); wid=str(uuid4())
    payload={'id':wid,'name':'Shared'}
    assert c.post('/team/projects',json=payload).status_code==403
    team.paid(owner,price=PRO_PRICE)
    assert c.post('/team/projects',json=payload).status_code==403
    private=c.post('/items',json={'type':'note','content':'Private founder note'}).json()
    wid=team.create(owner,c)
    assert c.get('/items',params={'workspace':wid}).json()==[]
    assert c.get('/items').json()[0]['id']==private['id']
    assert c.post('/team/projects',json={'id':wid,'name':'Retry'}).status_code==201
    assert c.post('/team/projects',json={'id':str(uuid4()),'name':'Beyond limit'}).status_code==409


def test_two_accounts_join_share_and_author_is_server_owned(team):
    owner,c=team.account(); member,m=team.account(); outsider,o=team.account(); wid=team.create(owner,c)
    token,_=team.invite(c,wid,member)
    assert team.accept(o,token).status_code==404
    assert team.accept(m,token).status_code==200
    assert team.accept(m,token).status_code==200
    assert wid in [p['id'] for p in m.get('/team/projects').json()['projects']]
    r=m.post('/items',params={'workspace':wid},json={'type':'note','content':'Our shared interview'})
    assert r.status_code==201,r.text
    assert len(c.get('/items',params={'workspace':wid}).json())==1
    assert m.get('/items').json()==[]
    assert o.get('/items',params={'workspace':wid}).status_code==404
    task_id=str(uuid4());path=f'/team/projects/{wid}/tasks'
    base={'id':task_id,'expectedVersion':0,'title':'Interview customers','assigneeId':owner.user_id}
    assert m.post(path,json={**base,'createdBy':owner.user_id}).status_code==422
    r=m.post(path,json=base);assert r.status_code==200,r.text
    task=c.get(path).json()['tasks'][0]
    assert task['createdBy']==member.user_id and task['creatorName']==member.name and task['assigneeId']==owner.user_id
    assert c.post(path,json={'id':task_id,'expectedVersion':1,'status':'doing'}).status_code==200
    assert m.post(path,json={'id':task_id,'expectedVersion':1,'title':'Stale edit'}).status_code==409
    assert c.get(path).json()['tasks'][0]['title']=='Interview customers'
    history=m.get(path+'/'+task_id+'/history').json();assert len(history)==2
    assert history[0]['actorName']==owner.name


def test_viewer_removed_member_and_last_owner_guards(team):
    owner,c=team.account(); member,m=team.account(); wid=team.create(owner,c)
    token,_=team.invite(c,wid,member,'viewer');assert team.accept(m,token).status_code==200
    assert m.get(f'/team/projects/{wid}/members').status_code==200
    assert all(x['email'] is None for x in m.get(f'/team/projects/{wid}/members').json())
    assert m.post('/items',params={'workspace':wid},json={'type':'note','content':'Denied'}).status_code==403
    path=f'/team/projects/{wid}/members/'
    assert m.post(path+owner.user_id,json={'action':'remove'}).status_code==403
    assert c.post(path+owner.user_id,json={'action':'leave'}).status_code==409
    assert c.post(path+member.user_id,json={'action':'role','role':'editor'}).status_code==200
    task_id=str(uuid4());tasks=f'/team/projects/{wid}/tasks'
    assert c.post(tasks,json={'id':task_id,'expectedVersion':0,'title':'Owned by editor','assigneeId':member.user_id}).status_code==200
    assert c.post(path+member.user_id,json={'action':'remove'}).status_code==200
    assert m.get('/items',params={'workspace':wid}).status_code==404
    assert m.get(tasks).status_code==404
    assert c.get(tasks).json()['tasks'][0]['assigneeId'] is None
    assert m.get('/items').status_code==200


@pytest.mark.parametrize('state',['expired','canceled','past_due','paused','period_end','watermark','quantity','scheduled'])
def test_expired_team_retains_reads_and_blocks_new_work(team,state):
    owner,c=team.account(); wid=team.create(owner,c)
    assert c.post('/items',params={'workspace':wid},json={'type':'note','content':'Kept context'}).status_code==201
    changes={'expired':"trial_ends_at=now()-interval '1s',status='trialing'",'canceled':"status='canceled'",'past_due':"status='past_due'",
        'paused':"status='paused'",'period_end':"current_period_ends_at=now()-interval '1s'",'watermark':'watermark_conflict=true',
        'quantity':'quantity=0','scheduled':"scheduled_action='cancel',scheduled_effective_at=now()-interval '1s'"}
    team.query('UPDATE billing_subscriptions SET '+changes[state]+' WHERE workspace_id=%s',owner.workspace_id)
    assert len(c.get('/items',params={'workspace':wid}).json())==1
    assert c.post('/items',params={'workspace':wid},json={'type':'note','content':'Blocked'}).status_code==403
    assert c.post(f'/team/projects/{wid}/tasks',json={'id':str(uuid4()),'expectedVersion':0,'title':'Blocked'}).status_code==403
    assert c.get('/export',params={'workspace':wid}).status_code==200
    assert c.get('/team/projects').json()['projects'][1]['writable'] is False


def test_cancel_resend_and_pending_seats(team):
    owner,c=team.account(); member,m=team.account(); other,o=team.account(); wid=team.create(owner,c)
    team.query('UPDATE team_policy SET max_members=2')
    token,inv=team.invite(c,wid,member)
    assert c.post(f'/team/projects/{wid}/invitations',json={'email':other.email,'sharingAcknowledged':True}).status_code==409
    assert c.delete(f'/team/projects/{wid}/invitations/{inv}').status_code==204
    assert team.accept(m,token).status_code==404
    token2,_=team.invite(c,wid,other)
    assert team.accept(o,token2).status_code==200
    assert c.post(f'/team/projects/{wid}/invitations',json={'email':member.email,'sharingAcknowledged':True}).status_code==409


def test_bypassed_verification_cannot_join_or_create_and_can_reverify(team):
    owner,c=team.account(); member,m=team.account(verified=False); wid=team.create(owner,c)
    token,_=team.invite(c,wid,member)
    assert team.accept(m,token).status_code==403
    assert m.get('/team/projects').json()['capability']['requiresVerification'] is True
    assert m.post('/team/verify-email').status_code==200
    verify_token=re.search(r'token=([A-Za-z0-9_-]{43})',team.mail.messages[-1]['text']).group(1)
    assert m.post('/auth/verify-email',json={'token':verify_token}).status_code==200
    assert team.accept(m,token).status_code==200


def test_email_failure_cancels_link_without_exposing_provider_error(team):
    owner,c=team.account(); member,m=team.account(); wid=team.create(owner,c);team.mail.fail=True
    r=c.post(f'/team/projects/{wid}/invitations',json={'email':member.email,'sharingAcknowledged':True})
    assert r.status_code==503 and 'PRIVATE_SMTP_DETAIL' not in r.text
    assert c.get(f'/team/projects/{wid}/invitations').json()[0]['status']=='canceled'


def test_task_limit_counts_archived_rows_and_bounds_history(team):
    owner,c=team.account(); wid=team.create(owner,c);team.query('UPDATE team_policy SET max_tasks=1');tasks=f'/team/projects/{wid}/tasks';tid=str(uuid4())
    assert c.post(tasks,json={'id':tid,'expectedVersion':0,'title':'One'}).status_code==200
    assert c.post(tasks,json={'id':str(uuid4()),'expectedVersion':0,'title':'Two'}).status_code==409
    for version in range(1,55):
        r=c.post(tasks,json={'id':tid,'expectedVersion':version,'title':'Task '+str(version)});assert r.status_code==200,r.text
    assert len(c.get(tasks+'/'+tid+'/history').json())==50
    assert c.post(tasks,json={'id':tid,'expectedVersion':55,'remove':True}).status_code==200
    assert c.get(tasks).json()['tasks']==[]
    replacement=str(uuid4())
    assert c.post(tasks,json={'id':replacement,'expectedVersion':0,'title':'Replacement'}).status_code==200
    assert c.post(tasks,json={'id':replacement,'expectedVersion':1,'remove':True}).status_code==200
    assert c.post(tasks,json={'id':str(uuid4()),'expectedVersion':0,'title':'Storage bypass'}).status_code==409
    team.query("UPDATE team_tasks SET deleted_at=now()-interval '31 days' WHERE workspace_id=%s",UUID(wid))
    assert c.post(tasks,json={'id':str(uuid4()),'expectedVersion':0,'title':'After retirement'}).status_code==200


def test_db_runtime_cannot_assign_membership_or_write_team_tables(team):
    owner,c=team.account(); wid=team.create(owner,c)
    with team.db.connection() as conn:
        for query in ['SELECT token_hash FROM team_invitations','UPDATE team_policy SET enabled=true','DELETE FROM team_tasks',
            'SELECT public._team_paid(NULL)','INSERT INTO workspace_members(workspace_id,user_id) VALUES(NULL,\'self\')']:
            with pytest.raises(psycopg.errors.InsufficientPrivilege),conn.transaction(): conn.execute(query)


def test_documents_storage_is_atomic_and_shared_between_members(team):
    owner,c=team.account(); member,m=team.account(); wid=team.create(owner,c);token,_=team.invite(c,wid,member);team.accept(m,token)
    team.query('UPDATE team_policy SET max_documents=1')
    assert c.post('/items',params={'workspace':wid},json={'type':'note','content':'First'}).status_code==201
    assert m.post('/items',params={'workspace':wid},json={'type':'note','content':'Over limit'}).status_code!=201
    assert len(c.get('/items',params={'workspace':wid}).json())==1


def test_transfer_rebinds_schedule_keeps_license_payer_and_revokes_old_invites(team):
    owner,c=team.account(); member,m=team.account(); wid=team.create(owner,c);token,_=team.invite(c,wid,member);team.accept(m,token)
    team.query("INSERT INTO analysis_schedules(workspace_id,updated_by_user_id) VALUES(%s,%s)",UUID(wid),owner.user_id)
    other,o=team.account();old_token,_=team.invite(c,wid,other)
    r=c.post(f'/team/projects/{wid}/members/{member.user_id}',json={'action':'transfer'});assert r.status_code==200,r.text
    assert team.query('SELECT updated_by_user_id FROM analysis_schedules WHERE workspace_id=%s',UUID(wid))[0][0]==member.user_id
    assert team.query('SELECT license_workspace_id FROM team_projects WHERE workspace_id=%s',UUID(wid))[0][0]==owner.workspace_id
    assert c.post(f'/team/projects/{wid}/invitations',json={'email':'new@team-test.invalid','sharingAcknowledged':True}).status_code==403
    assert team.accept(o,old_token).status_code==404


def test_team_checkout_uses_server_price_and_does_not_grant_browser_access(team):
    owner,c=team.account()
    r=c.post('/billing/checkout-intents',json={'plan':'team'});assert r.status_code==201,r.text
    assert r.json()['priceId']==TEAM_PRICE and r.json()['quantity']==1
    assert c.post('/team/projects',json={'id':str(uuid4()),'name':'Unpaid'}).status_code==403
    assert c.post('/billing/checkout-intents',json={'plan':'team','priceId':PRO_PRICE}).status_code==400
    wid=team.create(owner,c)
    assert c.get('/billing/status').json()['plan']=='team'
    child=c.get('/billing/status',params={'workspace':wid});assert child.status_code==200,child.text
    assert child.json()['plan']=='team' and child.json()['canManageBilling'] is False
    assert c.post('/billing/checkout-intents',params={'workspace':wid},json={'plan':'team'}).status_code==403


def test_preview_is_email_bound_and_shows_only_project_invitation(team):
    owner,c=team.account();member,m=team.account();outsider,o=team.account();wid=team.create(owner,c);token,_=team.invite(c,wid,member)
    assert o.post('/team/invitations/preview',json={'token':token}).status_code==404
    preview=m.post('/team/invitations/preview',json={'token':token});assert preview.status_code==200,preview.text
    assert preview.json()['projectName']=='Flare Team' and preview.json()['invitedBy']==owner.name
    assert 'token' not in preview.json() and 'email' not in preview.json()


def test_create_retry_is_idempotent_and_single_task_get_is_scoped(team):
    owner,c=team.account();wid=team.create(owner,c);path=f'/team/projects/{wid}/tasks';tid=str(uuid4());body={'id':tid,'expectedVersion':0,'title':'Retry safely'}
    assert c.post(path,json=body).status_code==200
    assert c.post(path,json=body).status_code==200
    assert len(c.get(path).json()['tasks'])==1 and len(c.get(path+'/'+tid+'/history').json())==1
    assert c.get(path+'/'+tid).json()['creatorName']==owner.name
    stranger,s=team.account();assert s.get(path+'/'+tid).status_code==404


def test_concurrent_project_creation_and_pending_seats_are_atomic(team):
    from concurrent.futures import ThreadPoolExecutor
    owner,c=team.account();team.paid(owner);svc=TeamService(team.db,owner.user_id)
    def attempt(args):
        try:return svc.call(*args)
        except psycopg.Error as error:return error.sqlstate
    ids=[uuid4(),uuid4()]
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[('create',tid,'Concurrent') for tid in ids]))
    created=[r for r in results if isinstance(r,UUID)];team.projects.extend(created);assert len(created)==1 and 'P0003' in results
    wid=created[0];team.query('UPDATE team_policy SET max_members=2')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,[('invite',wid,'one@team-test.invalid','editor',sha256(uuid4().bytes).hexdigest()),('invite',wid,'two@team-test.invalid','editor',sha256(uuid4().bytes).hexdigest())]))
    assert len([r for r in results if isinstance(r,dict)])==1 and 'P0003' in results


def test_two_editors_cannot_overwrite_same_task_version(team):
    from concurrent.futures import ThreadPoolExecutor
    from psycopg.types.json import Jsonb
    owner,c=team.account();member,m=team.account();wid=team.create(owner,c);token,_=team.invite(c,wid,member);team.accept(m,token)
    tid=uuid4();svc=TeamService(team.db,owner.user_id);svc.call('task',UUID(wid),tid,0,Jsonb({'title':'Original'}),False)
    def change(user):
        try:return TeamService(team.db,user.user_id).call('task',UUID(wid),tid,1,Jsonb({'title':user.name}),False)
        except psycopg.Error as error:return error.sqlstate
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(change,[owner,member]))
    assert len([r for r in results if isinstance(r,dict)])==1 and '40001' in results
    assert c.get(f'/team/projects/{wid}/tasks/{tid}').json()['version']==2


def test_utf8_storage_budget_keeps_failed_publication_atomic(team):
    from app.services.item_service import ItemService
    from app.models.database import WorkspaceIdentity
    owner,c=team.account();wid=team.create(owner,c);team.query('UPDATE team_policy SET max_content_bytes=1048576')
    svc=ItemService(team.db,WorkspaceIdentity(UUID(wid),owner.user_id))
    for _ in range(10):svc.create_note(title='Stored',content='x'*100000)
    with pytest.raises(psycopg.Error):svc.create_note(title='Overflow',content='я'*30000)
    assert len(c.get('/items',params={'workspace':wid}).json())==10
    assert team.query('SELECT sum(octet_length(content)) FROM chunks WHERE workspace_id=%s',UUID(wid))[0][0]==1000000
    usage=c.get(f'/team/projects/{wid}/usage').json()
    assert usage['contentBytes']==1000000 and usage['documents']==10


def test_team_bodies_are_bounded_before_json_parsing(team):
    _,c=team.account()
    assert c.post('/team/projects',content=b' '*70000,headers={'Content-Type':'application/json'}).status_code==413
    assert c.post('/team/projects',content=iter([b' '*40000,b' '*40000]),headers={'Content-Type':'application/json'}).status_code==413


def test_task_keyset_cursor_includes_all_rows_without_cross_project_leaks(team):
    from psycopg.types.json import Jsonb
    owner,c=team.account();wid=team.create(owner,c);svc=TeamService(team.db,owner.user_id)
    for i in range(105):svc.call('task',UUID(wid),uuid4(),0,Jsonb({'title':str(i)}),False)
    path=f'/team/projects/{wid}/tasks';page=c.get(path).json();assert len(page['tasks'])==100 and page['nextCursor']
    rest=c.get(path,params=page['nextCursor']).json();assert len(rest['tasks'])==5 and rest['nextCursor'] is None
    assert len({t['id'] for t in page['tasks']+rest['tasks']})==105
    assert c.get(path+'/'+rest['tasks'][0]['id']).status_code==200


def test_unpaid_team_is_filtered_before_scheduler_without_blocking_personal_projects(team):
    owner,c=team.account();wid=team.create(owner,c);personal,p=team.account();now=datetime.now(timezone.utc)
    # Both projects have the same due slot. Prepare an older update timestamp
    # exactly as a schedule configured earlier would have, without real AI.
    due=(now+timedelta(minutes=10)).time().replace(tzinfo=None)
    for workspace,user in [(UUID(wid),owner),(personal.workspace_id,personal)]:
        team.query("INSERT INTO analysis_schedules(workspace_id,enabled,local_time,updated_by_user_id) VALUES(%s,true,%s,%s)",workspace,due,user.user_id)
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute("UPDATE analysis_schedules SET updated_at=now()-interval '1 hour' WHERE workspace_id=ANY(%s)",([UUID(wid),personal.workspace_id],))
    team.query("UPDATE billing_subscriptions SET status='canceled' WHERE workspace_id=%s",owner.workspace_id)
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        conn.execute('SET LOCAL ROLE flare_worker')
        assert conn.execute('SELECT materialize_analysis_cycles(%s,100)',(now,)).fetchone()[0]==1
    assert team.query('SELECT count(*) FROM analysis_cycles WHERE workspace_id=%s',UUID(wid))[0][0]==0
    assert team.query('SELECT count(*) FROM analysis_cycles WHERE workspace_id=%s',personal.workspace_id)[0][0]==1


def test_disable_team_keeps_personal_workspace_and_denies_selected_team_requests(team):
    owner,c=team.account();wid=team.create(owner,c);team.config.team_enabled=False
    assert c.get('/items').status_code==200
    assert c.get('/items',params={'workspace':wid}).status_code==403
    assert c.get('/team/projects').status_code==503


def test_project_rename_is_owner_only_and_export_keeps_author_on_readonly_license(team):
    owner,c=team.account();member,m=team.account();wid=team.create(owner,c);token,_=team.invite(c,wid,member);team.accept(m,token)
    assert m.patch(f'/team/projects/{wid}',json={'name':'Not allowed'}).status_code==403
    assert c.patch(f'/team/projects/{wid}',json={'name':'Customer Research'}).status_code==200
    assert m.get('/team/projects').json()['projects'][1]['name']=='Customer Research'
    assert m.post(f'/team/projects/{wid}/tasks',json={'id':str(uuid4()),'expectedVersion':0,'title':'Shared task'}).status_code==200
    team.query("UPDATE billing_subscriptions SET status='canceled' WHERE workspace_id=%s",owner.workspace_id)
    response=m.get(f'/team/projects/{wid}/tasks/export');assert response.status_code==200,response.text
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.json()['tasks'][0]['creatorName']==member.name
    stranger,s=team.account();assert s.get(f'/team/projects/{wid}/tasks/export').status_code==404


def test_team_oauth_state_selects_its_bound_project_and_returns_to_that_project(team):
    from app.api import github
    from fastapi import Depends
    from typing import Annotated
    from app.services.auth_service import AuthenticatedUser
    from types import SimpleNamespace
    owner,c=team.account();other,o=team.account();wid=team.create(owner,c);raw='a'*43;digest=sha256(raw.encode()).hexdigest()
    team.query("INSERT INTO github_connection_states(token_hash,workspace_id,user_id,expires_at) VALUES(%s,%s,%s,now()+interval '5 minutes')",digest,UUID(wid),owner.user_id)
    assert TeamService(team.db,other.user_id).call('oauth',digest,'github-app') is None
    selected=[]
    def fake_service(user:Annotated[AuthenticatedUser,Depends(github.session_user)]):
        selected.append(user.workspace_id)
        return SimpleNamespace(complete=lambda *_args:None)
    c.app.dependency_overrides[github.service]=fake_service
    c.app.state.github_settings=SimpleNamespace(frontend_return_url=team.config.app_public_url+'/sources')
    response=c.get('/integrations/github/callback',params={'state':raw,'installation_id':1,'code':'synthetic'},follow_redirects=False)
    assert response.status_code==303,response.text
    assert selected==[UUID(wid)]
    assert 'project='+wid in response.headers['location'] and 'github=select' in response.headers['location']


def test_sharing_and_acceptance_require_literal_true(team):
    owner,c=team.account();member,m=team.account();wid=team.create(owner,c)
    assert c.post(f'/team/projects/{wid}/invitations',json={'email':member.email,'sharingAcknowledged':1}).status_code==422
    token,_=team.invite(c,wid,member)
    assert m.post('/team/invitations/accept',json={'token':token,'accept':1}).status_code==422


def test_sources_integration_removal_retires_credentials_states_and_leases(team):
    if team.query("SELECT to_regclass('public.source_connections')")[0][0] is None:pytest.skip('Requires DATA-003 integration tree')
    owner,c=team.account();member,m=team.account();wid=team.create(owner,c);token,_=team.invite(c,wid,member);team.accept(m,token)
    cid=uuid4();jid=uuid4();lease=uuid4();digest=sha256(uuid4().bytes).hexdigest()
    try:
        team.query("INSERT INTO source_connections(id,workspace_id,provider,owner_user_id,credential_blob,cursor_blob,status,enabled) VALUES(%s,%s,'gmail',%s,'synthetic-cipher','synthetic-draft','ready',true)",cid,UUID(wid),member.user_id)
        team.query("INSERT INTO source_auth_states(state_hash,workspace_id,connection_id,user_id,scope_revision,pending_blob,expires_at) VALUES(%s,%s,%s,%s,1,'synthetic-state',now()+interval '5 minutes')",digest,UUID(wid),cid,member.user_id)
        assert TeamService(team.db,member.user_id).call('oauth',digest,'gmail')==UUID(wid)
        assert TeamService(team.db,owner.user_id).call('oauth',digest,'gmail') is None
        team.query("INSERT INTO source_jobs(id,workspace_id,connection_id,owner_user_id,scope_revision,status,lease_token,lease_expires_at,cursor_blob) VALUES(%s,%s,%s,%s,1,'processing',%s,now()+interval '2 minutes','synthetic-draft')",jid,UUID(wid),cid,member.user_id,lease)
        assert c.post(f'/team/projects/{wid}/members/{member.user_id}',json={'action':'remove'}).status_code==200
        assert team.query('SELECT credential_blob,cursor_blob,enabled FROM source_connections WHERE id=%s',cid)==[(None,None,False)]
        assert team.query('SELECT count(*) FROM source_auth_states WHERE workspace_id=%s',UUID(wid))==[(0,)]
        assert team.query('SELECT status,lease_token,cursor_blob FROM source_jobs WHERE id=%s',jid)==[('cancelled',None,None)]
    finally:
        for table in ('source_items','source_jobs','source_auth_states','source_connections'):
            team.query(f'DELETE FROM {table} WHERE workspace_id=%s',UUID(wid))


def test_sources_integration_expiry_stops_provider_admission(team):
    if team.query("SELECT to_regclass('public.source_connections')")[0][0] is None:pytest.skip('Requires DATA-003 integration tree')
    owner,c=team.account();wid=team.create(owner,c);cid=uuid4()
    try:
        team.query("INSERT INTO source_connections(id,workspace_id,provider,owner_user_id,credential_blob,status,enabled) VALUES(%s,%s,'gmail',%s,'synthetic-cipher','ready',true)",cid,UUID(wid),owner.user_id)
        team.query("UPDATE billing_subscriptions SET status='canceled' WHERE workspace_id=%s",owner.workspace_id)
        with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as worker:
            assert worker.execute("SELECT claim_source_job(ARRAY['gmail'],1)").fetchone()[0] is None
        assert team.query('SELECT credential_blob,enabled FROM source_connections WHERE id=%s',cid)==[(None,False)]
        assert team.query('SELECT count(*) FROM source_jobs WHERE workspace_id=%s',UUID(wid))==[(0,)]
    finally:
        for table in ('source_items','source_jobs','source_auth_states','source_connections'):
            team.query(f'DELETE FROM {table} WHERE workspace_id=%s',UUID(wid))
