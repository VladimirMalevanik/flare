"""Synthetic first-party journeys on the disposable restricted-role database."""
import os
from uuid import UUID, uuid4
import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient
from app.models.database import Database
from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthService, EmailDeliveryFailed
from app.services.attribution_service import AttributionService, normalize_touch, reference_digest
from test_items_api import ApiEnvironment

# Explicit nonproduction fixture. These are NOT deployment recommendations.
POLICY = {'enabled':True,'revision':'nonproduction-v1','notice_id':'synthetic-opt-in',
 'eligibility':'explicit-opt-in','cleanup_owner':'synthetic-test','lookback_seconds':3600,'cookie_seconds':3600,
 'raw_seconds':3600,'linked_seconds':864000,'fact_seconds':864000,'global_hour':1000,'network_hour':1000,
 'reference_limit':20,'visitor_limit':1000,'budget_limit':1000,'deadline_ms':500,'min_cohort':2,'report_window_days':30,
 'report_calendar':'UTC-v1','tokens':{'utm_source':['alpha','beta'],'utm_medium':['test'],'utm_campaign':['fixture'],
 'utm_content':['one'],'ref':['approved'],'referrer_domain':['example.org']}}


def configure(admin, **changes):
    values=POLICY | changes
    with psycopg.connect(admin) as c:
        c.execute('UPDATE public.growth_policy SET '+','.join(k+'=%s' for k in values),
                  tuple(Jsonb(v) if isinstance(v,dict) else v for v in values.values()))
        c.execute('DELETE FROM public.acquisition_visitors')
        c.execute('DELETE FROM public.acquisition_budgets')


@pytest.fixture
def enabled_growth_policy():
    """Enable only an explicit nonproduction policy, restoring the prior row."""
    admin = os.getenv('TEST_DATABASE_URL')
    if not admin:
        pytest.skip('Disposable migrated PostgreSQL required')
    with psycopg.connect(admin, row_factory=dict_row) as c:
        previous = c.execute('SELECT * FROM public.growth_policy').fetchone()
    configure(admin)
    try:
        yield
    finally:
        with psycopg.connect(admin) as c:
            c.execute('UPDATE public.growth_policy SET '+','.join(k+'=%s' for k in previous),
                      tuple(Jsonb(v) if isinstance(v,dict) else v for v in previous.values()))
            c.execute('DELETE FROM public.acquisition_visitors')
            c.execute('DELETE FROM public.acquisition_budgets')


@pytest.fixture
def growth(enabled_growth_policy):
    if not os.getenv('TEST_DATABASE_URL') or not os.getenv('DATABASE_URL'):
        pytest.skip('Disposable migrated PostgreSQL required')
    db=Database(os.environ['DATABASE_URL']);db.open()
    e=ApiEnvironment(os.environ['DATABASE_URL'],os.environ['TEST_DATABASE_URL'])
    service=AuthService(db)
    def account(reference=None):
        token=service.register(uuid4().hex+'@growth.invalid','synthetic-long-password','Synthetic',acquisition_reference=reference)
        user=service.current(token);e.user_ids.add(user.user_id);e.workspace_ids.add(user.workspace_id)
        return user,token
    yield db,e,service,account
    with psycopg.connect(e.admin_url) as c:
        c.execute('DELETE FROM public.acquisition_visitors');c.execute('DELETE FROM public.acquisition_budgets')
    db.close();e.cleanup()


def row(e,user):
    with psycopg.connect(e.admin_url,row_factory=dict_row) as c:
        return c.execute('''SELECT a.*,u.verification_provenance AS verification,u.email_verified_at AS verified_at
            FROM public.signup_attribution a JOIN public.auth_users u ON u.id=a.user_id WHERE user_id=%s''',(user.user_id,)).fetchone()


def touch(db,reference=None,source=None):
    return AttributionService(db).touch(reference=reference,peer='synthetic-peer',
       touch={'landing_route':'/register'} | ({'utm_source':source} if source else {}),revision='nonproduction-v1')


@pytest.mark.parametrize('payload',[{'landing_route':'/','email':'hidden'}, {'landing_route':'/','utm_source':'%61'},
 {'landing_route':'/','utm_source':'x'*81},{'landing_route':'/private/id'}, {'landing_route':'/','utm_source':False}])
def test_minimization_rejects_unsafe(payload):
    with pytest.raises(ValueError):normalize_touch(payload)


def test_first_last_direct_freeze_login_replay_shared_device(growth):
    db,e,auth,account=growth
    ref=touch(db,source='alpha'); assert ref
    assert touch(db,ref)==ref
    assert touch(db,ref,'beta')==ref
    user,_=account(ref);saved=row(e,user)
    assert saved['first_touch']['utm_source']=='alpha' and saved['last_touch']['utm_source']=='beta'
    assert saved['eligibility']=='eligible' and saved['verification']=='bypassed'
    assert touch(db,ref,'alpha') is None  # consumed references cannot be recreated
    newref=touch(db,source='alpha')
    auth.login(user.email,'synthetic-long-password')
    with db.workspace_transaction(user.identity) as c:c.execute('SELECT public.acquisition_freeze(%s)',(reference_digest(newref),))
    assert row(e,user)==saved
    second,_=account(ref);assert row(e,second)['eligibility']=='unknown'
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.acquisition_visitors WHERE reference_hash=%s',(reference_digest(ref),)).fetchone()==(0,)


