/* EXP0018: Qwen I4 layout adapted after causal/SVG review; read-only. */
(() => {
  'use strict';
  const ns = 'http://www.w3.org/2000/svg';
  const node = (tag, text) => { const e = document.createElement(tag); if (text != null) e.textContent = String(text); return e; };
  const valid = v => v != null && Number.isFinite(Date.parse(v));
  const fmt = v => valid(v) ? new Date(v).toLocaleString('pl-PL', {timeZone:'Europe/Warsaw', timeZoneName:'short'}) : '—';
  const number = v => typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('pl-PL', {maximumFractionDigits:4}) : '—';
  const cutoff = () => {
    const s = window.dashboard?.state;
    if (!s) return NaN;
    return s.live ? (s.hoverAt ?? Date.now()) : (s.replayAt ?? Date.parse(s.data?.cutoff));
  };
  document.addEventListener('DOMContentLoaded', () => {
    const panel = node('section'); panel.id = 'entry-reconstruction-panel'; panel.className = 'panel entry-timing-panel';
    panel.append(node('span','EXP-0018 / DOWODY I LUKI'),node('h2','HIGH TEMPTATION — ENTRY RECONSTRUCTION'));
    const stamp = node('p'); const select = node('select'); select.setAttribute('aria-label','Transakcja EXP-0018');
    const body = node('div'); panel.append(stamp, select, body);
    const footer = document.querySelector('.footer');
    if (footer) footer.before(panel); else document.querySelector('.shell')?.append(panel);
    let catalog = null, selected = '', busy = false, fetchError = false, rendered = '';

    function timeline(entry) {
      const wrap = node('figure'); wrap.append(node('figcaption','Oś ±5 min: wykonanie ≠ wykrycie ≠ publikacja METAR. Punkty oznaczają zapisane snapshoty, nie ciągłą cenę.'));
      const base = Date.parse(entry.source_trade_timestamp);
      if (!Number.isFinite(base)) return wrap;
      const svg = document.createElementNS(ns,'svg'); svg.setAttribute('viewBox','0 0 1000 200'); svg.setAttribute('role','img'); svg.setAttribute('aria-label','Zapisane ceny YES i NO oraz oddzielne zegary');
      const add = (tag, attrs, text) => {const n=document.createElementNS(ns,tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v))); if(text!=null)n.textContent=text; svg.append(n); return n;};
      const x = t => 55 + ((Date.parse(t)-base)/1000+300)*1.48;
      const line = (t,label,color,y) => { if(!valid(t) || Math.abs(Date.parse(t)-base)>300000)return; const p=x(t); add('line',{x1:p,y1:15,x2:p,y2:160,stroke:color,'stroke-dasharray':'4 3'});add('text',{x:Math.max(55,Math.min(820,p)),y,fill:color,'font-size':12},label);};
      add('line',{x1:55,y1:160,x2:943,y2:160,stroke:'#788898'});
      [-300,-60,0,60,300].forEach(s=>add('text',{x:55+(s+300)*1.48,y:193,fill:'#a4b7c8','font-size':12},`${s}s`));
      [0,.5,1].forEach(p=>add('text',{x:5,y:160-p*135,fill:'#a4b7c8','font-size':12},p.toFixed(2)));
      for(const [side,color] of [['no','#46d1c5'],['yes','#e9b35d']]) for(const point of entry.books?.[side]?.history ?? []) {
        if(!valid(point.received_at)||Math.abs(Date.parse(point.received_at)-base)>300000)continue;
        const bid=Number(point.bids?.[0]?.price),ask=Number(point.asks?.[0]?.price);
        if(!Number.isFinite(bid)||!Number.isFinite(ask))continue;
        const dot=add('circle',{cx:x(point.received_at),cy:160-(bid+ask)/2*135,r:3,fill:color});
        const tip=document.createElementNS(ns,'title');tip.textContent=`${side.toUpperCase()} ${fmt(point.received_at)} bid ${bid} ask ${ask}`;dot.append(tip);
      }
      line(entry.source_trade_timestamp,'Wykonanie (dokładność źródła 1s)','#ef889a',12);
      line(entry.original_first_detection,'Wykrycie portfela','#46d1c5',176);
      line(entry.metar_schedule?.nearest_nominal_time,'Nominalny METAR, nie publikacja','#c7b4f6',28);
      line(entry.weather_at_execution?.metar?.collector_receive_time,'Odbiór ostatniego znanego METAR','#78aceb',44);
      wrap.append(svg,node('p','YES: złoty · NO: turkusowy. Brak punktów = brak dowodów; nie zero.'));return wrap;
    }

    function render(force=false) {
      const at=cutoff(), published=Date.parse(catalog?.published_at), known=Number.isFinite(at)&&Number.isFinite(published)&&published<=at;
      const key=`${known}|${selected}|${catalog?.published_at}|${fetchError}|${Math.floor(Date.now()/60000)}`;
      if(!force&&rendered===key)return;rendered=key;body.replaceChildren();select.replaceChildren();
      if(!known){stamp.textContent=catalog?'Ten raport powstał później niż wybrany czas. Nie pokazujemy późniejszej wiedzy.':'Brak eksportu EXP-0018. Brak dowodów nie oznacza braku wejść.';select.disabled=true;return;}
      const entries=(catalog.entries??[]).slice(0,30);select.disabled=!entries.length;
      for(const e of entries){const o=node('option',`${fmt(e.source_trade_timestamp)} · ${e.station??'?'} · ${e.price??'—'}`);o.value=e.trade_id;select.append(o);}
      if(!entries.some(e=>e.trade_id===selected))selected=entries[0]?.trade_id??'';select.value=selected;
      stamp.textContent=`${catalog.mode} · raport ${fmt(catalog.published_at)} · wejścia ${catalog.summary?.entries??'—'} · para YES/NO przed wykonaniem ${catalog.summary?.paired_pre_execution??'—'} · kontrole ${catalog.summary?.controls??'—'} · ${catalog.status??'UNKNOWN'}${Date.now()-published>120000?' · RAPORT NIEŚWIEŻY':''}${fetchError?' · BŁĄD ODCZYTU':''}`;
      body.append(node('p','Tylko rekonstrukcja dowodów. Reguła wejścia nie została zamrożona ani uruchomiona. Brak realnych zleceń; snapshot i cena 0,99 nie dowodzą naszego fillu.'));
      const e=entries.find(e=>e.trade_id===selected);if(!e){body.append(node('p','Brak kwalifikujących się transakcji w tej próbie.'));return;}
      const f=e.books?.no?.pre_execution??{}, changes=e.books?.no?.price_changes??{};
      body.append(node('p',`Stacja ${e.station??'NIEZNANA'} · wykonanie ${fmt(e.source_trade_timestamp)} · wykrycie ${fmt(e.original_first_detection)} · NO spread ${number(f.spread)} · imbalance ${number(f.imbalance)} · Δ5s ${number(changes.change_5s)} · Δ30s ${number(changes.change_30s)}`));
      body.append(timeline(e));
      const details=node('details');details.append(node('summary','Pełne zegary, pokrycie, SELL i ograniczenia'),node('pre',JSON.stringify(e,null,2)));body.append(details);
    }
    select.addEventListener('change',()=>{selected=select.value;render(true);});
    async function refresh(){if(busy)return;busy=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);try{const response=await fetch('/static/entry_reconstruction_summary.json',{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error('unavailable');const data=await response.json();if(!Array.isArray(data.entries)||!valid(data.published_at))throw new Error('invalid');catalog=data;fetchError=false;}catch{fetchError=true;}finally{clearTimeout(timer);busy=false;render(true);}}
    refresh();setInterval(refresh,60000);setInterval(()=>render(),1000);
  });
})();
