const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const vm = require('node:vm');
const policy = {enabled:true,revision:'x-launch-2026-10-v1',noticeId:'measurement-x-v1',eligibility:'explicit-opt-in',cookieSeconds:604800};
function load(extra={}) {
  const storage = new Map();
  const sandbox = {URL,AbortSignal,navigator:{},window:{location:{href:'https://flare.invalid/?utm_source=x&utm_medium=organic_social&utm_campaign=launch_2026_10&utm_content=fedor&ref=fedor&email=private'}},document:{referrer:'https://t.co/private'},
    sessionStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},...extra};
  const consent={};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/telemetry/consent.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:consent});
  const exports={};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/auth/acquisition.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:()=>consent,...sandbox});
  return {m:exports,storage,sandbox};
}
test('collection stays off before opt-in and after rejecting; Azure consent is independent',async()=>{
  const calls=[];
  const {m,storage}=load({fetch:async(u,o)=>{calls.push([u,o]);return {ok:true,json:async()=>policy}}});
  storage.set('flare-site-analytics-consent-v1','allowed');
  await m.captureAcquisition('/api');assert.equal(calls.length,1);
  assert.equal(m.chooseAcquisition(policy,false),true);
  await m.captureAcquisition('/api');assert.equal(calls.length,2);
  assert.equal(m.chooseAcquisition(policy,true),true);
  await m.captureAcquisition('/api');
  assert.equal(calls.filter(c=>c[0].endsWith('/touch')).length,1);
  const payload=JSON.parse(calls.at(-1)[1].body);
  assert.equal(payload.touch.ref,'fedor');assert.equal(payload.touch.referrer_domain,'t.co');assert.equal(payload.touch.email,undefined);
  assert.deepEqual([...storage.keys()],['flare-site-analytics-consent-v1','flare_measurement_opt_in']);
  assert.equal(storage.get(m.consentKey),policy.revision);
});
test('unknown notices, changed revisions and changed retention never enable collection',async()=>{
  for(const changed of [{revision:'other'},{noticeId:'other'},{cookieSeconds:86400},{eligibility:'implicit'},{enabled:'true'}]) {
    const calls=[];const {m}=load({fetch:async u=>{calls.push(u);return {ok:true,json:async()=>({...policy,...changed})}}});
    m.chooseAcquisition(policy,true);await m.captureAcquisition('/api');assert.equal(calls.length,1);
  }
});
test('privacy signals suppress even previously allowed collection',async()=>{
  for(const navigator of [{globalPrivacyControl:true},{doNotTrack:'1'},{msDoNotTrack:'yes'}]) {
    let calls=0;const {m,storage}=load({navigator,fetch:async()=>{calls++;return {ok:true,json:async()=>policy}}});
    storage.set(m.consentKey,policy.revision);
    await m.captureAcquisition('/api');assert.equal(calls,0);
    assert.equal(m.chooseAcquisition(policy,true),false);
    assert.equal(storage.has(m.consentKey),false);
  }
});
test('storage failure fails closed and reset does not change Azure consent',async()=>{
  const {m}=load({sessionStorage:{getItem(){throw Error('blocked')},setItem(){throw Error('blocked')},removeItem(){throw Error('blocked')}}});
  assert.equal(m.chooseAcquisition(policy,true),false);
  m.resetAcquisitionConsent();
  const normal=load();normal.storage.set('flare-site-analytics-consent-v1','allowed');normal.m.chooseAcquisition(policy,true);normal.m.resetAcquisitionConsent();
  assert.equal(normal.storage.get('flare-site-analytics-consent-v1'),'allowed');
});
test('withdrawal waits for an in-flight touch and clears anonymous and account measurement',async()=>{
  const calls=[];let finish;
  const {m,storage}=load({fetch:async url=>{calls.push(url);if(url.endsWith('/touch'))await new Promise(r=>finish=r);return {ok:true,json:async()=>policy}}});
  m.chooseAcquisition(policy,true);
  const touch=m.captureAcquisition('/api',policy);
  await Promise.resolve();
  const removal=m.withdrawAcquisition('/api',true);
  assert.equal(storage.has(m.consentKey),false);
  assert.deepEqual(calls,['/api/acquisition/touch']);
  finish();await touch;assert.equal(await removal,true);
  assert.deepEqual(calls,['/api/acquisition/touch','/api/acquisition/forget','/api/analytics/withdraw']);
});
test('failed account withdrawal is reported and anonymous notice withdrawal is supported',async()=>{
  for(const status of [401,403,500]) {
    const {m}=load({fetch:async url=>({ok:!url.endsWith('/withdraw'),status})});
    assert.equal(await m.withdrawAcquisition('/api',true),false);
    assert.equal(await m.withdrawAcquisition('/api','optional'),status===401);
  }
});
test('account settings do not mistake auth-boundary tab consent reset for account measurement status',()=>{
  const compile=file=>ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
  const copies={};vm.runInNewContext(compile('src/features/acquisition/copy.ts'),{exports:copies});
  for(const choice of ['allowed','unset','rejected']) {
    const exports={};const jsx=(type,props)=>({type,props});
    const mocks={
      'react':{useState:v=>[v,()=>{}]},'react/jsx-runtime':{jsx,jsxs:jsx},'next/link':{default:'a'},
      '@/i18n/provider':{useI18n:()=>({locale:'en'})},'@/lib/auth/session':{apiBaseUrl:'/api'},
      '@/lib/auth/acquisition':{acquisitionChoice:()=>choice},'./copy':copies,
      './use-policy':{useAcquisitionPolicy:()=>policy,useAcquisitionPrivacy:()=>false},
      '@/features/telemetry/telemetry.module.css':{default:{}},
    };
    vm.runInNewContext(compile('src/features/acquisition/preferences.tsx'),{exports,require:n=>mocks[n]});
    const tree=exports.AcquisitionPreferences({account:true});
    const flatten=node=>typeof node==='string'?node:Array.isArray(node)?node.map(flatten).join(' '):node?.props?flatten(node.props.children):'';
    const text=flatten(tree);
    assert.match(text,/You can remove your account’s measurement data below/);
    assert.doesNotMatch(text,/Link measurement stays off until you allow it|Link measurement is allowed for this tab/);
  }
});
test('registration asserts current consent; rejection, privacy signals and failed forget cannot reuse an old cookie',async()=>{
  for(const scenario of ['allowed','rejected','privacy','unset']) {
    const calls=[];
    const {m,storage,sandbox}=load({fetch:async(url,options)=>{
      calls.push([url,options]);return {ok:true,status:201,json:async()=>({ok:true})};
    }});
    if(scenario!=='unset')storage.set(m.consentKey,policy.revision);
    if(scenario==='rejected')storage.set(m.rejectionKey,policy.revision);
    if(scenario==='privacy')sandbox.navigator.globalPrivacyControl=true;
    const exports={};
    vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/auth/session.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:()=>m,process:{env:{}},...sandbox});
    await exports.authRequest('register',{email:'synthetic@example.invalid',acquisitionOptIn:true});
    assert.equal(JSON.parse(calls[0][1].body).acquisitionOptIn,scenario==='allowed');
    assert.equal(storage.has(m.consentKey),false);
  }
});
test('failed registration keeps its active choice for a corrected retry; login still clears it',async()=>{
  const {m,storage,sandbox}=load({fetch:async()=>({ok:false,status:422,json:async()=>({detail:'synthetic validation'})})});
  storage.set(m.consentKey,policy.revision);
  const exports={};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/auth/session.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:()=>m,process:{env:{}},...sandbox});
  await assert.rejects(exports.authRequest('register',{}));
  assert.equal(storage.get(m.consentKey),policy.revision);
  await assert.rejects(exports.authRequest('login',{}));
  assert.equal(storage.has(m.consentKey),false);
});
