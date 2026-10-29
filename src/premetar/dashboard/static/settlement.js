/* Public backfilled labels, isolated from production forecasts and strategy gates. */
(() => {
  'use strict';
  const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=x=>x==null?'—':Number(x).toLocaleString('pl-PL',{maximumFractionDigits:2});
  const names={VERIFIED_SOURCE_AND_MARKET:'ŹRÓDŁO + RYNEK',VERIFIED_MARKET_ONLY:'TYLKO RYNEK',SOURCE_RECONSTRUCTED:'REKONSTRUKCJA ŹRÓDŁA',CONFLICT:'KONFLIKT',INSUFFICIENT_EVIDENCE:'BRAK DOWODÓW'};
  let catalog=null,busy=false,last=0,rendered='';
  function render(){
    if(!catalog)return;
    const state=window.dashboard?.state;
    const cutoff=state?.live?(state.hoverAt??Date.now()):(state?.replayAt??Date.parse(state?.data?.cutoff));
    const known=Number.isFinite(cutoff)&&Date.parse(catalog.published_at)<=cutoff;
    const key=`${catalog.published_at}|${known}`;
    if(rendered===key)return;rendered=key;
    const body=document.getElementById('settlement-content');
    document.getElementById('settlement-cutoff').textContent=`Audyt pozyskany: ${new Date(catalog.published_at).toLocaleString('pl-PL',{timeZone:'Europe/Warsaw'})} Europe/Warsaw`;
    if(!known){body.innerHTML='<p class="empty">W wybranej chwili ten audyt historyczny nie był jeszcze dostępny. Później pozyskanych etykiet nie pokazujemy jako wiedzy z tamtego momentu.</p>';return;}
    const calibration=catalog.calibration||{},p=calibration.progress||{};
    const targets=(catalog.targets||[]).filter(t=>Date.parse(t.target_available_at)<=cutoff);
    const summaries=(calibration.summary||[]).filter(r=>r.checkpoint_local==='D-1 12:00 Europe/Warsaw'&&r.target_classification==='VERIFIED_SOURCE_AND_MARKET');
    body.innerHTML=`<div class="d1-metrics"><div class="d1-metric"><label>Zweryfikowane dni / wymagane</label><strong>${num(p.verified_days)} / ${num(p.required_training_days)}</strong><span class="micro">Dodatkowo ${num(p.required_independent_validation_days)} niezależnych dni walidacji</span></div><div class="d1-metric"><label>Ściśle zweryfikowane pary D−1</label><strong>${num(calibration.strict_independent_model_day_pairs)}</strong><span class="micro">Oryginalny czas dostępności prognoz pozostaje nieznany</span></div></div>
    <p class="micro">Etykiety pozyskane retrospektywnie. Zgodność dzisiejszego oficjalnego archiwum z rozstrzygnięciem rynku nie jest archiwalnym zrzutem źródła z chwili rozliczenia. CALIBRATION PENDING — brak nowych prawdopodobieństw lub wejść.</p>
    <div class="table-scroll"><table class="data-table d1-table"><thead><tr><th>Dzień</th><th>Max METAR kwalifikowany</th><th>Integer</th><th>Wygrany przedział</th><th>Weryfikacja</th><th>Reguły i źródło</th></tr></thead><tbody>${targets.map(t=>`<tr><td>${esc(t.settlement_date)}</td><td>${num(t.qualifying_maximum_c)}°C</td><td>${num(t.integer_outcome)}</td><td>${esc(t.winning_bracket??t.market_result?.winning_label)}</td><td>${esc(names[t.classification]??t.classification)}<span class="secondary">Stan w chwili rozliczenia: ${esc(t.historical_source_state_at_resolution??'NIEZARCHIWIZOWANY')}</span></td><td>${esc(t.rules?.source_family)}<details><summary>Dowody</summary><pre>${esc(JSON.stringify(t,null,2))}</pre></details></td></tr>`).join('')}</tbody></table></div>
    <h3>RAW błędy modeli — D−1 godz. 12:00</h3><p class="micro">APPROXIMATE REPLAY: dostępność init+6h jest założeniem. Poniższe błędy dotyczą maksimum punktów godzinowych, a nie dobowego Tmax API. Kolejne checkpointy nie zwiększają liczby niezależnych dni.</p>
    <div class="table-scroll"><table class="data-table d1-table"><thead><tr><th>Model</th><th>Dni</th><th>MAE °C</th><th>Bias °C</th><th>Zgodność integer</th></tr></thead><tbody>${summaries.map(r=>`<tr><td>${esc(r.model)}</td><td>${num(r.independent_days)}</td><td>${num(r.hourly_point_MAE_c)}</td><td>${num(r.hourly_point_bias_c)}</td><td>${r.hourly_point_integer_accuracy==null?'—':num(r.hourly_point_integer_accuracy*100)+'%'}</td></tr>`).join('')}</tbody></table></div>
    <details><summary>Prognoza, horyzont i błąd dla każdego dnia</summary><div class="table-scroll"><table class="data-table d1-table"><thead><tr><th>Dzień</th><th>Model</th><th>Checkpoint</th><th>Prognoza</th><th>Lead init → dzień</th><th>Błąd</th><th>Dostępność</th></tr></thead><tbody>${(calibration.records||[]).map(r=>`<tr><td>${esc(r.settlement_date)}</td><td>${esc(r.model)}</td><td>${esc(r.checkpoint_local)}</td><td>${num(r.hourly_point_max_c)}°C</td><td>${num(r.forecast_lead_to_day_start_hours)} h</td><td>${num(r.hourly_point_error_c)}°C</td><td>${esc(r.availability_class)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  async function refresh(){
    if(busy||Date.now()-last<60000)return;
    busy=true;last=Date.now();
    try {const r=await fetch('/static/settlement_history.json',{cache:'no-store'});if(!r.ok)throw new Error('Brak audytu');catalog=await r.json();render();}
    catch{document.getElementById('settlement-content').textContent='Audyt jeszcze niedostępny. Brak danych nie oznacza zerowego Tmax.';}
    finally{busy=false;}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const panel=document.createElement('section');panel.className='panel d1-panel';panel.id='settlement-history-panel';
    panel.innerHTML='<div class="panel-heading"><div><span class="eyebrow">EXP-0016.1 / ETYKIETY HISTORYCZNE</span><h2>EPWA — historia rozliczeń i kalibracja</h2></div><span class="tag amber">BEZ PROMOCJI STRATEGII</span></div><p id="settlement-cutoff" class="micro"></p><div id="settlement-content">Oczekiwanie na audyt…</div>';
    document.getElementById('d1-panel')?.after(panel);refresh();setInterval(()=>{refresh();render();},1000);
  });
})();
