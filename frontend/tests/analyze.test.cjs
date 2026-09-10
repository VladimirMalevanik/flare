const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText, filename);
const { AnalyzeController } = require('../src/features/analyze/analyze-controller.ts');
const { ApiDataProvider } = require('../src/lib/data/api-provider.ts');
const pending = { id: 'run', status:'pending',stage:'analysis',selectedChunkCount:2,flareIds:[],error:null };
const completed = {...pending,status:'completed',stage:'completed',flareIds:['flare']};
function setup(provider, sleep = async () => {}, maxPolls = 40) {
  const states=[]; let refreshed=0, keys=0;
  const controller=new AnalyzeController(provider,s=>states.push(s),()=>refreshed++,sleep,()=>`key-${++keys}`,maxPolls);
  return {controller,states,refreshed:()=>refreshed,keys:()=>keys};
}
test('click generates one key, polls stages, refreshes once on completion', async () => {
  const keys=[],polls=[],delays=[];
  const f=setup({startAnalysis:async key=>{keys.push(key);return pending;},getAnalysisRun:async id=>{polls.push(id);return polls.length===1?{...pending,stage:'flare_generation',status:'processing'}:completed;}},async ms=>delays.push(ms));
  await f.controller.start();
  assert.deepEqual(keys,['key-1']); assert.deepEqual(polls,['run','run']);
  assert.deepEqual(delays,[1000,1500]); assert.equal(f.refreshed(),1);
  assert.ok(f.states.some(s=>s.message==='Generating Flares…'));
  assert.equal(f.states.at(-1).busy,false);
});
test('double click cannot create duplicate work', async () => {
  let resolve; const f=setup({startAnalysis:()=>new Promise(r=>resolve=r),getAnalysisRun:async()=>completed});
  const a=f.controller.start(); await f.controller.start();
  assert.equal(f.keys(),1); resolve(completed); await a;
});
test('failure stops polling and explicit retry creates new key', async () => {
  const keys=[];
  const f=setup({startAnalysis:async key=>{keys.push(key);return {...pending,status:'failed',stage:'failed',error:'network'};},getAnalysisRun:()=>assert.fail('poll after terminal')});
  await f.controller.start(); await f.controller.start();
  assert.deepEqual(keys,['key-1','key-2']); assert.equal(f.refreshed(),0);
});
test('uncertain POST outcome retries the same key, never mock success', async () => {
  const keys=[];
  const f=setup({startAnalysis:async key=>{keys.push(key);if(keys.length===1)throw Error('network');return completed;},getAnalysisRun:()=>assert.fail()});
  await f.controller.start(); assert.equal(f.refreshed(),0);
  await f.controller.start(); assert.deepEqual(keys,['key-1','key-1']);
});
test('unmount aborts pending request and ignores its late completion', async () => {
  let resolve, signal;
  const f=setup({startAnalysis:(_,s)=>{signal=s;return new Promise(r=>resolve=r);},getAnalysisRun:()=>assert.fail()});
  const a=f.controller.start(); const count=f.states.length; f.controller.dispose();
  assert.equal(signal.aborted,true); resolve(completed); await a;
  assert.equal(f.states.length,count); assert.equal(f.refreshed(),0);
});
test('unmount cancels sleep and no stale poll occurs', async () => {
  let entered, release; const ready=new Promise(r=>entered=r);
  const f=setup({startAnalysis:async()=>pending,getAnalysisRun:()=>assert.fail('stale poll')},()=>{entered();return new Promise(r=>release=r);});
  const a=f.controller.start(); await ready; f.controller.dispose(); release(); await a;
  assert.equal(f.refreshed(),0);
});
test('bounded polling can resume status without another enqueue', async () => {
  let posts=0,polls=0;
  const f=setup({startAnalysis:async()=>{posts++;return pending;},getAnalysisRun:async()=>{polls++;return pending;}},async()=>{},2);
  await f.controller.start(); assert.equal(polls,2); assert.equal(f.states.at(-1).busy,false);
  await f.controller.start(); assert.equal(posts,1); assert.equal(polls,4);
});
test('API sends strict body, idempotency, cookies and abort signal', async () => {
  const calls=[]; const signal=new AbortController().signal;
  global.fetch=async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(pending),{status:202});};
  const api=new ApiDataProvider({baseUrl:'/api',fallback:new Proxy({}, {get(){assert.fail('mock fallback');}})});
  await api.startAnalysis('key',signal); await api.getAnalysisRun('run',signal);
  assert.equal(calls[0].options.body,'{}'); assert.equal(calls[0].options.headers['Idempotency-Key'],'key');
  assert.equal(calls[0].options.credentials,'include'); assert.equal(calls[0].options.cache,'no-store');
  assert.equal(calls[0].options.signal,signal); assert.equal(calls[1].url,'/api/analysis-runs/run');
});
test('API error and malformed run never fall back to mock', async () => {
  const api=new ApiDataProvider({baseUrl:'/api',fallback:new Proxy({}, {get(){assert.fail('mock fallback');}})});
  global.fetch=async()=>new Response('{}',{status:503}); await assert.rejects(api.startAnalysis('key'));
  global.fetch=async()=>new Response(JSON.stringify({...pending,stage:'completed'})); await assert.rejects(api.getAnalysisRun('run'));
});
test('zero-Flares completion refreshes real feed and says none found', async () => {
  const f=setup({startAnalysis:async()=>({...completed,flareIds:[]}),getAnalysisRun:()=>assert.fail()});
  await f.controller.start(); assert.equal(f.refreshed(),1); assert.match(f.states.at(-1).message,/No new Flares/);
});
