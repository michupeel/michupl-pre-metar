// Synthetic DOM contract check; this is NOT rendered-browser verification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) {this.tag=tag; this.children=[]; this.textContent=''; this.attrs={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items; this.textContent='';}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this['on'+k]=v;}
  before(e){this.inserted=e;}
  get text(){return this.textContent+this.children.map(c=>c.text??c.textContent??'').join(' ');}
}
(async()=>{
  const footer=new Element('footer'), intervals=[];
  const document={createElement:t=>new Element(t),createElementNS:(ns,t)=>{assert.equal(ns,'http://www.w3.org/2000/svg');return new Element(t);},querySelector:s=>s==='.footer'?footer:null,addEventListener:(k,f)=>{document.ready=f;}};
  const at=Date.now(), stamp=new Date(at-60000).toISOString();
  const window={dashboard:{state:{live:true,hoverAt:null}}};
  const catalog={published_at:stamp,mode:'SYNTHETIC_TEST_ONLY',status:'TEST',version:'test',summary:{entries:1,paired_pre_execution:0,controls:0},entries:[{trade_id:'test',source_trade_timestamp:stamp,original_first_detection:stamp,station:'<img onerror=unsafe>',price:'0.94',books:{no:{history:[],pre_execution:{spread:null,imbalance:0},price_changes:{}},yes:{history:[]}}}]};
  const context={document,window,console,AbortController,Date,setTimeout,clearTimeout,setInterval:f=>{intervals.push(f);return 1;},fetch:async()=>({ok:true,json:async()=>catalog})};
  vm.runInNewContext(fs.readFileSync('src/premetar/dashboard/static/entry_reconstruction.js','utf8'),context);
  document.ready();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(footer.inserted.id,'entry-reconstruction-panel');
  assert.match(footer.inserted.text,/SYNTHETIC_TEST_ONLY/);
  assert.match(footer.inserted.text,/imbalance 0/);
  assert.match(footer.inserted.text,/<img onerror=unsafe>/); // literal text, no HTML parser
  window.dashboard.state={live:false,replayAt:at-120000};intervals[1]();
  assert.match(footer.inserted.text,/raport powstał później/);
  assert.doesNotMatch(footer.inserted.text,/onerror/);
  console.log('EXP0018 synthetic DOM contracts PASS; rendered browser still requires separate QA.');
})().catch(error=>{console.error(error);process.exitCode=1;});
