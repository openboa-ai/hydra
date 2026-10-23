/** Execute the real app entry with an inert DOM and synthetic native bridge. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { Script } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { setImmediate as settle } from 'node:timers/promises';
import { JSDOM } from 'jsdom';
import ts from 'typescript';

const root = fileURLToPath(new URL('../', import.meta.url));
export const sourceFrame = JSON.parse(readFileSync(resolve(root, '../../tests/fixtures/control-v3/inputs.json'), 'utf8')).frame;
const uid = (n:number) => `00000000-0000-4000-8000-${n.toString(16).padStart(12,'0')}`;
export async function flush() { for (let n=0;n<6;n++) await settle(); }

export async function appFixture(frame=structuredClone(sourceFrame)) {
  const dom = new JSDOM(readFileSync(resolve(root,'index.html'),'utf8'), {
    url:'https://hydra.fixture.invalid/', runScripts:'outside-only',
  });
  const {window}=dom;
  const calls:{method:string;args:Record<string,unknown>}[]=[];
  const intervals:(()=>void)[]=[];
  let sequence=0, nonce=100, now=Date.parse(frame.assembled_at);
  const api={binding:frame.binding_epoch,frame,fail:false,
    deferred:null as null | ((args:Record<string,unknown>,sequence:number)=>Promise<unknown>|undefined),
    beforeInvoke:null as null | ((method:string,args:Record<string,unknown>)=>unknown),
    calls,intervals};
  window.Date.now=()=>now;
  Object.defineProperty(window.crypto,'randomUUID',{value:()=>uid(++nonce)});
  Object.assign(window,{structuredClone,TextEncoder,TextDecoder});
  window.setInterval=((callback:()=>void)=>{intervals.push(callback);return intervals.length;}) as typeof window.setInterval;
  window.fetch=()=>{throw Error('No network access in the DOM fixture');};
  function cached(args:Record<string,unknown>,value=api.frame,version=++sequence) {
    const payload=structuredClone(value);
    payload.binding_epoch=api.binding;
    payload.request_id=args.requestId;
    return {payload:JSON.stringify(payload),age_ms:0,cached:false,stale:false,sequence:version,
      read_context:{scope:'fixture:registered-read',sequence:1}};
  }
  const invoke=async(method:string,args:Record<string,unknown>={})=>{
    calls.push({method,args:structuredClone(args)});
    const override=api.beforeInvoke?.(method,args);
    if(override!==undefined)return await override;
    if(method==='projection_binding')return api.binding;
    if(method==='projection_clock_resumed')return null;
    if(method==='projection_status'){
      if(args.epoch!==api.binding)throw {code:'read_binding_mismatch'};
      if(api.fail)throw {code:'backend_unavailable',message:'PRIVATE_PROVIDER_CANARY'};
      const current=++sequence;
      const pending=api.deferred?.(args,current);
      return pending===undefined?cached(args,api.frame,current):await pending;
    }
    if(method==='open_record')return null;
    if(method==='status')return {
      schema_version:2,observed_at:new Date(now).toISOString(),host_alias:'Fixture host',revision:4,
      runtime:{identity_schema:1,package:'openboa-hydra-sdlc',version:'0.2.1',code_digest:'a'.repeat(64),
        code_digest_scope:'package_sources_at_startup',config_digest:'b'.repeat(64),
        control_binding_digest:'c'.repeat(64),identity_reason:null},
      global_mode:'paused',gate_status:'blocked',gate_reason:'host_paused',native_turn_control:'unsupported',
      execution:{state:'unknown',active_count:null,reason:'native_ownership_unconfirmed'},
      coverage:{state:'unverified',reason:'schedule_coverage_unverified'},can_quit:false,
      quit_reason:'schedule_coverage_unverified',remote:{state:'not_requested',observed_at:null},
      projects:[],request:null,
    };
    throw Error(`Unexpected bridge operation: ${method}`);
  };
  const context=dom.getInternalVMContext();
  const modules=new Map<string,{exports:Record<string,unknown>}>();
  function load(path:string):Record<string,unknown>{
    if(path.endsWith('.css'))return {};
    const found=modules.get(path);if(found)return found.exports;
    const module={exports:{}};modules.set(path,module);
    const code=ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{
      target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,
    }}).outputText;
    const require=(name:string)=>{
      if(name==='@tauri-apps/api/core')return {invoke};
      if(name==='@tauri-apps/api/event')return {listen:async()=>()=>{}};
      assert.ok(name.startsWith('.'),`Only the actual app's local imports are permitted: ${name}`);
      return load(resolve(dirname(path),name));
    };
    new Script(`(function(require,module,exports){\n${code}\n})`,{filename:path})
      .runInContext(context)(require,module,module.exports);
    return module.exports;
  }
  load(resolve(root,'src/main.ts'));
  await flush();
  const result={...api,api,dom,window,document:window.document,
    cached,flush,advance:(milliseconds:number)=>{now+=milliseconds;},close:()=>window.close(),
    lifecycle:()=>window.document.querySelector<HTMLElement>('[aria-label="Work lifecycle"]'),
    click:async(label:string)=>{
      const scope=window.document.querySelector<HTMLElement>('[aria-label="Work lifecycle"]');
      assert.ok(scope,'The running app must expose its workflow lifecycle view');
      const button=[...scope.querySelectorAll<HTMLButtonElement>('button')].find(node=>node.getAttribute('aria-label')===label);
      assert.ok(button,`The actual workflow view must offer ${label}`);
      assert.equal(button.disabled,false,`${label} must remain usable`);
      button.click();await flush();
    },
  };
  return result;
}

export function noMutations(calls:{method:string}[]) {
  assert.ok(calls.every(call=>['status','projection_binding','projection_status',
    'projection_clock_resumed','open_record'].includes(call.method)),
  'Rendering, reading and selection cannot dispatch a control/workflow/native effect');
}
