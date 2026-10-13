"""Selected-resource readers. No provider writes, attachments or AI calls."""
import base64
import json
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import time
from urllib.parse import quote, urlsplit
from .contracts import Resource, ResourcePage, SourceDocument, DocumentPage, SourceProviderError
from .http import ProviderHTTP, identifier, plain_text, next_cursor
from .settings import SourceSettings
from .oauth import SourceOAuth


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        if tag in ('p','div','br','li','tr') and not self.hidden: self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.hidden = max(0,self.hidden-1)
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def text_html(value):
    parser=TextHTML(); parser.feed(value); return ''.join(parser.parts).strip()


def obj(value):
    if not isinstance(value,dict): raise SourceProviderError('invalid_provider_response')
    return value


def rows(value, key, maximum=100):
    result=obj(value).get(key,[])
    if not isinstance(result,list) or len(result)>maximum or any(not isinstance(x,dict) for x in result):
        raise SourceProviderError('invalid_provider_response')
    return result


def source_url(value, hosts):
    if not value: return None
    value=plain_text(value,maximum=2000)
    parsed=urlsplit(value)
    if parsed.scheme!='https' or not parsed.hostname or not any(parsed.hostname==host or parsed.hostname.endswith('.'+host) for host in hosts) or parsed.username or parsed.password:
        raise SourceProviderError('invalid_provider_response')
    return value


class Reader:
    def __init__(self, settings: SourceSettings, http: ProviderHTTP, credentials: dict):
        self.settings,self.http,self.credentials=settings,http,credentials
        self.persist=None
        self.refreshed=False
    def request(self,method,url,params=None,headers=None,json_body=None):
        token=plain_text(self.credentials.get('access_token'),maximum=6000)
        if any(ord(c)<32 for c in token): raise SourceProviderError('authorization_lost',reconnect=True)
        response=self.http.request(method,url,params=params,json_body=json_body,headers={'Authorization':'Bearer '+token,**(headers or {})})
        if response.status==401 and not self.refreshed and self.credentials.get('refresh_token'):
            self.refreshed=True
            provider=next(name for name,reader in READERS.items() if isinstance(self,reader))
            self.credentials=SourceOAuth(provider,self.settings,self.http).refresh(self.credentials)
            if self.persist: self.persist(self.credentials)
            return self.request(method,url,params,headers,json_body)
        return response
    def get(self,url,params=None,headers=None):
        return self.request('GET',url,params,headers)
    def document(self,key,title,content,url=None,metadata=None):
        content=plain_text(content,maximum=self.settings.max_document_bytes)
        title=plain_text(title,maximum=1200)[:280]
        account=sha256((str(self.credentials['account_id'])+(':'+str(self.credentials['repository_id']) if 'repository_id' in self.credentials else '')).encode()).hexdigest()[:24]
        return SourceDocument(account+':'+identifier(key),title,content,url,metadata or {})


