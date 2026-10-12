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

function screen({role='owner',conflict=false}={}){
 const slots=[],effects=[],requests=[];let cursor=0;
 const task={id:'task-one',title:'Interview customers',description:'Write down the main objections.',status:'todo',createdBy:'other-user',creatorName:'Ilyas',assigneeId:'current-user',assigneeName:'Fedor',version:7,createdAt:'2026-10-12T12:00:00Z',updatedAt:'2026-10-12T12:00:00Z'};
 const project={id:'project-one',name:'Flare',role,kind:'team',writable:true,canManageLicense:true};
 const response={projects:[project],capability:{enabled:true,canCreate:false,projectCount:1,requiresVerification:false,limits:{members:10,tasks:1000,projects:1}}};
 const api={async teamRequest(url,body,method){requests.push({url,body,method});
  if(body&&url.endsWith('/tasks')&&conflict)throw Error('Someone changed this task. Keep your draft.');
  if(url==='/projects')return response;if(url.endsWith('/members'))return[{id:'current-user',name:'Fedor',role},{id:'other-user',name:'Ilyas',role:'editor'}];
  if(url.endsWith('/tasks'))return body?{id:task.id,version:8}:{tasks:[task],nextCursor:null};
  if(url.endsWith('/usage'))return{contentBytes:10,documents:1,tasks:1,limits:{contentBytes:104857600,documents:5000,tasks:1000}};
  if(url.endsWith('/invitations'))return[];if(url.endsWith('/history'))return[];
  if(url.endsWith('/tasks/task-one'))return{...task,version:8,title:'Changed by colleague'};
  return{ok:true};}};
 const react={useState(initial){const index=cursor++;if(!(index in slots))slots[index]=initial;return[slots[index],next=>{slots[index]=typeof next==='function'?next(slots[index]):next;}];},useRef(value){const index=cursor++;if(!(index in slots))slots[index]={current:value};return slots[index];},useEffect(fn){effects.push(fn);}};
 const load=loader({window:{addEventListener(){},removeEventListener(){},dispatchEvent(){}},crypto:{randomUUID:()=> 'new-task-id'}},
  {react,'@/lib/auth/session':{apiBaseUrl:'/api'},'@/components/auth-session':{useSession:()=>({user:{id:'current-user'},workspace:{id:project.id}})},
   '@/components/select':{Select:'select'},'@/components/dialog':{Dialog:'dialog'},'@/components/icons':{Icon:'icon'},
   '@/i18n/provider':{useI18n:()=>({locale:'en'})},'@/lib/team-context':{switchProject(){}},'./api':api});
 const {TeamPage}=load('features/team/team-page.tsx');
 return{task,requests,render(){cursor=0;return TeamPage();},async start(){this.render();for(const effect of effects.splice(0))effect();await flush();},all:()=>slots};
}

test('shared tasks display the server creator, assignee and timestamp; viewer cannot add or edit',async()=>{
 const h=screen({role:'viewer'});await h.start();let tree=h.render();assert.match(text(tree),/Added by\s+Ilyas/);
 assert.match(text(tree),/Assigned to\s*:\s*Fedor/);assert.equal(nodes(tree).find(n=>n.type==='time').props.dateTime,h.task.createdAt);
 assert.equal(nodes(tree).find(n=>n.type==='button'&&text(n).trim()==='Add task').props.disabled,true);
 nodes(tree).find(n=>n.props?.className==='card team-task').props.onClick();tree=h.render();
 assert.ok(nodes(tree).filter(n=>n.type==='input'||n.type==='textarea').every(n=>n.props.disabled));
 assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='Save task'));
});

test('task submission uses its expected server version and never sends a forged creator; conflict preserves the draft',async()=>{
 const h=screen({conflict:true});await h.start();nodes(h.render()).find(n=>n.props?.className==='card team-task').props.onClick();
 let tree=h.render();nodes(tree).find(n=>n.type==='input'&&n.props.value===h.task.title).props.onChange({target:{value:'My unfinished draft'}});
 tree=h.render();nodes(tree).find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await flush();tree=h.render();
 const request=h.requests.find(r=>r.body&&r.url.endsWith('/tasks'));assert.equal(request.body.expectedVersion,7);
 assert.equal(request.body.title,'My unfinished draft');assert.equal(request.body.createdBy,undefined);
 assert.ok(text(tree).includes('Keep your draft'));assert.ok(nodes(tree).some(n=>n.type==='input'&&n.props.value==='My unfinished draft'));
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
