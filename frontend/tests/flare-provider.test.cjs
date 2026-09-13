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