class SlackReader(Reader):
    def api(self,method,params):
        value=obj(self.get('https://slack.com/api/'+method,params).json())
        if value.get('ok') is not True:
            code=value.get('error')
            if code in ('invalid_auth','token_revoked','token_expired','missing_scope','not_allowed_token_type','not_authed','account_inactive'):
                raise SourceProviderError('authorization_lost',reconnect=True)
            if code=='ratelimited': raise SourceProviderError('rate_limited',retry_after=60)
            if code not in ('channel_not_found','thread_not_found','access_denied','no_permission','not_in_channel'):
                raise SourceProviderError('provider_unavailable',retry_after=60)
            raise SourceProviderError('resource_unavailable')
        return value
    def resources(self,cursor=None):
        value=self.api('conversations.list',{'types':'public_channel','exclude_archived':'true','limit':100,**({'cursor':cursor} if cursor else {})})
        channels=rows(value,'channels')
        return ResourcePage(tuple(Resource(identifier(x.get('id')),'#'+plain_text(x.get('name'),maximum=300),'channel') for x in channels if x.get('is_member') is True and not x.get('is_private')),next_cursor(obj(value.get('response_metadata',{})).get('next_cursor')))
    def resource(self,key):
        channel=obj(self.api('conversations.info',{'channel':identifier(key)}).get('channel'))
        if channel.get('is_member') is not True or channel.get('is_private') or channel.get('is_archived') or channel.get('id')!=key:
            raise SourceProviderError('resource_unavailable')
        return Resource(key,'#'+plain_text(channel.get('name'),maximum=300),'channel')
    def documents(self,resource,cursor=None):
        cursor=cursor or {}; channel=resource['id']; self.resource(channel)
        threads=cursor.get('threads',[])
        if not isinstance(threads,list) or len(threads)>15: raise SourceProviderError('invalid_provider_response')
        params={'channel':channel,'limit':self.settings.page_items}
        snapshot=cursor.get('snapshot') or str(time.time())
        oldest=cursor.get('oldest') or str(time.time()-self.settings.lookback_days*86400)
        latest=cursor.get('latest') or snapshot
        if threads:
            params.update(ts=threads[0],latest=snapshot)
            if cursor.get('replyAfter'): params['oldest']=cursor['replyAfter']
            value=self.api('conversations.replies',params)
        else:
            params.update(oldest=oldest,latest=latest)
            value=self.api('conversations.history',params)
        messages=rows(value,'messages',15)
        pending=bool(value.get('has_more')) or bool(next_cursor(obj(value.get('response_metadata',{})).get('next_cursor')))
        # Timestamp bounds survive pauses between batches; opaque Slack cursors
        # may expire while the commercially limited reader waits on threads.
        boundary=identifier(messages[-1].get('ts')) if messages else None
        if pending and (not boundary or not re.fullmatch(r"[0-9]{1,12}\.[0-9]{1,12}",boundary)):
            raise SourceProviderError('invalid_provider_response')
        if pending and (threads and cursor.get('replyAfter') and float(boundary)<=float(cursor['replyAfter']) or not threads and float(boundary)>=float(latest)):
            raise SourceProviderError('invalid_provider_response')
        if threads:
            following={'threads':threads if pending else threads[1:], 'replyAfter':boundary if pending else None,
                       'historyDone':cursor.get('historyDone',False),'latest':latest,'oldest':oldest,'snapshot':snapshot}
        else:
            following={'threads':[identifier(x['ts']) for x in messages if x.get('reply_count',0)>0 and x.get('ts')],
                       'historyDone':not pending,'latest':boundary if pending else latest,'oldest':oldest,'snapshot':snapshot}
        docs=[]; skipped=0
        for row in messages:
            if not row.get('text','').strip() or row.get('subtype') in ('channel_join','channel_leave','message_deleted'):
                skipped+=1; continue
            ts=identifier(row.get('ts'))
            link=self.api('chat.getPermalink',{'channel':channel,'message_ts':ts}).get('permalink')
            body='Author: '+str(row.get('user') or row.get('bot_id') or 'Unknown')+'\nTimestamp: '+ts+'\n\n'+plain_text(row.get('text'),maximum=self.settings.max_document_bytes)
            docs.append(self.document(channel+':'+ts,resource['name']+' · '+ts,body,source_url(link,('slack.com',)),{'authorId':row.get('user'),'timestamp':ts,'threadId':row.get('thread_ts')}))
        more=bool(following['threads']) or not following['historyDone']
        return DocumentPage(tuple(docs),following if more else None,skipped,60)


class GmailReader(Reader):
    root='https://gmail.googleapis.com/gmail/v1/users/me'
    def resources(self,cursor=None):
        if cursor: raise SourceProviderError('invalid_request')
        value=self.get(self.root+'/labels').json()
        return ResourcePage(tuple(Resource(identifier(x.get('id')),plain_text(x.get('name'),maximum=300),'label') for x in rows(value,'labels',10000) if x.get('id') not in ('SPAM','TRASH')))
    def resource(self,key):
        row=obj(self.get(self.root+'/labels/'+quote(identifier(key),safe='')).json())
        if row.get('id')!=key or key in ('SPAM','TRASH'): raise SourceProviderError('resource_unavailable')
        return Resource(key,plain_text(row.get('name'),maximum=300),'label')
    def body(self,payload,depth=0):
        if depth>20: raise SourceProviderError('document_too_large')
        payload=obj(payload); parts=payload.get('parts',[])
        if not isinstance(parts,list) or len(parts)>100: raise SourceProviderError('document_too_large')
        if parts:
            values=[self.body(x,depth+1) for x in parts if not x.get('filename')]
            plain=[text for mime,text in values if mime=='text/plain' and text.strip()]
            return ('text/plain','\n'.join(plain or [text for _,text in values]))
        if payload.get('filename'): return ('','')
        mime=payload.get('mimeType',''); body=obj(payload.get('body',{})); data=body.get('data','')
        if mime not in ('text/plain','text/html') or not data: return ('','')
        if not isinstance(data,str) or len(data)>self.settings.max_document_bytes*2: raise SourceProviderError('document_too_large')
        try: decoded=base64.b64decode(data+'='*((-len(data))%4),altchars=b'-_',validate=True).decode('utf-8')
        except (ValueError,UnicodeError): raise SourceProviderError('invalid_provider_response') from None
        return (mime,text_html(decoded) if mime=='text/html' else decoded)
    def documents(self,resource,cursor=None):
        self.resource(resource['id']); cursor=cursor or {}
        # Re-scan the bounded recent window, including label changes and edited metadata.
        query={'labelIds':resource['id'],'maxResults':self.settings.page_items,'q':f'newer_than:{self.settings.lookback_days}d -in:spam -in:trash'}
        if cursor.get('page'): query['pageToken']=cursor['page']
        value=obj(self.get(self.root+'/messages',query).json()); docs=[]; skipped=0
        for message in rows(value,'messages',15):
            key=identifier(message.get('id'))
            row=obj(self.get(self.root+'/messages/'+quote(key,safe=''),{'format':'full'}).json())
            if resource['id'] not in row.get('labelIds',[]): skipped+=1; continue
            payload=obj(row.get('payload',{})); headers={str(x.get('name','')).lower():str(x.get('value','')) for x in rows(payload,'headers',200)}
            _,body=self.body(payload)
            if not body.strip(): skipped+=1; continue
            title=headers.get('subject') or '(No subject)'
            content='Subject: '+title+'\nFrom: '+headers.get('from','')+'\nDate: '+headers.get('date','')+'\n\n'+body
            docs.append(self.document(key,title,content,'https://mail.google.com/mail/u/0/#all/'+quote(key,safe=''),{'sender':headers.get('from'),'date':headers.get('date'),'messageId':key}))
        pending=next_cursor(value.get('nextPageToken'))
        return DocumentPage(tuple(docs),{'page':pending} if pending else None,skipped)


