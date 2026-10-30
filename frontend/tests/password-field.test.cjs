const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');
const jsx = { jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props}) };
const nodes = n => !n || typeof n !== 'object' ? [] : Array.isArray(n) ? n.flatMap(nodes) : [n, ...nodes(n.props?.children)];
function field(locale='en', props={}) {
  let visible=false;
  const exports={};
  const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/components/password-field.tsx'),'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022},
  }).outputText;
  vm.runInNewContext(code,{exports,require(name){
    if(name==='react/jsx-runtime')return jsx;
    if(name==='react')return {useState:()=>[visible,value=>{visible=typeof value==='function'?value(visible):value;}]};
    if(name==='@/components/icons')return {Icon:'icon'};
    if(name==='@/i18n/provider')return i18nMock(locale);
    throw Error(name);
  }});
  return {render(){return nodes(exports.PasswordField({id:'test-password',label:'Password',name:'password',autoComplete:'new-password',required:true,maxLength:128,defaultValue:'synthetic password',...props}));}};
}
for(const locale of ['en','es'])test('show/hide preserves field semantics and uses localized actions ('+locale+')',()=>{
  const h=field(locale);
  const read=()=>{const all=h.render();return {input:all.find(n=>n.type==='input'),button:all.find(n=>n.type==='button'),label:all.find(n=>n.type==='label'),icon:all.find(n=>n.type==='icon')};};
  let {input,button,label,icon}=read();
  assert.equal(input.props.type,'password');assert.equal(label.props.htmlFor,input.props.id);
  assert.equal(button.props['aria-controls'],input.props.id);assert.equal(button.props.type,'button');
  assert.equal(button.props['aria-label'],locale==='en'?'Show password':'Mostrar contraseña');assert.equal(icon.props.name,'eye');
  let prevented=false;button.props.onPointerDown({preventDefault(){prevented=true;}});assert.equal(prevented,true);
  const original=input.props;
  button.props.onClick();({input,button,icon}=read());
  assert.equal(input.props.type,'text');assert.equal(icon.props.name,'eye-off');
  assert.equal(button.props['aria-label'],locale==='en'?'Hide password':'Ocultar contraseña');
  for(const key of ['id','name','autoComplete','required','maxLength','defaultValue'])assert.equal(input.props[key],original[key]);
  assert.equal(input.props.spellCheck,false);assert.equal(input.props.autoCapitalize,'none');
  button.props.onClick();assert.equal(read().input.props.type,'password');
});
test('confirmation visibility is independent and pending forms disable both controls',()=>{
  const first=field(),confirmation=field('en',{id:'confirmation',name:'confirmPassword'});
  first.render().find(n=>n.type==='button').props.onClick();
  assert.equal(first.render().find(n=>n.type==='input').props.type,'text');
  assert.equal(confirmation.render().find(n=>n.type==='input').props.type,'password');
  const disabled=field('en',{disabled:true,'aria-describedby':'help'}).render();
  assert.equal(disabled.find(n=>n.type==='input').props.disabled,true);
  assert.equal(disabled.find(n=>n.type==='button').props.disabled,true);
  assert.equal(disabled.find(n=>n.type==='input').props['aria-describedby'],'help');
});
