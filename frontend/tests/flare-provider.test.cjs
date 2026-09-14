// Execute the real TypeScript providers using the existing compiler; no test dependency.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '../src');
const resolve = Module._resolveFilename;
Module._resolveFilename = function(request, parent, ...args) {
  return resolve.call(this, request.startsWith('@/') ? path.join(root, request.slice(2)) : request, parent, ...args);
};
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText, filename);
const { ApiDataProvider } = require('../src/lib/data/api-provider.ts');
const { MockDataProvider } = require('../src/lib/data/mock-provider.ts');
const { contextItems } = require('../src/mocks/cupertino.ts');
const dto = { id: 'flare-1', type: 'Recommendation', title: 'Finish the core flow',
  statement: 'The core flow is unfinished.', action: 'Finish the core flow before integrations.',
  reason: 'The release deadline is this week.', createdAt: '2026-09-09T00:00:00Z',
  evidence: [{ itemId: 'note-1', sourceTitle: 'Plan', sourceType: 'note', excerpt: 'Ship this week.', sourceUrl: null }] };
const provider = () => new ApiDataProvider({baseUrl:'/api', fallback:new Proxy({}, {get() {throw new Error('Mock fallback called');}})});

test('API list/detail use real DTO, cookie and no-store', async () => {
  const urls=[];
  global.fetch=async (url,opts) => {urls.push(url); assert.equal(opts.credentials,'include'); assert.equal(opts.cache,'no-store');
    return new Response(JSON.stringify(url==='/api/flares' ? [dto] : dto));};
  assert.deepEqual(await provider().listInsights(),[dto]);
  assert.deepEqual(await provider().getInsight('flare-1'),dto);
  assert.deepEqual(urls,['/api/flares','/api/flares/flare-1']);
});
test('404 maps to null; outage never falls back to demo', async () => {
  global.fetch=async () => new Response('{}',{status:404});
  assert.equal(await provider().getInsight('foreign'),null);
  global.fetch=async () => {throw new Error('offline');};
  await assert.rejects(provider().listInsights(),/Cannot reach/);
});
test('old taxonomy and malformed recommendation fail closed', async () => {
  for (const changed of [{type:'Discovery'}, {action:null}, {evidence:[]}]) {
    global.fetch=async () => new Response(JSON.stringify([{...dto,...changed}]));
    await assert.rejects(provider().listInsights());
  }
});
test('mock path is independent and has exact evidence for new taxonomy', async () => {
  global.fetch=async () => {throw new Error('Mock must not use HTTP');};
  const mock=new MockDataProvider(); const flares=await mock.listInsights();
  assert.deepEqual(new Set(flares.map(f=>f.type)),new Set(['Reminder','Warning','Recommendation']));
  for (const flare of flares) {
    assert.deepEqual(await mock.getInsight(flare.id),flare);
    for (const evidence of flare.evidence) {
      const item=contextItems.find(item=>item.id===evidence.itemId);
      assert.ok(item.content.includes(evidence.excerpt));
    }
  }
});

test('detail fetch is independent of the first list page and empty lists stay empty', async () => {
  const calls=[];
  global.fetch=async (url) => {
    calls.push(url);
    return new Response(JSON.stringify(url==='/api/flares' ? [] : dto));
  };
  const api=provider();
  assert.deepEqual(await api.listInsights(),[]);
  assert.deepEqual(await api.getInsight('outside-first-page'),dto);
  assert.deepEqual(calls,['/api/flares','/api/flares/outside-first-page']);
});