def test_direct_to_campaign_unknown_ref_and_expiry(growth):
    db,e,_,account=growth
    assert touch(db,source='not-approved') is None
    ref=touch(db);assert ref;assert touch(db,ref,'alpha')==ref
    user,_=account(ref);saved=row(e,user)
    assert 'utm_source' not in saved['first_touch'] and saved['last_touch']['utm_source']=='alpha'
    ref=touch(db,source='beta')
    with psycopg.connect(e.admin_url) as c:c.execute('UPDATE public.acquisition_visitors SET expires_at=now()-interval \'1 second\'')
    expired,_=account(ref);assert row(e,expired)['eligibility']=='unknown'
    unknown,_=account(str(uuid4()));assert row(e,unknown)['eligibility']=='unknown'


def test_optional_linkage_outage_and_durable_smtp_truth(growth,monkeypatch):
    db,e,auth,account=growth
    monkeypatch.setattr('app.services.attribution_service.reference_digest',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic')))
    user,_=account();assert row(e,user) is None
    email=uuid4().hex+'@growth.invalid'
    verification=AuthService(db,email_verification_required=True,app_public_url='http://localhost')
    with pytest.raises(EmailDeliveryFailed):verification.register(email,'synthetic-long-password','Synthetic')
    with psycopg.connect(e.admin_url,row_factory=dict_row) as c:
        saved=c.execute('SELECT id,initial_workspace_id FROM public.auth_users WHERE email=%s',(email,)).fetchone()
        e.user_ids.add(saved['id']);e.workspace_ids.add(saved['initial_workspace_id'])
        assert c.execute('SELECT verification_provenance FROM public.auth_users WHERE id=%s',(saved['id'],)).fetchone()['verification_provenance']=='pending'


def test_actual_verification_other_device_and_replay(growth):
    db,e,_,_=growth
    class Mail:
        def send(self,**kwargs):self.text=kwargs['text']
    mail=Mail();auth=AuthService(db,email_verification_required=True,email_sender=mail,app_public_url='http://localhost')
    token=auth.register(uuid4().hex+'@growth.invalid','synthetic-long-password','Synthetic')
    user=auth.current(token);e.user_ids.add(user.user_id);e.workspace_ids.add(user.workspace_id)
    import re
    verification=re.search(r'token=([A-Za-z0-9_-]+)',mail.text).group(1)
    auth.verify_email(verification)
    assert row(e,user)['verification']=='actual' and row(e,user)['verified_at'] is not None
    from app.services.auth_service import VerificationInvalid
    with pytest.raises(VerificationInvalid):auth.verify_email(verification)


def test_global_reference_storage_caps_cleanup(growth):
    db,e,_,_=growth
    configure(e.admin_url,global_hour=3,network_hour=3,visitor_limit=2,reference_limit=1)
    assert touch(db);assert touch(db);assert touch(db) is None
    assert touch(db) is None
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.acquisition_visitors').fetchone()==(2,)
        c.execute("UPDATE public.acquisition_visitors SET expires_at=now()-interval '1 second'")
        assert c.execute('SELECT public.growth_cleanup(1)').fetchone()[0]['visitors']==1
        assert c.execute('SELECT public.growth_cleanup(1)').fetchone()[0]['visitors']==1


def test_anonymous_api_invalid_duplicate_off_outage_and_cookie(growth):
    db,e,_,_=growth
    settings=Settings(database_url=None,cors_origins=['http://testserver'],environment='test',email_verification_required=False)
    with TestClient(create_app(settings,database=db)) as client:
        h={'Origin':'http://testserver'}
        assert client.get('/acquisition/policy').json()['enabled']
        for raw in ('{"touch":{},"touch":{},"revision":"nonproduction-v1","eligible":true}', 'x'*1025):
            assert client.post('/acquisition/touch',content=raw,headers=h).status_code==202
            assert not client.cookies.get('flare_acquisition')
        assert client.post('/acquisition/touch',json={'touch':{'landing_route':'/','utm_source':'alpha'},'revision':'nonproduction-v1','eligible':True},headers=h).status_code==202
        assert client.cookies.get('flare_acquisition')
        assert client.post('/acquisition/forget',headers=h).status_code==204
        assert not client.cookies.get('flare_acquisition')
        with psycopg.connect(e.admin_url) as c:c.execute('UPDATE public.growth_policy SET enabled=false')
        assert client.get('/acquisition/policy').json()=={'enabled':False}
        assert client.get('/analytics/events').status_code==401


def test_network_bucket_storage_churn_and_null_batches_are_bounded(growth):
    db,e,_,_=growth
    configure(e.admin_url,budget_limit=3)
    collector=AttributionService(db)
    for peer in ('network-one','network-two'):
        assert collector.touch(reference=None,peer=peer,touch={'landing_route':'/'},revision=POLICY['revision'])
    assert collector.touch(reference=None,peer='new-network',touch={'landing_route':'/'},revision=POLICY['revision']) is None
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.acquisition_budgets').fetchone()==(3,)
        for function in ('growth_cleanup','growth_reconcile'):
            with pytest.raises(psycopg.errors.RaiseException),c.transaction():
                c.execute('SELECT public.'+function+'(NULL)')
        c.execute("UPDATE public.acquisition_budgets SET hour=now()-interval '2 hours'")
        assert c.execute('SELECT public.growth_cleanup(3)').fetchone()[0]['budgets']==3
    assert collector.touch(reference=None,peer='new-network',touch={'landing_route':'/'},revision=POLICY['revision'])


def test_login_logout_and_optional_collector_outage_do_not_cross_accounts(growth,monkeypatch):
    db,e,_,account=growth
    user,_=account()
    settings=Settings(database_url=None,cors_origins=['http://testserver'],environment='test',email_verification_required=False)
    with TestClient(create_app(settings,database=db)) as client:
        h={'Origin':'http://testserver'}
        payload={'touch':{'landing_route':'/'},'revision':POLICY['revision'],'eligible':True}
        assert client.post('/acquisition/touch',json=payload,headers={'Origin':'http://evil.invalid'}).status_code==403
        client.post('/acquisition/touch',json=payload,headers=h)
        assert client.cookies.get('flare_acquisition')
        response=client.post('/auth/login',json={'email':user.email,'password':'synthetic-long-password'},headers=h)
        assert response.status_code==200 and not client.cookies.get('flare_acquisition')
        client.post('/acquisition/touch',json=payload,headers=h)
        assert not client.cookies.get('flare_acquisition')
        assert client.post('/auth/logout',headers=h).status_code==204
        monkeypatch.setattr(AttributionService,'policy',lambda self:(_ for _ in ()).throw(RuntimeError('synthetic outage')))
        assert client.post('/acquisition/touch',json=payload,headers=h).status_code==202
        response=client.post('/auth/register',json={'email':uuid4().hex+'@growth.invalid','name':'Synthetic','password':'synthetic-long-password','termsAccepted':True,'privacyAccepted':True},headers=h)
        # Auth has an independent policy; optional collection cannot alter it.
        assert response.status_code==201,response.text
        saved=client.get('/auth/me').json()
        e.user_ids.add(saved['user']['id']);e.workspace_ids.add(UUID(saved['workspace']['id']))


@pytest.mark.parametrize('outage',['locked','failing'])
def test_optional_snapshot_failure_cannot_rollback_signup_or_rebuild_on_login(growth,outage):
    db,e,auth,account=growth
    ref=touch(db,source='alpha')
    blocker=psycopg.connect(e.admin_url)
    try:
        if outage=='locked':
            blocker.execute('LOCK TABLE public.signup_attribution IN ACCESS EXCLUSIVE MODE')
        else:
            blocker.execute("""CREATE FUNCTION public.synthetic_signup_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'synthetic optional sink outage'; END $$""")
            blocker.execute('CREATE TRIGGER synthetic_signup_failure BEFORE INSERT ON public.signup_attribution FOR EACH ROW EXECUTE FUNCTION public.synthetic_signup_failure()')
            blocker.commit()
        user,_=account(ref)
    finally:
        blocker.rollback();blocker.close()
        if outage=='failing':
            with psycopg.connect(e.admin_url) as c:
                c.execute('DROP TRIGGER synthetic_signup_failure ON public.signup_attribution')
                c.execute('DROP FUNCTION public.synthetic_signup_failure()')
    assert row(e,user) is None
    assert auth.current(auth.login(user.email,'synthetic-long-password')).user_id==user.user_id
    with db.workspace_transaction(user.identity) as c:
        c.execute('SELECT public.acquisition_freeze(%s)',(reference_digest(ref),))
    assert row(e,user) is None
    # Durable account and verification exist independently of optional measurement.
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT verification_provenance FROM public.auth_users WHERE id=%s',(user.user_id,)).fetchone()==('bypassed',)


@pytest.mark.parametrize('failure',[False,True])
def test_optional_hook_preserves_shorter_auth_statement_timeout(growth,monkeypatch,failure):
    from contextlib import contextmanager
    from app.models.auth import AuthRepository
    db,e,_,account=growth
    original_connection=db.connection
    @contextmanager
    def bounded_connection():
        with original_connection() as c:
            c.execute("SET LOCAL statement_timeout='150ms'")
            yield c
    monkeypatch.setattr(db,'connection',bounded_connection)
    original_insert=AuthRepository.insert_session
    observed=[]
    def insert(repository,*args):
        observed.append(repository.connection.execute('SHOW statement_timeout').fetchone()['statement_timeout'])
        return original_insert(repository,*args)
    monkeypatch.setattr(AuthRepository,'insert_session',insert)
    if failure:
        monkeypatch.setattr('app.services.attribution_service.reference_digest',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic')))
    account()
    assert observed==['150ms']
