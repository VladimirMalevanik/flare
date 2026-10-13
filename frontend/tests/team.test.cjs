const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const source=path.resolve(__dirname,'../src');
const plain=value=>JSON.parse(JSON.stringify(value));
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
const nodes=n=>!n||typeof n!=='object'?[]:Array.isArray(n)?n.flatMap(nodes):[n,...nodes(n.props?.children)];
const text=n=>typeof n==='string'?n:Array.isArray(n)?n.map(text).join(' '):n&&typeof n==='object'?text(n.props?.children):'';
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function loader(globals={},mocks={}){
 const cache=new Map();
 function load(relative){
  const file=path.resolve(source,relative);if(cache.has(file))return cache.get(file);
  const exports={};cache.set(file,exports);
  const compiled=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(compiled,{exports,Error,Event,URLSearchParams,AbortController,AbortSignal,setTimeout,clearTimeout,fetch,process:{env:{}},...globals,require(name){
   if(name in mocks)return mocks[name];
   if(name==='react/jsx-runtime')return jsx;
   const target=name.startsWith('@/')?path.join(source,name.slice(2)):path.resolve(path.dirname(file),name);
   for(const suffix of ['.ts','.tsx'])if(fs.existsSync(target+suffix))return load(target+suffix);
   throw Error('Unexpected import '+name);
  }});return exports;
 }
 return load;
}

test('project belongs to the URL tab; API query and fragments are preserved without changing an auth cookie',()=>{
 const first=loader({window:{location:{search:'?project=project-one'}}})('lib/team-context.ts');
 const second=loader({window:{location:{search:'?project=project-two'}}})('lib/team-context.ts');
 assert.equal(first.projectApiUrl('/api/items?limit=100'),'/api/items?limit=100&workspace=project-one');
 assert.equal(second.projectApiUrl('/api/export'),'/api/export?workspace=project-two');
 assert.equal(first.projectHref('/settings#subscription'),'/settings?project=project-one#subscription');
 assert.equal(first.projectHref('/vault',null),'/vault');
});

test('Team API sends a bounded cookie request with explicit acceptance and no client identity headers',async()=>{
 const requests=[];
 const {teamRequest}=loader({fetch:async(url,options)=>{requests.push({url,options});return{ok:true,status:200,json:async()=>({workspaceId:'project-one'})};}},
  {'@/lib/auth/session':{apiBaseUrl:'/api'}})('features/team/api.ts');
 const result=await teamRequest('/invitations/accept',{token:'synthetic-invitation',accept:true});
 assert.equal(result.workspaceId,'project-one');
 assert.equal(requests[0].url,'/api/team/invitations/accept');assert.equal(requests[0].options.credentials,'include');
 assert.equal(requests[0].options.cache,'no-store');assert.equal(requests[0].options.headers['X-User-Id'],undefined);
 assert.deepEqual(JSON.parse(requests[0].options.body),{token:'synthetic-invitation',accept:true});
});

test('Team deadline bounds JSON parsing even if transport ignores abort; late success is ignored',async()=>{
 const timers=new Map();let timerId=0,finishBody;
 const load=loader({setTimeout(fn,ms){timers.set(++timerId,{fn,ms});return timerId;},clearTimeout(id){timers.delete(id);},
  fetch:async()=>({ok:true,status:200,json:()=>new Promise(resolve=>{finishBody=resolve;})})},
  {'@/lib/auth/session':{apiBaseUrl:'/api'}});
 const {teamRequest}=load('features/team/api.ts');const pending=teamRequest('/projects');await flush();
 assert.equal(timers.size,1);const timer=[...timers.values()][0];assert.equal(timer.ms,12000);timer.fn();
 await assert.rejects(pending,error=>error.code==='team_request_stopped');
 finishBody({projects:[]});await flush();assert.equal(timers.size,0);
});

test('Team API errors retain only stable public messages and aborted requests never call transport',async()=>{
 let calls=0;const load=loader({fetch:async()=>{calls++;return{ok:false,status:409,json:async()=>({detail:{code:'team_conflict',message:'Keep your draft.'}})};}},
  {'@/lib/auth/session':{apiBaseUrl:'/api'}});const {teamRequest}=load('features/team/api.ts');
 await assert.rejects(teamRequest('/projects'),e=>e.status===409&&e.code==='team_conflict'&&e.message==='Keep your draft.');
 const controller=new AbortController();controller.abort();await assert.rejects(teamRequest('/projects',undefined,undefined,controller.signal));assert.equal(calls,1);
});

