"""Read-only source authorization and leased snapshot publication."""
from dataclasses import replace
from hashlib import sha256
import json
import secrets
import time
from uuid import uuid4
from app.integrations.sources.credentials import CredentialScope, CredentialCipher, CredentialUnavailable
from app.integrations.sources.contracts import SourceProviderError, DocumentPage
from app.integrations.sources.http import ProviderHTTP, identifier, plain_text
from app.integrations.sources.adapters import READERS, obj
from app.integrations.sources.oauth import SourceOAuth
from app.integrations.github import GitHubClient
from app.models.github_connections import GitHubConnectionRepository
from app.models.source_connections import SourceStateError
from app.services.import_service import ImportService, ImportValidationError


def scope(identity, connection, purpose='credentials'):
    return CredentialScope(str(identity.workspace_id),str(connection['id']),connection['provider'],identity.user_id,purpose)


def github_access(credentials, configured, http):
    if configured is None: raise SourceProviderError('source_not_enabled')
    # A short-lived token is restricted to exactly the already authorized repository.
    response=obj(http.request('POST',f"https://api.github.com/app/installations/{int(credentials['installation_id'])}/access_tokens",
        headers={'Authorization':'Bearer '+GitHubClient(configured)._app_jwt(),'X-GitHub-Api-Version':'2022-11-28'},
        json_body={'repository_ids':[int(credentials['repository_id'])],
                   'permissions':{'metadata':'read','contents':'read','issues':'read','pull_requests':'read'}}).json())
    return credentials|{'access_token':plain_text(response.get('token'),maximum=6000)}


def reader_for(provider, credentials, settings, http, github_settings=None, persist=None):
    if provider=='github': credentials=github_access(credentials,github_settings,http)
    elif credentials.get('expires_at') and credentials['expires_at']<=time.time()+60:
        credentials=SourceOAuth(provider,settings,http).refresh(credentials)
        if persist: persist(credentials)
    return READERS[provider](settings,http,credentials)


class SourceService:
    def __init__(self, repository, settings, github_settings=None, http_factory=ProviderHTTP):
        self.repository,self.settings,self.github_settings,self.http_factory=repository,settings,github_settings,http_factory
        self.cipher=CredentialCipher(settings.token_keys)
    def policy(self):
        return {'syncIntervalSeconds':self.settings.sync_interval_seconds,'workspaceBytes':self.settings.workspace_bytes}
    def configured(self,provider):
        if not self.settings.configured(provider) or provider=='github' and self.github_settings is None:
            raise SourceProviderError('source_not_enabled')
    def connect(self,provider):
        self.configured(provider)
        connection=self.repository.action('reserve',uuid4(),{'provider':provider})
        binding=scope(self.repository.identity,connection)
        if provider=='github':
            with self.repository.database.workspace_transaction(self.repository.identity) as database:
                existing=GitHubConnectionRepository(database).get()
            if not existing or existing.status!='connected' or not existing.repository_id:
                raise SourceStateError('github_repository_required')
            credentials={'account_id':str(existing.account_id),'installation_id':existing.installation_id,
                         'repository_id':existing.repository_id,'repository':existing.repository_full_name}
            # Check content permissions before representing this as connected.
            reader=reader_for(provider,credentials,self.settings,self.http_factory(self.settings),self.github_settings)
            reader.resource(str(existing.repository_id))
            self.repository.action('complete_github',connection['id'],{
                'expectedRevision':connection['scopeRevision'],'credentialBlob':self.cipher.encrypt(binding,credentials),
                'accountLabel':existing.repository_full_name,'installationId':existing.installation_id,
                'repositoryId':existing.repository_id,'policy':self.policy()})
            return {'connected':True}
        state,verifier=secrets.token_urlsafe(32),secrets.token_urlsafe(48)
        self.repository.action('state',connection['id'],{'expectedRevision':connection['scopeRevision'],
            'stateHash':sha256(state.encode()).hexdigest(),'pendingBlob':self.cipher.encrypt(replace(binding,purpose='oauth_state'),{'verifier':verifier})})
        return {'url':SourceOAuth(provider,self.settings,self.http_factory(self.settings)).authorize_url(state,verifier)}
    def callback(self,provider,state,code):
        self.configured(provider)
        connection=self.repository.action('consume_state',payload={'stateHash':sha256(state.encode()).hexdigest(),'provider':provider})
        binding=scope(self.repository.identity,connection)
        pending=self.cipher.decrypt(replace(binding,purpose='oauth_state'),connection['pendingBlob'])
        credentials,label=SourceOAuth(provider,self.settings,self.http_factory(self.settings)).exchange(code,pending['verifier'])
        self.repository.action('complete',connection['id'],{'expectedRevision':connection['scopeRevision'],
            'credentialBlob':self.cipher.encrypt(binding,credentials),'accountLabel':label,'policy':self.policy()})
    def private(self,connection_id):
        connection=self.repository.action('credentials',connection_id)
        self.configured(connection['provider'])
        credentials=self.cipher.decrypt(scope(self.repository.identity,connection),connection['credentialBlob'])
        return connection,credentials
    def reader(self,connection,credentials):
        def persist(value):
            self.repository.action('token_refresh',connection['id'],{'expectedRevision':connection['scopeRevision'],
                'credentialBlob':self.cipher.encrypt(scope(self.repository.identity,connection),value)})
        return reader_for(connection['provider'],credentials,self.settings,self.http_factory(self.settings),self.github_settings,persist)
    def resources(self,connection_id,cursor=None):
        connection,credentials=self.private(connection_id)
        result=self.reader(connection,credentials).resources(cursor)
        return {'resources':[x.public() for x in result.resources],'cursor':result.cursor,'scopeRevision':connection['scopeRevision']}
    def select(self,connection_id,revision,ids,consent):
        connection,credentials=self.private(connection_id)
        if revision!=connection['scopeRevision']: raise SourceStateError('selection_changed')
        if ids and not consent: raise SourceStateError('selection_consent_required')
        if len(ids)>self.settings.max_resources or len(set(ids))!=len(ids): raise SourceStateError('invalid_request')
        reader=self.reader(connection,credentials)
        resources=[reader.resource(identifier(key)).public() for key in ids]
        return self.repository.action('select',connection_id,{'expectedRevision':revision,'resources':resources,'shareWithWorkspace':consent})


