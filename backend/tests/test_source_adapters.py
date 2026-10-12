"""Synthetic provider contracts; no personal credentials or provider traffic."""
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
import gzip
import httpx
import pytest
from cryptography.fernet import Fernet
from app.integrations.sources.settings import SourceSettings
from app.integrations.sources.credentials import CredentialCipher, CredentialScope, CredentialUnavailable
from app.integrations.sources.http import ProviderHTTP, ProviderResponse
from app.integrations.sources.oauth import SourceOAuth
from app.integrations.sources.contracts import SourceProviderError


@pytest.fixture
def source_settings():
    return SourceSettings(enabled=True, public_api_url='http://localhost:8000/api', frontend_url='http://localhost:8000',
                          token_keys=(Fernet.generate_key().decode(),), google_client_id='test-google-client', google_client_secret='test-google-secret',
                          slack_client_id='test-slack-client', slack_client_secret='test-slack-secret',
                          notion_client_id='test-notion-client', notion_client_secret='test-notion-secret')


def test_source_configuration_is_independent_and_fail_closed(source_settings):
    source_settings.validate()
    assert SourceSettings().configured('gmail') is False
    for values in [{'token_keys': ()}, {'public_api_url': 'http://public.example.com'},
                   {'frontend_url': 'https://user:private@example.com/sources'}, {'max_resources': 21}, {'deadline_seconds': 1000}]:
        with pytest.raises(ValueError):
            replace(source_settings, **values).validate()
    assert 'test-google-secret' not in repr(source_settings)


@pytest.mark.parametrize('field', ['workspace_id', 'connection_id', 'provider', 'user_id'])
def test_encrypted_credentials_cannot_be_swapped(source_settings, field):
    scope = CredentialScope('w1', 'c1', 'gmail', 'user1')
    cipher = CredentialCipher(source_settings.token_keys)
    token = cipher.encrypt(scope, {'access_token': 'test-sensitive-value'})
    assert 'test-sensitive-value' not in token
    assert cipher.decrypt(scope, token)['access_token'] == 'test-sensitive-value'
    with pytest.raises(CredentialUnavailable):
        cipher.decrypt(replace(scope, **{field: 'different'}), token)


def test_credentials_support_rotation_and_reject_tampering(source_settings):
    old = source_settings.token_keys[0]; new = Fernet.generate_key().decode()
    scope = CredentialScope('w', 'c', 'notion', 'u')
    token = CredentialCipher((old,)).encrypt(scope, {'access_token': 'synthetic'})
    assert CredentialCipher((new, old)).decrypt(scope, token)['access_token'] == 'synthetic'
    with pytest.raises(CredentialUnavailable):
        CredentialCipher((new,)).decrypt(scope, token)
    with pytest.raises(CredentialUnavailable):
        CredentialCipher((old,)).decrypt(scope, token[:-10] + 'tampered')


@pytest.mark.parametrize('url', ['http://slack.com/api', 'https://evil.example/api', 'https://slack.com.evil.example/api',
                                'https://user:private@slack.com/api', 'https://slack.com:bad/api', 'https://slack.com/api#secret'])
def test_http_rejects_unsafe_destinations_without_requests(source_settings, url):
    calls = []
    client = ProviderHTTP(source_settings, transport=httpx.MockTransport(lambda r: calls.append(r)))
    with pytest.raises(SourceProviderError) as raised:
        client.request('GET', url)
    assert raised.value.code == 'invalid_provider_request' and not calls


def test_http_caps_body_and_rejects_compression_and_redirect(source_settings):
    for response, code in [
        (httpx.Response(200, stream=httpx.ByteStream(b'x' * 10_001)), 'response_too_large'),
        (httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=httpx.ByteStream(gzip.compress(b'body'))), 'unsupported_response_encoding'),
        (httpx.Response(302, headers={'Location': 'https://evil.example'}), 'provider_unavailable'),
    ]:
        calls = []
        def send(request):
            calls.append(request)
            assert request.headers['accept-encoding'] == 'identity'
            return response
        client = ProviderHTTP(replace(source_settings, max_response_bytes=10_000), transport=httpx.MockTransport(send))
        with pytest.raises(SourceProviderError) as raised:
            client.request('GET', 'https://slack.com/api/auth.test').checked()
        assert raised.value.code == code and len(calls) == 1