function screen({role='owner',writable=true,notesFailure=false,empty=false}={}){
 const slots=[],effects=[],cleanups=[],requests=[],captures=[];let cursor=0;
 const note={id:'note-one',title:'Customer interview',author:'Ilyas',createdBy:'other-user',createdAt:'2026-10-12T12:00:00Z'};
 const project={id:'project-one',name:'Flare',role,kind:'team',writable,canManageLicense:true};
 const response={projects:[project],capability:{enabled:true,canCreate:false,projectCount:1,requiresVerification:false,limits:{members:10,projects:1}}};
 const api={async teamRequest(url,body,method){requests.push({url,body,method});
  assert.ok(!url.includes('/tasks'), 'Team must not request task data');
  if(url==='/projects')return response;if(url.endsWith('/members'))return[{id:'current-user',name:'Fedor',role},{id:'other-user',name:'Ilyas',role:'editor'}];
  if(url.endsWith('/usage'))return{contentBytes:10,documents:1,limits:{contentBytes:104857600,documents:5000}};
  if(url.endsWith('/invitations'))return[];return{ok:true};}};
 const react={useState(initial){const index=cursor++;if(!(index in slots))slots[index]=initial;return[slots[index],next=>{slots[index]=typeof next==='function'?next(slots[index]):next;}];},useRef(value){const index=cursor++;if(!(index in slots))slots[index]={current:value};return slots[index];},useEffect(fn){effects.push(fn);}};
 const load=loader({window:{location:{search:'?project=project-one'},addEventListener(){},removeEventListener(){},dispatchEvent(){}}},
  {react,'next/link':{default:'a'},'@/components/workspace-context':{useWorkspace:()=>({revision:0,openCapture:()=>captures.push('shared-note')})},
   '@/lib/data':{dataProvider:{async listItems(options){requests.push({url:'/items',options});if(notesFailure)throw Error('Notes unavailable');return empty?[]:[note];}}},
   '@/components/auth-session':{useSession:()=>({user:{id:'current-user'},workspace:{id:project.id}})},
   '@/components/select':{Select:'select'},'@/components/dialog':{Dialog:'dialog'},'@/components/icons':{Icon:'icon'},
   '@/i18n/provider':{useI18n:()=>({locale:'en'})},'./api':api});
 const {TeamPage}=load('features/team/team-page.tsx');
 return{note,requests,captures,render(){cursor=0;return TeamPage();},async start(){this.render();for(const effect of effects.splice(0))cleanups.push(effect());await flush();},dispose(){for(const cleanup of cleanups)cleanup?.();}};
}

test('Team defaults to authored shared notes and project-bound Vault/Flares/Sources with no task controls or requests',async()=>{
 const h=screen();await h.start();const tree=h.render();
 assert.match(text(tree),/Added by\s+Ilyas/);assert.match(text(tree),/Shared Flares/);
 const links=nodes(tree).filter(n=>n.type==='a').map(n=>new URL(n.props.href,'http://localhost'));
 for(const path of ['/vault','/insights','/sources','/settings'])assert.ok(links.some(url=>url.pathname===path&&url.searchParams.get('project')==='project-one'),path);
 assert.ok(links.some(url=>url.searchParams.get('item')==='note-one'&&url.searchParams.get('project')==='project-one'));
 assert.equal(nodes(tree).find(n=>n.type==='time').props.dateTime,h.note.createdAt);
 assert.deepEqual(plain(h.requests.find(r=>r.url==='/items').options),{limit:5});
 assert.doesNotMatch(text(tree),/Add task|Export tasks|Assigned to|Tasks/);
 nodes(tree).find(n=>n.type==='button'&&text(n).trim()==='Add a note').props.onClick();assert.deepEqual(h.captures,['shared-note']);h.dispose();
});

test('viewer or expired Team can read shared context but cannot add notes; personal notes are not claimed as shared',async()=>{
 for(const options of [{role:'viewer'},{writable:false}]){
  const h=screen(options);await h.start();const tree=h.render();
  assert.equal(nodes(tree).find(n=>n.type==='button'&&text(n).trim()==='Add a note').props.disabled,true);
  assert.ok(nodes(tree).some(n=>n.type==='a'&&text(n).includes('Open Vault')));assert.match(text(tree),/personal Vault stays separate/);h.dispose();
 }
});

test('empty context explains scheduled shared analysis, while a failed note fetch remains an error instead of an empty Vault',async()=>{
 const empty=screen({empty:true});await empty.start();assert.match(text(empty.render()),/first shared note/);assert.match(text(empty.render()),/next scheduled analysis/);empty.dispose();
 const failed=screen({notesFailure:true});await failed.start();const tree=failed.render();assert.match(text(tree),/Notes unavailable/);assert.doesNotMatch(text(tree),/first shared note/);assert.ok(nodes(tree).some(n=>n.props.role==='alert'));failed.dispose();
});