test('GitHub source state and actions stay behind the API provider boundary', async () => {
  const seed = [{id:'github',name:'GitHub',scope:'Project activity',description:'Planned',channels:[],status:'coming-soon',updated:'Soon'}];
  const fallback = {listSources:async()=>seed};
  const calls=[];
  global.fetch=async(url,options={}) => {
    calls.push([url,options.method ?? 'GET',options.body]);
    if (url==='/api/integrations/github') return options.method==='DELETE'
      ? new Response(null,{status:204})
      : new Response(JSON.stringify({status:'connected',accountLogin:'acme',repository:{id:101,owner:'acme',name:'flare',fullName:'acme/flare',private:true,htmlUrl:'https://github.com/acme/flare'}}));
    if (url.endsWith('/start')) return new Response(JSON.stringify({authorizationUrl:'https://github.com/apps/flare/installations/new?state=safe'}));
    if (url.endsWith('/repositories')) return new Response(JSON.stringify([{id:101,owner:'acme',name:'flare',fullName:'acme/flare',private:true,htmlUrl:'https://github.com/acme/flare'}]));
    if (url.endsWith('/repository')) return new Response(JSON.stringify({status:'connected',accountLogin:'acme',repository:{id:101,owner:'acme',name:'flare',fullName:'acme/flare',private:true,htmlUrl:'https://github.com/acme/flare'}}));
    assert.fail(`Unexpected URL ${url}`);
  };
  const api=new ApiDataProvider({baseUrl:'/api',fallback});
  const sources=await api.listSources();
  assert.equal(sources[0].status,'connected'); assert.equal(sources[0].repository.fullName,'acme/flare');
  assert.match(await api.startGitHubConnection(),/^https:\/\/github\.com\/apps\//);
  assert.equal((await api.listGitHubRepositories())[0].id,101);
  await api.selectGitHubRepository(101); await api.disconnectGitHub();
  assert.deepEqual(calls.map(call=>call[0]),[
    '/api/integrations/github','/api/integrations/github/start','/api/integrations/github/repositories',
    '/api/integrations/github/repository','/api/integrations/github',
  ]);
  assert.equal(calls[3][2],'{"repositoryId":101}');
});

test('text import sends the actual file text and maps the canonical imported item', async () => {
  const calls=[];
  const imported={id:'import-1',format:'csv',fileName:'customers.csv',item:{
    id:'item-1',type:'file',title:'customers',content:'name,stage\nAda,beta\n',
    fileName:'customers.csv',fileSize:20,fileType:'text/csv',status:'ready',
    createdAt:'2026-09-09T00:00:00Z',updatedAt:'2026-09-09T00:00:00Z',
    currentVersionId:'00000000-0000-0000-0000-000000000001',versionNumber:1,
    extractedFacts:[],relatedItemIds:[]
  },rowCount:1,chunkCount:1,analysisJobsQueued:1};
  global.fetch=async (url, options) => {
    calls.push([url, JSON.parse(options.body)]);
    return new Response(JSON.stringify(imported));
  };
  const result=await provider().importTextFile({
    format:'csv',fileName:'customers.csv',fileType:'text/csv',fileSize:20,
    content:'name,stage\nAda,beta\n'
  });
  assert.deepEqual(result,imported);
  assert.deepEqual(calls,[['/api/imports',{
    format:'csv',fileName:'customers.csv',fileType:'text/csv',fileSize:20,
    content:'name,stage\nAda,beta\n'
  }]]);
});

test('versioned item update sends an optimistic concurrency token', async () => {
  const item={
    id:'item-1',type:'note',title:'Updated plan',content:'Ship the updated plan.',status:'ready',
    createdAt:'2026-09-09T00:00:00Z',updatedAt:'2026-09-14T10:00:00Z',
    currentVersionId:'00000000-0000-0000-0000-000000000002',versionNumber:2,
    extractedFacts:[],relatedItemIds:[]
  };
  const calls=[];
  global.fetch=async(url,options)=>{
    calls.push([url,options.method,JSON.parse(options.body)]);
    return new Response(JSON.stringify(item));
  };
  const result=await provider().updateItem('item-1',{
    type:'note',
    expectedCurrentVersionId:'00000000-0000-0000-0000-000000000001',
    title:' Updated plan ',content:' Ship the updated plan. '
  });
  assert.deepEqual(result,item);
  assert.deepEqual(calls,[['/api/items/item-1','PATCH',{
    expectedCurrentVersionId:'00000000-0000-0000-0000-000000000001',
    title:'Updated plan',content:'Ship the updated plan.'
  }]]);
});

test('daily schedule and status use strict live API contracts', async () => {
  const schedule={enabled:true,timezone:'Europe/Moscow',localTime:'19:00',leadMinutes:30,
    nextRefreshAt:'2026-09-14T15:30:00Z',nextRunAt:'2026-09-14T16:00:00Z',updatedAt:'2026-09-14T10:00:00Z'};
  const daily={localDate:'2026-09-14',timezone:'Europe/Moscow',state:'scheduled',cycleId:'cycle-1',runId:null,
    mode:'scheduled',scheduledFor:'2026-09-14T16:00:00Z',refreshDueAt:'2026-09-14T15:30:00Z',
    sourceSnapshotCount:0,canRequestToday:false,reason:'daily_limit',sync:{status:'not_started',github:{
      connected:false,ingestionSupported:false,status:'not_connected'}}};
  const calls=[];
  global.fetch=async(url,options={})=>{
    calls.push([url,options.method??'GET',options.body]);
    return new Response(JSON.stringify(url.endsWith('daily-status')?daily:schedule));
  };
  const api=provider();
  assert.deepEqual(await api.getAnalysisSchedule(),schedule);
  assert.deepEqual(await api.updateAnalysisSchedule({enabled:true,timezone:'Europe/Moscow',localTime:'19:00'}),schedule);
  assert.deepEqual(await api.getDailyAnalysisStatus(),daily);
  assert.deepEqual(calls.map(call=>call.slice(0,2)),[
    ['/api/analysis-schedule','GET'],['/api/analysis-schedule','PUT'],['/api/analysis/daily-status','GET']
  ]);
});

test('mock schedule follows its wall-clock time and leaves manual analysis open before refresh', async () => {
  const mock=new MockDataProvider();
  const target=new Date(Date.now()+2*60*60*1000);
  const localTime=`${String(target.getUTCHours()).padStart(2,'0')}:${String(target.getUTCMinutes()).padStart(2,'0')}`;
  const schedule=await mock.updateAnalysisSchedule({enabled:true,timezone:'UTC',localTime});
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
    .formatToParts(new Date(schedule.nextRunAt));
  const read=type=>parts.find(part=>part.type===type).value;
  assert.equal(`${read('hour')}:${read('minute')}`,localTime);
  assert.equal(new Date(schedule.nextRunAt)-new Date(schedule.nextRefreshAt),30*60*1000);
  const before=await mock.getDailyAnalysisStatus();
  assert.equal(before.state,'available');
  assert.equal(before.canRequestToday,true);
  const run=await mock.startAnalysis('manual-today');
  assert.equal(run.status,'completed');
  const after=await mock.getDailyAnalysisStatus();
  assert.equal(after.mode,'manual');
  assert.equal(after.canRequestToday,false);
});
