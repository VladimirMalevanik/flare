"""Cookie/OAuth/selection/worker acceptance against a real isolated tenant database."""
from dataclasses import replace
from uuid import UUID,uuid4
from urllib.parse import parse_qs,urlsplit
import base64
import os
import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from app.main import create_app
from app.config import Settings
from app.integrations.sources.settings import SourceSettings
from app.integrations.sources.http import ProviderHTTP
from app.models.source_connections import SourceJobs
from app.services.source_sync import SourceProcessor
from test_items_api import ApiEnvironment

pytestmark=pytest.mark.integration


@pytest.fixture
def environment():
    if not all(os.getenv(x) for x in ('DATABASE_URL','TEST_DATABASE_URL','WORKER_DATABASE_URL')): pytest.skip('Disposable restricted-role DB required')
    e=ApiEnvironment(os.environ['DATABASE_URL'],os.environ['TEST_DATABASE_URL'])
    configured=Settings(database_url=e.runtime_url,environment='test',cors_origins=['http://testserver'])
    application=create_app(configured)
    source_settings=SourceSettings(enabled=True,public_api_url='http://localhost:8425/api',frontend_url='http://localhost:8425',token_keys=(Fernet.generate_key().decode(),),google_client_id='test-client',google_client_secret='synthetic')
    application.state.source_settings=source_settings
    calls=[]
    def send(request):
        calls.append(request)
        assert request.url.host in ('oauth2.googleapis.com','gmail.googleapis.com')
        if request.url.host=='oauth2.googleapis.com': return httpx.Response(200,json={'access_token':'synthetic-access','refresh_token':'synthetic-renewal','expires_in':3600})
        if request.url.path.endswith('/profile'): return httpx.Response(200,json={'emailAddress':'test@example.invalid'})
        if request.url.path.endswith('/labels'): return httpx.Response(200,json={'labels':[{'id':'L1','name':'Support'}]})
        if '/labels/' in request.url.path: return httpx.Response(200,json={'id':'L1','name':'Support'})
        if request.url.path.endswith('/messages'): return httpx.Response(200,json={'messages':[{'id':'msg1'}]})
        return httpx.Response(200,json={'id':'msg1','labelIds':['L1'],'payload':{'mimeType':'text/plain','headers':[{'name':'Subject','value':'Customer feedback'}],'body':{'data':base64.urlsafe_b64encode(b'Customer needs import').decode()}}})
    factory=lambda settings:ProviderHTTP(settings,transport=httpx.MockTransport(send))
    application.state.source_http_factory=factory
    with TestClient(application,headers={'Origin':'http://testserver'}) as client:
        email=uuid4().hex+'@source-test.invalid'
        r=client.post('/auth/register',json={'email':email,'password':'password','name':'Sources Test','termsAccepted':True,'privacyAccepted':True})
        assert r.status_code==201,r.text
        with psycopg.connect(e.admin_url) as c:
            row=c.execute('SELECT id,initial_workspace_id FROM auth_users WHERE email=%s',(email,)).fetchone()
        e.user_ids.add(row[0]); e.workspace_ids.add(row[1])
        try: yield client,application,source_settings,factory,calls,e
        finally:
            with psycopg.connect(e.admin_url) as c:
                for table in ('source_items','source_auth_states','source_jobs','source_connections'):
                    c.execute(f'DELETE FROM {table} WHERE workspace_id=ANY(%s)',(list(e.workspace_ids),))
            e.cleanup()


def connect(client):
    r=client.post('/integrations/sources/gmail/connect',json={}); assert r.status_code==200,r.text
    url=r.json()['url']; state=parse_qs(urlsplit(url).query)['state'][0]
    r=client.get('/integrations/sources/gmail/callback',params={'code':'synthetic-code','state':state},follow_redirects=False)
    assert r.status_code==303 and r.headers['location']=='http://localhost:8425/sources?source=gmail&connection=success'
    connection=client.get('/integrations/sources').json()['connections'][0]
    return connection,state


def test_real_oauth_single_use_selection_durable_sync_vault_no_ai(environment):
    client,app,settings,factory,calls,e=environment
    connection,state=connect(client); id=connection['id']
    assert connection['accountLabel']=='test@example.invalid'
    assert 'synthetic-access' not in str(connection) and 'credentialBlob' not in str(connection)
    replay=client.get('/integrations/sources/gmail/callback',params={'code':'synthetic-code','state':state},follow_redirects=False)
    assert replay.status_code==303 and 'failed' in replay.headers['location']
    assert len([r for r in calls if r.url.host=='oauth2.googleapis.com'])==1
    resource=client.get('/integrations/sources/connection/'+id+'/resources').json()
    assert resource['resources']==[{'id':'L1','name':'Support','kind':'label'}]
    payload={'expectedRevision':resource['scopeRevision'],'resourceIds':['L1'],'shareWithWorkspace':False}
    r=client.post('/integrations/sources/connection/'+id+'/selection',json=payload); assert r.status_code==409
    payload['shareWithWorkspace']=True
    r=client.post('/integrations/sources/connection/'+id+'/selection',json=payload); assert r.status_code==200,r.text
    jobs=SourceJobs(os.environ['WORKER_DATABASE_URL']); job=jobs.claim(['gmail']); assert job['connection_id']==id
    SourceProcessor(jobs,settings,http_factory=factory).process(job)
    items=client.get('/items').json(); assert len(items)==1 and 'Customer needs import' in items[0]['content']
    assert items[0]['sourceUrl']=='https://mail.google.com/mail/u/0/#all/msg1'
    result=client.get('/integrations/sources').json()['connections'][0]; assert result['lastResult']['added']==1
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM analysis_jobs WHERE workspace_id=ANY(%s)',(list(e.workspace_ids),)).fetchone()==(0,)
    r=client.post('/integrations/sources/connection/'+id+'/disconnect',json={}); assert r.status_code==200
    assert len(client.get('/items').json())==1


def test_sources_disabled_remains_truthful_private_and_auth_origin_guards(environment):
    client,app,settings,*_=environment
    assert client.post('/integrations/sources/gmail/connect',headers={'Origin':'https://evil.invalid'},json={}).status_code==403
    app.state.source_settings=SourceSettings()
    response=client.get('/integrations/sources')
    assert response.status_code==200 and all(not p['available'] for p in response.json()['providers'])
    assert client.post('/integrations/sources/gmail/connect',json={}).status_code==503
    client.cookies.clear()
    assert client.get('/integrations/sources').status_code==401