class DriveReader(Reader):
    root='https://www.googleapis.com/drive/v3/files'
    supported=('application/vnd.google-apps.document','text/plain','text/markdown','text/csv')
    def resources(self,cursor=None):
        query={'q':"trashed = false and ("+' or '.join("mimeType = '"+x+"'" for x in self.supported)+')','fields':'nextPageToken,files(id,name,mimeType)','pageSize':100,'orderBy':'modifiedTime desc'}
        if cursor: query['pageToken']=cursor
        value=obj(self.get(self.root,query).json())
        return ResourcePage(tuple(Resource(identifier(x.get('id')),plain_text(x.get('name'),maximum=600),x.get('mimeType')) for x in rows(value,'files')),next_cursor(value.get('nextPageToken')))
    def details(self,key):
        row=obj(self.get(self.root+'/'+quote(identifier(key),safe=''),{'fields':'id,name,mimeType,trashed,webViewLink,modifiedTime,size'}).json())
        if row.get('id')!=key or row.get('trashed') or row.get('mimeType') not in self.supported: raise SourceProviderError('resource_unavailable')
        return row
    def resource(self,key):
        row=self.details(key); return Resource(key,plain_text(row.get('name'),maximum=600),row['mimeType'])
    def documents(self,resource,cursor=None):
        row=self.details(resource['id']); path=self.root+'/'+quote(resource['id'],safe='')
        response=self.get(path+'/export',{'mimeType':'text/plain'}) if row['mimeType']==self.supported[0] else self.get(path,{'alt':'media'})
        try: text=response.checked().data.decode('utf-8-sig')
        except UnicodeError: raise SourceProviderError('invalid_provider_response') from None
        if not text.strip(): return DocumentPage((),skipped=1)
        return DocumentPage((self.document(resource['id'],row['name'],text,source_url(row.get('webViewLink'),('google.com',)),{'modifiedAt':row.get('modifiedTime'),'mimeType':row['mimeType']}),))