def test_http_request_and_absolute_budgets(source_settings):
    now = [0]
    client = ProviderHTTP(replace(source_settings, max_requests=2), clock=lambda: now[0], transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'ok': True})))
    client.request('GET', 'https://slack.com/api/auth.test'); client.request('GET', 'https://slack.com/api/auth.test')
    with pytest.raises(SourceProviderError) as raised:
        client.request('GET', 'https://slack.com/api/auth.test')
    assert raised.value.code == 'sync_budget_reached'
    client.requests = 0; now[0] = 121
    with pytest.raises(SourceProviderError):
        client.request('GET', 'https://slack.com/api/auth.test')


def test_provider_throttling_retains_the_provider_delay_and_redacts_body():
    with pytest.raises(SourceProviderError) as raised:
        ProviderResponse(429, {'retry-after': '121'}, b'PRIVATE_CONTENT_OR_CREDENTIAL').checked()
    assert raised.value.retry_after == 121
    assert 'PRIVATE' not in str(raised.value)
    with pytest.raises(SourceProviderError) as raised:
        ProviderResponse(403, {'x-ratelimit-remaining': '0', 'retry-after': '61'}, b'private').checked()
    assert raised.value.code == 'rate_limited' and raised.value.retry_after == 61


@pytest.mark.parametrize('provider', ['gmail', 'drive', 'slack', 'notion'])
def test_oauth_urls_request_only_the_intended_read_context(source_settings, provider):
    flow = SourceOAuth(provider, source_settings, ProviderHTTP(source_settings))
    query = parse_qs(urlsplit(flow.authorize_url('test-state', 'a'*64)).query)
    assert query['state'] == ['test-state']
    assert query['redirect_uri'] == [source_settings.callback(provider)]
    assert not any(secret in str(query) for secret in ['test-google-secret', 'test-slack-secret', 'test-notion-secret'])
    if provider in ('gmail', 'drive'):
        assert query['code_challenge_method'] == ['S256']
        assert 'readonly' in query['scope'][0] and 'modify' not in query['scope'][0]
    if provider == 'slack':
        assert query['user_scope'] == ['channels:read,channels:history']


def test_gmail_exchange_and_refresh_keep_account_binding(source_settings):
    calls = []
    def send(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            values = parse_qs(request.content.decode())
            if values['grant_type'] == ['authorization_code']:
                assert values['code_verifier'] == ['a'*64]
                return httpx.Response(200, json={'access_token': 'test-access', 'refresh_token': 'test-renewal', 'expires_in': 3600})
            assert values['refresh_token'] == ['test-renewal']
            return httpx.Response(200, json={'access_token': 'test-new-access', 'expires_in': 3600})
        assert request.headers['authorization'] == 'Bearer test-access'
        return httpx.Response(200, json={'emailAddress': 'test@example.invalid'})
    flow = SourceOAuth('gmail', source_settings, ProviderHTTP(source_settings, transport=httpx.MockTransport(send)))
    credentials, label = flow.exchange('test-code', 'a'*64)
    assert label == 'test@example.invalid'
    renewed = flow.refresh(credentials)
    assert renewed['account_id'] == credentials['account_id']
    assert renewed['access_token'] == 'test-new-access' and renewed['refresh_token'] == 'test-renewal'


def test_missing_google_offline_access_is_not_fake_connected_success(source_settings):
    flow = SourceOAuth('gmail', source_settings, ProviderHTTP(source_settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'access_token': 'test', 'expires_in': 3600}))))
    with pytest.raises(SourceProviderError) as raised:
        flow.exchange('test-code', 'a'*64)
    assert raised.value.code == 'offline_access_unavailable'

from app.integrations.sources.adapters import READERS, TextHTML
from app.services.source_sync import SourceProcessor, SourceService


def fixture_reader(settings,provider,handler,**credentials):
    return READERS[provider](settings,ProviderHTTP(settings,transport=httpx.MockTransport(handler)),{'access_token':'synthetic','account_id':'account',**credentials})


