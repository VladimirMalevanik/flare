const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const fixture = (patch = {}) => ({ id:'package-1',sourceKind:'obsidian',fileName:'snapshot.zip',fileSize:100,
  status:'queued',phase:'inspect',entryCount:null,supportedCount:0,importedCount:0,skippedCount:0,chunkCount:0,failedCount:0,errorCode:null,retryable:false,...patch });
const jsx = { jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}) };
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node,...nodes(node.props?.children)];
}
function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join(' ');
  return node ? text(node.props?.children) : '';
}
function harness(provider, history = []) {
  let cursor=0;const state=[],effects=[],timers=[],deps=[],cleanups=[];
  provider.getImportCapabilities ??= async()=>({available:true,maxUploadBytes:100000});
  provider.listImportPackages ??= async()=>history;
  const exports={};
  const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/sources/zip-import.tsx'),'utf8'),{
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(code,{exports,AbortController,crypto:{randomUUID:()=> 'request-1'},
    setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){},require(name){
      if(name==='react/jsx-runtime')return jsx;
      if(name==='next/link')return {default:'a'};
      if(name==='@/lib/data')return {dataProvider:provider};
      if(name==='@/i18n/provider')return {useI18n:()=>({t:s=>s,label:s=>s,message:s=>s})};
      if(name==='react')return {
        useState(initial){const i=cursor++;if(!(i in state))state[i]=initial;return[state[i],v=>state[i]=typeof v==='function'?v(state[i]):v];},
        useRef(initial){const i=cursor++;if(!(i in state))state[i]={current:initial};return state[i];},
        useEffect(fn,values){const i=cursor++;if(!deps[i]||values.some((v,j)=>v!==deps[i][j])){effects.push(fn);deps[i]=values;}}
      };
      throw Error(name);
    }});
  function render(){cursor=0;return exports.ZipImport({sourceKind:'obsidian'});}
  return {render,buttons:()=>nodes(render()).filter(n=>n.type==='button'),
    async effects(){for(const fn of effects.splice(0)){const cleanup=fn();if(typeof cleanup==='function')cleanups.push(cleanup);}await new Promise(r=>setImmediate(r));},
    async poll(){for(const fn of timers.splice(0))fn();await new Promise(r=>setImmediate(r));},
    select(file={name:'snapshot.zip',size:100}){nodes(render()).find(n=>n.type==='input').props.onChange({target:{files:[file]}});},
    async click(label){const button=this.buttons().find(n=>text(n)===label);assert.ok(button,label);assert.ok(!button.props.disabled);button.props.onClick();await new Promise(r=>setImmediate(r));},
    dispose(){for(const fn of cleanups.splice(0).reverse())fn();},
    exports};
}

test('upload, finalize, truthful phase/counts, terminal result and paged skips',async()=>{
 const calls=[];
 const provider={async createImportPackage(input){calls.push(['create',input]);return fixture({status:'uploading',phase:'upload'});},
  async uploadImportPackage(id,file,signal){calls.push(['upload',id,file.name,signal.aborted]);return fixture({status:'staged'});},
  async importPackageAction(id,action){calls.push(action);return fixture();},
  async getImportPackage(){return fixture({status:'completed_with_skips',phase:'complete',entryCount:3,supportedCount:2,importedCount:2,skippedCount:1});},
  async getImportPackageReport(id,after){calls.push(['report',after]);return {entries:[{ordinal:after+1,path:after<0?'nested/note.md':'image.png',status:after<0?'published':'skipped',skipReason:after<0?null:'unsupported_format'}],nextCursor:after<0?0:null};}};
 const app=harness(provider);app.render();await app.effects();app.select();await app.click('Import ZIP');
 assert.equal(calls[0][1].requestKey,'request-1');assert.deepEqual(calls[1],['upload','package-1','snapshot.zip',false]);assert.equal(calls[2],'finalize');
 assert.match(text(app.render()),/Inspecting ZIP/);assert.doesNotMatch(text(app.render()),/%/);
 await app.effects();await app.poll();assert.match(text(app.render()),/Imported with skipped files/);assert.match(text(app.render()),/Imported\s*:\s*2/);
 await app.click('View import report');assert.match(text(app.render()),/nested\/note.md/);
 await app.click('More files');assert.match(text(app.render()),/Unsupported file format/);
 assert.ok(nodes(app.render()).some(n=>n.type==='a'&&n.props.href==='/vault'));
});

