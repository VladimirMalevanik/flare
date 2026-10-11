const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const exportsObject={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/data/import-request.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,
  {exports:exportsObject,AbortController,setTimeout,clearTimeout});
const {importRequest}=exportsObject;

test('a hung request stops at its deadline even if the transport ignores abort',async()=>{
 let signal;
 await assert.rejects(importRequest(s=>{signal=s;return new Promise(()=>{});},undefined,15),e=>e.code==='import_request_timeout');
 assert.equal(signal.aborted,true);
});
test('caller cancellation immediately aborts a hung request and late success is ignored',async()=>{
 const controller=new AbortController();let finish,signal;
 const pending=importRequest(s=>{signal=s;return new Promise(resolve=>finish=resolve);},controller.signal,1000);
 await new Promise(r=>setImmediate(r));controller.abort();
 await assert.rejects(pending,e=>e.code==='import_request_aborted');assert.equal(signal.aborted,true);
 finish('late result');await new Promise(r=>setImmediate(r));
});
test('already cancelled requests never call the transport',async()=>{
 const controller=new AbortController();controller.abort();let called=false;
 await assert.rejects(importRequest(async()=>{called=true;},controller.signal),e=>e.code==='import_request_aborted');
 assert.equal(called,false);
});
test('deadline includes response-body parsing, not just response headers',async()=>{
 await assert.rejects(importRequest(async()=>{await Promise.resolve();return new Promise(()=>{});},undefined,15),e=>e.code==='import_request_timeout');
});
test('success and transport failure release timers and caller listeners',async()=>{
 const controller=new AbortController();let removed=0;
 const remove=controller.signal.removeEventListener.bind(controller.signal);
 controller.signal.removeEventListener=(...args)=>{removed++;return remove(...args);};
 assert.equal(await importRequest(async()=>42,controller.signal,1000),42);
 const cause=new Error('synthetic transport');
 await assert.rejects(importRequest(async()=>{throw cause;},controller.signal,1000),e=>e===cause);
 assert.equal(removed,2);
});