class SourceProcessor:
    def __init__(self,jobs,settings,github_settings=None,http_factory=ProviderHTTP):
        self.jobs,self.settings,self.github_settings,self.http_factory=jobs,settings,github_settings,http_factory
        self.cipher=CredentialCipher(settings.token_keys)
    def process(self,job):
        binding=CredentialScope(job['workspace_id'],job['connection_id'],job['provider'],job['user_id'])
        cursor_scope=replace(binding,purpose='cursor')
        try:
            credentials=self.cipher.decrypt(binding,job['credential_blob'])
            state=self.cipher.decrypt(cursor_scope,job['cursor_blob']) if job.get('cursor_blob') else {'resource':0,'page':None}
            resources=job['resources']; index=state['resource']
            if type(index) is not int or not 0<=index<len(resources): raise SourceProviderError('invalid_cursor',reconnect=True)
            def persist(value): self.jobs.step(job,'credentials',{'credentialBlob':self.cipher.encrypt(binding,value)})
            reader=reader_for(job['provider'],credentials,self.settings,self.http_factory(self.settings),self.github_settings,persist)
            try:
                page=reader.documents(resources[index],state.get('page'))
            except SourceProviderError as error:
                if error.code not in ('resource_unavailable','document_too_large','response_too_large'):
                    raise
                # Unsupported or removed resources are reported; other selections can finish.
                page=DocumentPage((),skipped=1)
            following={'resource':index,'page':page.cursor} if page.cursor else ({'resource':index+1,'page':None} if index+1<len(resources) else None)
            documents=[]; skipped=page.skipped
            for document in page.documents:
                try: documents.append(self.prepare(document,job))
                except (ImportValidationError,SourceProviderError): skipped+=1
            self.jobs.step(job,'publish',{'documents':documents,'skipped':skipped,'delay':page.delay_seconds,
                'cursorBlob':self.cipher.encrypt(cursor_scope,following) if following else None})
        except CredentialUnavailable:
            self.jobs.step(job,'error',{'code':'authorization_lost','reconnect':True})
        except SourceProviderError as error:
            self.jobs.step(job,'error',{'code':error.code,'reconnect':error.reconnect,'delay':min(error.retry_after or 60,2_147_483_647)})
        except SourceStateError as error:
            if error.code=='workspace_storage_limit': self.jobs.step(job,'error',{'code':error.code,'reconnect':True})
            elif error.code not in ('lease_lost','authorization_lost','repository_changed'): raise
    @staticmethod
    def prepare(document,job):
        raw=document.content.encode('utf-8')
        prepared=ImportService.prepare_content(format='txt',file_name='source.txt',file_type='text/plain',file_size=len(raw),content=document.content)
        title=('['+job['provider'].title()+'] '+document.title)[:300]
        metadata=document.metadata|{'sourceType':'file','fileName':title.replace('/','-')+'.txt','fileType':'text/plain',
            'fileSize':len(raw),'sourceProvider':job['provider'],'sourceConnectionId':job['connection_id'],'externalId':document.external_id}
        hash_value=sha256(json.dumps([title,prepared.content,document.source_url,metadata],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return {'externalId':document.external_id,'title':title,'url':document.source_url,'hash':hash_value,'contentHash':prepared.content_hash,
            'metadata':metadata,'chunks':[{'ordinal':i,'content':chunk.content,'locator':chunk.locator|{'sourceProvider':job['provider'],'externalId':document.external_id}} for i,chunk in enumerate(prepared.chunks)]}
