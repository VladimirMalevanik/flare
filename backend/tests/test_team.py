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
    f=Fixture(); f.db=db; f.mail=mail; f.config=config
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
    assert c.post(tasks,json={'id':str(uuid4()),'expectedVersion':0,'title':'Storage bypass'}).status_code==409


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
    r=c.post(f'/team/projects/{wid}/members/{member.user_id}',json={'action':'transfer'});assert r.status_code==200,r.text
    assert team.query('SELECT updated_by_user_id FROM analysis_schedules WHERE workspace_id=%s',UUID(wid))[0][0]==member.user_id
    assert team.query('SELECT license_workspace_id FROM team_projects WHERE workspace_id=%s',UUID(wid))[0][0]==owner.workspace_id
    assert c.post(f'/team/projects/{wid}/invitations',json={'email':'new@team-test.invalid','sharingAcknowledged':True}).status_code==403


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