def test_slack_history_threads_cursor_links_and_no_private_channels(source_settings):
    calls=[]
    def send(request):
        method=request.url.path.split('/')[-1]; calls.append(method)
        if method=='conversations.list': return httpx.Response(200,json={'ok':True,'channels':[{'id':'C1','name':'product','is_member':True},{'id':'C2','name':'private','is_member':True,'is_private':True},{'id':'C3','name':'other','is_member':False}]})
        if method=='conversations.info': return httpx.Response(200,json={'ok':True,'channel':{'id':'C1','name':'product','is_member':True}})
        if method=='conversations.history':
            assert request.url.params['limit']=='15'
            return httpx.Response(200,json={'ok':True,'messages':[{'ts':'123.000001','text':'Feedback','user':'U1','reply_count':1}],'response_metadata':{'next_cursor':''}})
        if method=='conversations.replies': return httpx.Response(200,json={'ok':True,'messages':[{'ts':'123.000002','text':'Reply','user':'U2','thread_ts':'123.000001'}]})
        if method=='chat.getPermalink': return httpx.Response(200,json={'ok':True,'permalink':'https://example.slack.com/archives/C1/p123'})
        pytest.fail(method)
    reader=fixture_reader(source_settings,'slack',send)
    assert [r.id for r in reader.resources().resources]==['C1']
    page=reader.documents({'id':'C1','name':'#product'})
    assert page.cursor['threads']==['123.000001'] and page.delay_seconds==60
    reply=reader.documents({'id':'C1','name':'#product'},page.cursor)
    assert reply.cursor is None and 'Reply' in reply.documents[0].content
    assert all(x in ('conversations.list','conversations.info','conversations.history','conversations.replies','chat.getPermalink') for x in calls)


def test_slack_oauth_uses_user_credential_for_channel_replies(source_settings):
    def send(request):
        return httpx.Response(200,json={'ok':True,'access_token':'bot-not-used','authed_user':{'access_token':'user-used'},'team':{'id':'T1','name':'Test'}})
    credentials,_=SourceOAuth('slack',source_settings,ProviderHTTP(source_settings,transport=httpx.MockTransport(send))).exchange('code','v'*64)
    assert credentials['access_token']=='user-used' and credentials['account_id']=='T1'


def test_gmail_mime_html_attachments_label_pagination_and_account_dedupe(source_settings):
    import base64
    def send(request):
        if '/labels/' in request.url.path: return httpx.Response(200,json={'id':request.url.path.split('/')[-1],'name':'Support'})
        if request.url.path.endswith('/messages'):
            assert request.url.params['labelIds'] in ('L1','L2') and 'newer_than:30d' in request.url.params['q']
            return httpx.Response(200,json={'messages':[{'id':'msg1'}],'nextPageToken':'opaque+/=='})
        return httpx.Response(200,json={'id':'msg1','labelIds':['L1','L2'],'payload':{'mimeType':'multipart/mixed','headers':[{'name':'Subject','value':'Feedback'},{'name':'From','value':'person@example.invalid'}],'parts':[{'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(b'<p>Useful feedback</p><script>BAD</script>').decode()}},{'filename':'private.pdf','mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(b'ATTACHMENT').decode()}}]}})
    reader=fixture_reader(source_settings,'gmail',send)
    first=reader.documents({'id':'L1','name':'Support'}); second=reader.documents({'id':'L2','name':'Sales'})
    assert first.cursor['page']=='opaque+/==' and first.documents[0].external_id==second.documents[0].external_id
    assert 'Useful feedback' in first.documents[0].content and 'BAD' not in first.documents[0].content and 'ATTACHMENT' not in first.documents[0].content