test('resumes active server job on reload and cancel never finalizes',async()=>{
 const calls=[];const active=fixture({status:'processing',phase:'parse',entryCount:4,supportedCount:1});
 const app=harness({async importPackageAction(id,action){calls.push(action);return fixture({status:'cancelled'});}},[active]);
 app.render();await app.effects();assert.match(text(app.render()),/Reading files/);assert.match(text(app.render()),/Imported\s*:\s*0/);
 await app.click('Cancel import');assert.deepEqual(calls,['cancel']);assert.match(text(app.render()),/Import cancelled/);
});

test('recoverable failed import retries, inspects terminal report and never invents success',async()=>{
 const calls=[];
 const app=harness({async importPackageAction(id,action){calls.push(action);return fixture();},async getImportPackageReport(){return{entries:[],nextCursor:null};}},[fixture({status:'failed',errorCode:'storage_or_worker_unavailable',retryable:true})]);
 app.render();await app.effects();assert.match(text(app.render()),/Import failed/);await app.click('View import report');await app.click('Retry import');assert.deepEqual(calls,['retry']);
});

test('transport failure keeps the same session request key for an uncertain create outcome',async()=>{
 const keys=[];let count=0;
 const app=harness({async createImportPackage(input){keys.push(input.requestKey);if(count++===0)throw Error('offline');return fixture({status:'uploading'});},async uploadImportPackage(){return fixture({status:'staged'});},async importPackageAction(){return fixture();}});
 app.render();await app.effects();app.select();await app.click('Import ZIP');assert.match(text(app.render()),/Import could not continue/);
 await app.click('Import ZIP');assert.deepEqual(keys,['request-1','request-1']);
});

test('provider request sends raw ZIP with cookie, no-store, abort, strict DTO and no demo fallback',async()=>{
 const Module=require('node:module'),resolve=Module._resolveFilename;
 Module._resolveFilename=function(request,parent,...args){return resolve.call(this,request.startsWith('@/')?path.join(__dirname,'../src',request.slice(2)):request,parent,...args);};
 require.extensions['.ts']=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
 const {ApiDataProvider,mapImportPackage}=require('../src/lib/data/api-provider.ts');
 const dto={id:'id',source_kind:'notion',file_name:'a.zip',file_size:4,status:'queued',phase:'inspect',entry_count:null,prepared_count:0,published_count:0,skipped_count:0,chunk_count:0,failed_count:0,error_code:null,retryable:false};
 const provider=new ApiDataProvider({baseUrl:'/api',fallback:new Proxy({}, {get(){throw Error('fallback');}})});
 const file=new Blob(['ZIP!']);const signal=new AbortController().signal;
 global.fetch=async(url,init)=>{assert.equal(url,'/api/imports/packages/id/upload');assert.equal(init.body,file);assert.equal(init.signal,signal);assert.equal(init.headers['Content-Type'],'application/octet-stream');assert.equal(init.credentials,'include');assert.equal(init.cache,'no-store');return new Response(JSON.stringify(dto));};
 assert.equal((await provider.uploadImportPackage('id',file,signal)).sourceKind,'notion');
 for(const changed of [{status:'unknown'},{prepared_count:-1},{entry_count:'40'},{retryable:'false'}])assert.throws(()=>mapImportPackage({...dto,...changed}));
 global.fetch=async()=>new Response('{}',{status:503});await assert.rejects(provider.createImportPackage({}));
 Module._resolveFilename=resolve;
});

test('deployment without a configured adapter disables ZIP submission truthfully',async()=>{
 const app=harness({async getImportCapabilities(){return{available:false,maxUploadBytes:null};}});
 app.render();await app.effects();app.select();
 assert.match(text(app.render()),/ZIP import is unavailable in this environment/);
 assert.ok(app.buttons().find(n=>text(n)==='Import ZIP').props.disabled);
});

test('double click and unmount during creation cannot upload or finalize twice',async()=>{
 let resolveCreate;const calls=[];
 const app=harness({createImportPackage(){calls.push('create');return new Promise(resolve=>resolveCreate=resolve);},async uploadImportPackage(){calls.push('upload');return fixture({status:'staged'});},async importPackageAction(){calls.push('finalize');return fixture();}});
 app.render();await app.effects();app.select();
 const button=app.buttons().find(n=>text(n)==='Import ZIP');button.props.onClick();button.props.onClick();
 assert.deepEqual(calls,['create']);
 app.dispose();resolveCreate(fixture({status:'uploading'}));await new Promise(r=>setImmediate(r));
 assert.deepEqual(calls,['create']);
});