test('invitation requires an explicit sharing acknowledgement and editor/viewer role, with no membership identity supplied',async()=>{
 const h=screen();await h.start();let tree=h.render();nodes(tree).find(n=>n.type==='button'&&text(n).startsWith('Members')).props.onClick();
 tree=h.render();nodes(tree).find(n=>n.type==='button'&&text(n).includes('Invite member')).props.onClick();tree=h.render();
 assert.equal(nodes(tree).find(n=>n.type==='button'&&text(n)==='Send invitation').props.disabled,true);
 nodes(tree).find(n=>n.type==='input'&&n.props.type==='email').props.onChange({target:{value:'colleague@example.invalid'}});
 nodes(tree).find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});
 tree=h.render();nodes(tree).find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await flush();
 const request=h.requests.find(r=>r.body&&r.url.endsWith('/invitations'));
 assert.deepEqual(plain(request.body),{email:'colleague@example.invalid',role:'editor',sharingAcknowledged:true});
});

test('Team billing is a server-confirmed paid plan with a finite deadline',()=>{
 const api=loader()('lib/billing/billing-api.ts');
 const status={environment:'sandbox',workspaceId:'project-one',plan:'team',status:'active',canManageBilling:false,checkoutAvailable:false,
  accessUntil:'2099-01-01T00:00:00Z',trialEndsAt:null,currentPeriodEndsAt:'2099-01-01T00:00:00Z',scheduledChange:null};
 assert.equal(api.parseBillingStatus(status).plan,'team');assert.throws(()=>api.parseBillingStatus({...status,accessUntil:null}));
});

test('Team and Pro share one checkout lock and SDK; Team uses only the server-owned Team intent price',async()=>{
 const load=loader();const api=load('lib/billing/billing-api.ts');const sdkLoad=loader({}, {'./billing-api':api});
 const {createSandboxCheckoutClient}=sdkLoad('lib/billing/checkout-controller.ts');let callback,initialized=0,intents=[];const opened=[];
 const teamPrice='pri_'+'t'.repeat(26),proPrice='pri_'+'p'.repeat(26);const user={id:'current-user',email:'owner@example.invalid'};
 const checkout=createSandboxCheckoutClient({token:'test_synthetic',proPriceId:proPrice,
  initialize:async options=>{callback=options.eventCallback;initialized++;return{Initialized:true,Checkout:{open(value){opened.push(value);},close(){}}};},
  getCheckoutIntent:async(_signal,plan)=>{intents.push(plan);return{environment:'sandbox',priceId:plan==='team'?teamPrice:proPrice,quantity:1,email:user.email,
   customData:{userId:user.id,checkoutIntent:'server-bound-intent'},expiresAt:new Date(Date.now()+60000).toISOString()};}});
 const first=checkout.openProCheckout(user,'en','team');const duplicate=checkout.openProCheckout(user,'en');await Promise.all([first,duplicate]);
 assert.deepEqual(intents,['team']);assert.equal(opened[0].items[0].priceId,teamPrice);assert.equal(initialized,1);
 callback({name:'checkout.loaded'});callback({name:'checkout.closed'});await checkout.openProCheckout(user,'en');
 assert.equal(initialized,1);assert.equal(opened[1].items[0].priceId,proPrice);callback({name:'checkout.closed'});
});

test('real API adapter preserves server note attribution, optional legacy author and the selected project',async()=>{
 const calls=[];
 const dto={id:'note-one',type:'note',title:'Interview',content:'A shared customer interview.',status:'ready',createdAt:'2026-10-12T12:00:00Z',updatedAt:'2026-10-12T12:00:00Z',currentVersionId:'version-one',versionNumber:1,author:'Ilyas',createdBy:'member-id'};
 const {ApiDataProvider}=loader({window:{location:{search:'?project=project-one'}},fetch:async(url,options)=>{calls.push({url,options});return{ok:true,status:200,json:async()=>[dto,{...dto,id:'legacy-note',author:null,createdBy:null}]};}})('lib/data/api-provider.ts');
 const rows=await new ApiDataProvider({baseUrl:'/api',fallback:{}}).listItems({limit:5});
 assert.equal(calls[0].url,'/api/items?limit=5&workspace=project-one');assert.equal(calls[0].options.credentials,'include');
 assert.equal(rows[0].author,'Ilyas');assert.equal(rows[0].createdBy,'member-id');assert.equal(rows[1].author,undefined);assert.equal(rows[1].createdBy,undefined);
});
