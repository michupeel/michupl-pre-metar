// Synthetic DOM contract check, not a rendered-browser/screenshot substitute.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
class Element{constructor(tag){this.tag=tag;this.children=[];this.textContent='';}append(...e){this.children.push(...e);}appendChild(e){this.append(e);}prepend(e){this.children.unshift(e);}before(e){this.inserted=e;}replaceChildren(...e){this.children=e;this.textContent='';}setAttribute(){}addEventListener(k,f){this['on'+k]=f;}get text(){return this.textContent+this.children.map(c=>c.text??'').join(' ');}}
(async()=>{
 const footer=new Element('footer'),timers=[];const at=Date.now();const window={dashboard:{state:{live:true}}};
 const document={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),querySelector:s=>s==='.footer'?footer:null,addEventListener:(_,f)=>document.ready=f};
 const stamp=new Date(at-60000).toISOString();
 const data={published_at:stamp,mode:'SYNTHETIC_ONLY',session:{contracts:4,tokens:8},summary:{surges:0,entries:0,supported_fills:0,matched_controls:null},events:[],wellington:{classification:'TEST_NOT_OBSERVED',trigger_causality:'UNKNOWN',target:stamp,timeline:[]}};
 const context={document,window,Date,console,AbortController,setTimeout,clearTimeout,setInterval:f=>{timers.push(f);return 1;},fetch:async u=>({ok:!u.endsWith('_live.json'),json:async()=>data})};
 for(const file of ['surge_metric.js','surge_hunter.js'])vm.runInNewContext(fs.readFileSync('src/premetar/dashboard/static/'+file,'utf8'),context);
 assert.match(window.michuplSurgeMetric('literal <img>',0).text,/literal <img>\s*0/);
 assert.match(window.michuplSurgeMetric('Unknown',null).text,/Unknown\s*—/);
 document.ready();await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 assert.equal(footer.inserted.id,'surge-hunter-panel');assert.match(footer.inserted.text,/SYNTHETIC_ONLY/);
 window.dashboard.state={live:false,replayAt:at-120000};timers[1]();
 assert.match(footer.inserted.text,/Późniejsza wiedza niedostępna/);assert.doesNotMatch(footer.inserted.text,/TEST_NOT_OBSERVED/);
 console.log('Surge Hunter synthetic DOM PASS; browser QA remains independent.');
})().catch(e=>{console.error(e);process.exitCode=1;});
