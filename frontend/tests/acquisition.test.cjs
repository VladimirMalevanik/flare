const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const vm = require('node:vm');
function moduleWith(context = {}) {
 const exports = {};
 const consent = {};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/telemetry/consent.ts','utf8'), {
 compilerOptions:{ module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022 },
 }).outputText,{exports:consent});
 vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/auth/acquisition.ts','utf8'), {
 compilerOptions:{ module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022 },
 }).outputText,{exports,URL,AbortSignal,require:()=>consent,...context}); return exports;
}
const policy={enabled:true,eligibility:'explicit-opt-in',revision:'x-launch-2026-10-v1',noticeId:'measurement-x-v1',cookieSeconds:604800};
test('landing fields are minimized, conflict/encoded/oversized tokens discarded',()=>{
 const {landingTouch}=moduleWith();
 const touch=landingTouch('https://flare.invalid/register?utm_source=ALPHA&password=secret#secret','https://example.org/private?email=secret');
 assert.deepEqual(JSON.parse(JSON.stringify(touch)),{landing_route:'/register',utm_source:'alpha',referrer_domain:'example.org'});
 for(const query of ['utm_source=a&utm_source=b','utm_source=%2561','%75tm_source=a','utm_source='+ 'a'.repeat(81)])
 assert.equal(landingTouch('https://flare.invalid/?'+query,''),null);
 assert.equal(landingTouch('https://flare.invalid/vault?item=private',''),null);
 assert.equal(landingTouch('https://flare.invalid/','https://flare.invalid/private').referrer_domain,undefined);
});
test('off policy/storage denial/outage never collect or block navigation',async()=>{
 let calls=0;
 const off=moduleWith({fetch:async()=>{calls++;return {ok:true,json:async()=>({enabled:false})}}});
 await off.captureAcquisition('/api'); assert.equal(calls,1);
 const outage=moduleWith({fetch:async()=>{throw Error('synthetic')}});await outage.captureAcquisition('/api');
 const denied=moduleWith({fetch:async()=>({ok:true,json:async()=>policy}),sessionStorage:{getItem(){throw Error('denied')}}});
 await denied.captureAcquisition('/api');
});
test('explicit opt-in collects one bounded touch without a durable client queue',async()=>{
 const calls=[];
 const m=moduleWith({fetch:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>policy}},
 sessionStorage:{getItem:key=>key==='flare_measurement_opt_in'?policy.revision:null},window:{location:{href:'https://flare.invalid/register?utm_source=alpha&email=private'}},document:{referrer:''}});
 await m.captureAcquisition('/api');assert.equal(calls.length,2);
 const payload=JSON.parse(calls[1][1].body);assert.equal(payload.touch.utm_source,'alpha');assert.equal(payload.touch.email,undefined);
});
test('automatic detail hydration does not record a voluntary inspection',()=>{
 const source=fs.readFileSync('src/features/insights/insights-page.tsx','utf8');
 const effect=source.slice(source.indexOf('if (!detailId) return'),source.indexOf('const visible ='));
 assert.doesNotMatch(effect,/recordFlareView\(/);
 assert.match(source,/recordFlareView\(id\)/);
 assert.match(source,/eventType: "voluntary_inspection"/);
});