def test_drive_selected_docs_export_text_files_and_rejects_binaries(source_settings):
    calls=[]
    def send(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/export'): return httpx.Response(200,content='Привет 👋'.encode())
        if request.url.params.get('alt')=='media': return httpx.Response(200,content=b'Text file')
        key=request.url.path.split('/')[-1]
        return httpx.Response(200,json={'id':key,'name':'Doc','mimeType':'application/pdf' if key=='pdf' else 'text/plain' if key=='txt' else 'application/vnd.google-apps.document','webViewLink':'https://docs.google.com/document/d/doc/edit','modifiedTime':'2026-10-12T00:00:00Z'})
    reader=fixture_reader(source_settings,'drive',send)
    assert reader.documents({'id':'doc','name':'Doc'}).documents[0].content=='Привет 👋'
    assert reader.documents({'id':'txt','name':'Text'}).documents[0].content=='Text file'
    with pytest.raises(SourceProviderError): reader.resource('pdf')
    assert not any('/permissions' in x for x in calls)


def test_notion_current_version_nested_blocks_and_opaque_continuation(source_settings,monkeypatch):
    monkeypatch.setattr('app.integrations.sources.http.time.sleep',lambda *_:None)
    def send(request):
        assert request.headers['notion-version']=='2026-03-11'
        if '/pages/' in request.url.path: return httpx.Response(200,json={'id':'p1','url':'https://notion.so/p1','properties':{'Name':{'type':'title','title':[{'plain_text':'Roadmap'}]}}})
        block=request.url.path.split('/')[-2]
        if block=='p1' and request.url.params.get('start_cursor')!='opaque+/=':
            return httpx.Response(200,json={'results':[{'id':'child','type':'paragraph','paragraph':{'rich_text':[{'plain_text':'Parent'}]},'has_children':True}],'has_more':True,'next_cursor':'opaque+/='})
        return httpx.Response(200,json={'results':[{'id':'text','type':'paragraph','paragraph':{'rich_text':[{'plain_text':'Nested' if block=='child' else 'Next page'}]}}],'has_more':False})
    reader=fixture_reader(source_settings,'notion',send)
    result=reader.documents({'id':'p1','name':'Roadmap'})
    assert result.cursor is None and all(text in result.documents[0].content for text in ('Parent','Nested','Next page'))


def test_github_selected_readme_issues_prs_and_repository_identity(source_settings):
    import base64
    def send(request):
        assert request.url.path.startswith('/repos/acme/project')
        if request.url.path.endswith('/readme'): return httpx.Response(200,json={'content':base64.b64encode(b'README context').decode(),'html_url':'https://github.com/acme/project/blob/main/README.md'})
        if request.url.path.endswith('/issues'): return httpx.Response(200,json=[{'number':5,'title':'Fix import','body':'Report','state':'closed','updated_at':'2026-10-12','user':{'login':'test'},'pull_request':{},'html_url':'https://github.com/acme/project/pull/5'}])
        return httpx.Response(200,json={'id':101,'full_name':'acme/project'})
    reader=fixture_reader(source_settings,'github',send,repository='acme/project',repository_id=101)
    first=reader.documents({'id':'101','name':'acme/project'})
    assert first.cursor['stage']=='issues' and first.documents[0].content=='README context'
    second=reader.documents({'id':'101','name':'acme/project'},first.cursor)
    assert second.cursor is None and 'State: closed' in second.documents[0].content
    # A new selected repo does not overwrite the prior repo's source rows.
    other=fixture_reader(source_settings,'github',send,repository='acme/project',repository_id=102)
    assert reader.document('readme','t','body').external_id!=other.document('readme','t','body').external_id


def test_cursor_ciphertext_is_not_a_credential_and_checkpoint_cancel_is_fenced(source_settings):
    binding=CredentialScope('w','c','gmail','u'); cipher=CredentialCipher(source_settings.token_keys)
    raw=cipher.encrypt(replace(binding,purpose='cursor'),{'resource':0,'page':None})
    with pytest.raises(CredentialUnavailable): cipher.decrypt(binding,raw)
    calls=[]
    class Jobs:
        def step(self,job,action,payload): calls.append((action,payload)); return {}
    processor=SourceProcessor(Jobs(),source_settings)
    job={'workspace_id':'w','connection_id':'c','provider':'gmail','user_id':'u','credential_blob':raw,'resources':[]}
    processor.process(job)
    assert calls==[('error',{'code':'authorization_lost','reconnect':True})]


def test_source_401_refreshes_only_once_and_keeps_account(source_settings):
    tokens=[]; saved=[]
    def send(request):
        if request.url.host=='oauth2.googleapis.com':
            tokens.append(request); return httpx.Response(200,json={'access_token':'fresh','expires_in':3600})
        if request.headers['authorization']=='Bearer synthetic': return httpx.Response(401,json={'error':'expired'})
        return httpx.Response(200,json={'labels':[{'id':'L1','name':'Support'}]})
    reader=fixture_reader(source_settings,'gmail',send,refresh_token='renewal')
    reader.persist=lambda value:saved.append(value)
    assert reader.resources().resources[0].id=='L1'
    assert len(tokens)==1 and saved[0]['account_id']=='account' and saved[0]['access_token']=='fresh'


def test_github_mints_repository_only_read_token(source_settings,monkeypatch):
    import json
    from app.services.source_sync import github_access
    from app.integrations.github import GitHubClient
    monkeypatch.setattr(GitHubClient,'_app_jwt',lambda self:'synthetic-app-jwt')
    def send(request):
        assert request.url.path=='/app/installations/9001/access_tokens'
        body=json.loads(request.content)
        assert body['repository_ids']==[101] and all(value=='read' for value in body['permissions'].values())
        return httpx.Response(201,json={'token':'synthetic-repository-token'})
    from types import SimpleNamespace
    result=github_access({'account_id':'a','installation_id':9001,'repository_id':101},SimpleNamespace(validate=lambda:None),ProviderHTTP(source_settings,transport=httpx.MockTransport(send)))
    assert result['access_token']=='synthetic-repository-token'


def test_slack_continues_by_time_bounds_without_expiring_history_cursor(source_settings):
    histories=[]
    def send(request):
        method=request.url.path.split('/')[-1]
        if method=='conversations.info': return httpx.Response(200,json={'ok':True,'channel':{'id':'C1','name':'product','is_member':True}})
        if method=='conversations.history':
            histories.append(request.url.params)
            return httpx.Response(200,json={'ok':True,'messages':[{'ts':'123.000001','text':'Feedback','user':'U1','reply_count':1}],'has_more':len(histories)==1,'response_metadata':{'next_cursor':'would-expire'} if len(histories)==1 else {}})
        if method=='conversations.replies':return httpx.Response(200,json={'ok':True,'messages':[],'has_more':False})
        return httpx.Response(200,json={'ok':True,'permalink':'https://example.slack.com/archives/C1/p123'})
    reader=fixture_reader(source_settings,'slack',send)
    page=reader.documents({'id':'C1','name':'#product'})
    reply=reader.documents({'id':'C1','name':'#product'},page.cursor)
    assert reply.cursor is not None
    reader.documents({'id':'C1','name':'#product'},reply.cursor)
    assert histories[1]['latest']=='123.000001' and histories[1]['oldest']==histories[0]['oldest'] and 'cursor' not in histories[1]


def test_invalid_unicode_is_a_redacted_provider_error():
    from app.integrations.sources.http import plain_text
    with pytest.raises(SourceProviderError) as error: plain_text('\ud800',maximum=100)
    assert error.value.code=='invalid_provider_response'


@pytest.mark.parametrize('code,expected',[('ratelimited','rate_limited'),('internal_error','provider_unavailable'),('channel_not_found','resource_unavailable')])
def test_slack_transient_errors_do_not_silently_skip_selected_context(source_settings,code,expected):
    reader=fixture_reader(source_settings,'slack',lambda r:httpx.Response(200,json={'ok':False,'error':code}))
    with pytest.raises(SourceProviderError) as error: reader.resources()
    assert error.value.code==expected


def test_remote_titles_get_editable_portable_file_names():
    from app.integrations.sources.contracts import SourceDocument
    from app.services.import_service import ImportService
    job={'provider':'drive','connection_id':'c1'}
    result=SourceProcessor.prepare(SourceDocument('account:file','Folder\\Notes/Feedback:\nUpdate','Context'),job)
    name=result['metadata']['fileName']
    assert not any(ch in name for ch in ('\\','/','\n',':'))
    # Vault's existing text-file editing path accepts the generated name.
    prepared=ImportService.prepare_content(format='txt',file_name=name,file_type='text/plain',file_size=7,content='Context')
    assert prepared.content=='Context'