class NotionReader(Reader):
    root='https://api.notion.com/v1'
    def get(self,url,params=None,headers=None):
        return super().get(url,params,{'Notion-Version':'2026-03-11',**(headers or {})})
    def resources(self,cursor=None):
        body={'filter':{'property':'object','value':'page'},'page_size':100,'sort':{'direction':'descending','timestamp':'last_edited_time'}}
        if cursor: body['start_cursor']=cursor
        value=obj(self.request('POST',self.root+'/search',headers={'Notion-Version':'2026-03-11'},json_body=body).json())
        return ResourcePage(tuple(Resource(identifier(x.get('id')),self.title(x),'page') for x in rows(value,'results')),next_cursor(value.get('next_cursor')) if value.get('has_more') else None)
    def title(self,row):
        for prop in obj(row.get('properties',{})).values():
            if isinstance(prop,dict) and prop.get('type')=='title':
                return (''.join(str(x.get('plain_text','')) for x in prop.get('title',[])) or 'Untitled')[:300]
        return 'Untitled'
    def details(self,key):
        row=obj(self.get(self.root+'/pages/'+quote(identifier(key),safe='')).json())
        if row.get('id')!=key or row.get('archived') or row.get('in_trash'): raise SourceProviderError('resource_unavailable')
        return row
    def resource(self,key):
        row=self.details(key); return Resource(key,self.title(row),'page')
    def documents(self,resource,cursor=None):
        row=self.details(resource['id']); state=cursor or {'stack':[[resource['id'],None]],'text':[],'bytes':0}; stack=state['stack']; text=state['text']; size=state['bytes']
        # Checkpoint block traversal rather than publishing an incomplete page.
        for _ in range(min(5,self.settings.max_requests-2)):
            if not stack: break
            block,offset=stack.pop()
            value=obj(self.get(self.root+'/blocks/'+quote(identifier(block),safe='')+'/children',{'page_size':100,**({'start_cursor':offset} if offset else {})}).json())
            pending=next_cursor(value.get('next_cursor')) if value.get('has_more') else None
            if pending: stack.append([block,pending])
            children=[]
            for item in rows(value,'results'):
                kind=item.get('type'); data=obj(item.get(kind,{})); rich=data.get('rich_text',[])
                if not isinstance(rich,list): raise SourceProviderError('invalid_provider_response')
                value=''.join(str(x.get('plain_text','')) for x in rich)
                if kind=='child_page': continue
                if value: text.append(value); size+=len(value.encode())+1
                if size>self.settings.max_document_bytes or len(json.dumps({'stack':stack,'text':text},ensure_ascii=False).encode())>400000: raise SourceProviderError('document_too_large')
                if item.get('has_children'): children.append([identifier(item.get('id')),None])
            # Child blocks are included; their parent text remains immediately identifiable.
            stack.extend(reversed(children))
            if len(stack)>100 or len(json.dumps({'stack':stack,'text':text},ensure_ascii=False).encode())>400000: raise SourceProviderError('document_too_large')
        if stack: return DocumentPage((),{'stack':stack,'text':text,'bytes':size})
        if not text: return DocumentPage((),skipped=1)
        return DocumentPage((self.document(resource['id'],self.title(row),'\n'.join(text),source_url(row.get('url'),('notion.so','notion.site')),{'modifiedAt':row.get('last_edited_time')}),))


class GitHubReader(Reader):
    root='https://api.github.com'
    def details(self):
        full=self.credentials['repository']; owner,name=full.split('/')
        return obj(self.get(self.root+'/repos/'+quote(identifier(owner),safe='')+'/'+quote(identifier(name),safe='')).json())
    def resource(self,key):
        row=self.details()
        if str(row.get('id'))!=key: raise SourceProviderError('resource_unavailable')
        return Resource(key,plain_text(row.get('full_name'),maximum=300),'repository')
    def resources(self,cursor=None):
        return ResourcePage((self.resource(str(self.credentials['repository_id'])),))
    def documents(self,resource,cursor=None):
        self.resource(resource['id']); cursor=cursor or {'stage':'readme','page':1}; path=self.root+'/repos/'+self.credentials['repository']; docs=[]; skipped=0
        if cursor['stage']=='readme':
            response=self.get(path+'/readme')
            if response.status!=404:
                row=obj(response.json())
                try: content=base64.b64decode(str(row.get('content','')).replace('\n',''),validate=True).decode('utf-8')
                except (ValueError,UnicodeError): raise SourceProviderError('invalid_provider_response') from None
                if content.strip(): docs.append(self.document('readme',resource['name']+' · README',content,source_url(row.get('html_url'),('github.com',)),{'repository':resource['name']}))
            else: skipped+=1
            return DocumentPage(tuple(docs),{'stage':'issues','page':1,'since':datetime.fromtimestamp(time.time()-self.settings.lookback_days*86400,timezone.utc).isoformat()},skipped)
        page=cursor['page']
        if type(page) is not int or not 1<=page<=10000: raise SourceProviderError('invalid_provider_response')
        values=self.get(path+'/issues',{'state':'all','sort':'updated','direction':'desc','since':cursor['since'],'per_page':self.settings.page_items,'page':page}).json()
        if not isinstance(values,list) or len(values)>15: raise SourceProviderError('invalid_provider_response')
        for row in values:
            row=obj(row); number=row.get('number')
            if type(number) is not int or number<=0: raise SourceProviderError('invalid_provider_response')
            title=plain_text(row.get('title'),maximum=1200); author=obj(row.get('user',{})).get('login','Unknown')
            content=title+'\nState: '+str(row.get('state'))+'\nAuthor: '+str(author)+'\nUpdated: '+str(row.get('updated_at'))+'\n\n'+str(row.get('body') or '')
            docs.append(self.document('issue:'+str(number),('#'+str(number)+' '+title),content,source_url(row.get('html_url'),('github.com',)),{'kind':'pull_request' if 'pull_request' in row else 'issue','updatedAt':row.get('updated_at'),'author':author}))
        return DocumentPage(tuple(docs),cursor|{'page':page+1} if len(values)==self.settings.page_items else None)


READERS={'slack':SlackReader,'gmail':GmailReader,'drive':DriveReader,'notion':NotionReader,'github':GitHubReader}
