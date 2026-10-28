/* Read-only EXP0014/15 presentation. No order or external-provider API exists here. */
(() => {
  'use strict';
  const TZ = 'Europe/Warsaw';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const number = (value, digits = 2) => finite(value) ? Number(value).toLocaleString('pl-PL', {minimumFractionDigits:digits, maximumFractionDigits:digits}) : '—';
  const dollars = value => finite(value) ? `${number(value)} USD` : 'NIEIDENTYFIKOWALNY';
  const count = value => finite(value) ? number(value, 0) : '—';
  const ratio = value => finite(value) ? `${number(Number(value) * 100, 1)}%` : '—';
  const utc = value => typeof value === 'number' ? value : Date.parse(value || '');
  const local = value => Number.isFinite(utc(value)) ? new Intl.DateTimeFormat('pl-PL', {timeZone:TZ, day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', timeZoneName:'shortOffset', hourCycle:'h23'}).format(new Date(utc(value))) : '—';
  const state = {data:null, inflight:false, requestKey:'', lastAttempt:0, chart:null, events:new Map(), apiError:false};
  const words = {
    'ON TRACK':'ZGODNIE Z PROGNOZĄ', 'ON_TRACK':'ZGODNIE Z PROGNOZĄ',
    'SLIGHTLY COLDER':'NIECO CHŁODNIEJ', 'COLDER':'CHŁODNIEJ', 'SIGNIFICANTLY COLDER':'ZNACZNIE CHŁODNIEJ',
    'SLIGHTLY HOTTER':'NIECO CIEPLEJ', 'HOTTER':'CIEPLEJ', 'SIGNIFICANTLY HOTTER':'ZNACZNIE CIEPLEJ',
    'INSUFFICIENT DATA':'NIEWYSTARCZAJĄCE DANE', 'STALE DATA':'NIEŚWIEŻE DANE',
    'WARMING AS EXPECTED':'OCIEPLENIE ZGODNE Z PROGNOZĄ', 'WARMING SLOWER':'OCIEPLENIE WOLNIEJSZE', 'WARMING FASTER':'OCIEPLENIE SZYBSZE',
    'COOLING AS EXPECTED':'OCHŁODZENIE ZGODNE Z PROGNOZĄ', 'COOLING SLOWER':'OCHŁODZENIE WOLNIEJSZE', 'COOLING FASTER':'OCHŁODZENIE SZYBSZE',
    'TREND UNCERTAIN':'TREND NIEPEWNY', 'MINOR DEVIATION':'MAŁE ODCHYLENIE', 'FORECAST AT RISK':'PROGNOZA ZAGROŻONA',
    'FORECAST HIGH RISK':'WYSOKIE RYZYKO PROGNOZY', 'FORECAST RECOVERING':'POWRÓT DO PROGNOZY',
    'MORE LOW CLOUD THAN EXPECTED':'WIĘCEJ NISKICH CHMUR', 'LESS LOW CLOUD THAN EXPECTED':'MNIEJ NISKICH CHMUR',
    'UNEXPECTED OVERCAST':'NIEOCZEKIWANE ZACHMURZENIE CAŁKOWITE', 'FORECAST LOW CLOUD NOT OBSERVED':'NISKICH CHMUR NIE ZGŁOSZONO',
    'BROADLY CONSISTENT':'OGÓLNIE ZGODNE', 'CONSISTENT':'OGÓLNIE ZGODNE', 'UNKNOWN':'NIEZNANE',
    'SIGNAL ONLY':'TYLKO SYGNAŁY', 'NOT IDENTIFIABLE':'NIEIDENTYFIKOWALNE', 'RUNNING':'DZIAŁA',
    'EVIDENCE SUPPORTED':'POPARTY DOWODAMI', 'PESSIMISTIC':'PESYMISTYCZNY', 'OPTIMISTIC UPPER BOUND':'OPTYMISTYCZNA GRANICA GÓRNA',
    'CREATED':'UTWORZONO', 'PENDING SUBMISSION':'OCZEKUJE NA WYSŁANIE', 'RESTING':'OCZEKUJE W ARKUSZU',
    'UNRESOLVED EXECUTION':'NIEUSTALONE WYKONANIE', 'DEPTH SUPPORTED':'WARUNKOWO Z GŁĘBOKOŚCI',
    'PEAK PASSED FINAL TMAX UNVERIFIED':'SZCZYT MINĄŁ · KOŃCOWY TMAX NIEZWERYFIKOWANY',
    'PARTIALLY FILLED':'CZĘŚCIOWY FILL', 'FILLED':'FILL', 'CANCEL PENDING':'OCZEKUJE NA ANULOWANIE',
    'CANCELLED':'ANULOWANO', 'EXPIRED':'WYGASŁO', 'REJECTED':'ODRZUCONO', 'SETTLED':'ROZLICZONO'
  };
  function label(value) {
    if (value && typeof value === 'object') return label(value.status ?? value.state ?? value.classification);
    const text = String(value ?? '').replaceAll('_', ' ');
    return words[text] || words[String(value)] || text || 'NIEWYSTARCZAJĄCE DANE';
  }
  function quality(value) {
    const name = String(value ?? '').toUpperCase();
    return /HIGH.RISK|SIGNIFICANT|STALE|REJECT|FAILED/.test(name) ? 'status-bad' : /RISK|MINOR|COLDER|HOTTER|UNKNOWN|INSUFFICIENT|UNIDENTIFIED|SIGNAL|PENDING/.test(name) ? 'status-warning' : '';
  }
  function temp(value) {
    const raw = value && typeof value === 'object' ? value.temperature_c ?? value.tmax_c ?? value.value : value;
    return finite(raw) ? `${number(raw, 1)}°C` : '—';
  }
  function temperatureTime(value) {
    if (!value || typeof value !== 'object') return '';
    const time = value.peak_time ?? value.time ?? value.valid_time ?? value.times?.[0];
    return time ? local(time) : '';
  }
  function metric(title, value, note = '', css = '') {
    return `<div class="realization-metric"><label>${esc(title)}</label><strong class="${esc(css)}">${esc(value)}</strong><span class="micro">${esc(note)}</span></div>`;
  }
  function renderRealization(data) {
    const r = data.realization || {};
    const confidence = label(r.confidence);
    $('realization-confidence').textContent = confidence;
    $('realization-confidence').className = `tag ${quality(r.confidence) || 'cyan'}`;
    const latest = r.latest_metar ?? r.evidence?.latest_metar ?? r.history?.at(-1) ?? {};
    const evidence = r.evidence || {}, rates = evidence.rates || {};
    const latestTemperature = r.metar_temperature_c ?? latest.temperature_c ?? latest.metar_temperature_c ?? latest.observed_c;
    const adaptive = r.adaptive_tmax;
    const adaptiveStatus = adaptive && typeof adaptive === 'object' ? label(adaptive.status ?? 'EXPERIMENTAL') : 'EKSPERYMENTALNE';
    const metrics = [
      metric('ICON RAW Tmax', temp(r.forecast_tmax), temperatureTime(r.forecast_tmax)),
      metric('ICON daily API Tmax', temp(r.daily_api_tmax), 'Agregacja dobowa API · Europe/Warsaw · nie wynik rozliczenia'),
      metric('Adaptacyjny Tmax', temp(adaptive), `${adaptiveStatus}${temperatureTime(adaptive) ? ` · ${temperatureTime(adaptive)}` : ''}`),
      metric('Ostatni METAR', temp(latestTemperature), local(latest.observation_time_utc ?? latest.event_time ?? latest.nominal_time)),
      metric('ICON w czasie METAR', temp(r.forecast_at_metar), r.alignment_policy ?? latest.alignment ?? 'Wyrównanie czasowe według zapisanej reguły'),
      metric('Odchylenie przedziałowe', temp(r.residual_c), 'Uwzględnia kwantyzację METAR; nie jest dokładnym błędem termometru'),
      metric('Realizacja temperatury', label(r.state), `Reguła ${r.rule_version ?? 'nieznana'}`, `realization-state ${quality(r.state)}`),
      metric('Tempo temperatury', label(r.trend), finite(rates.actual_c_per_hour) ? `Pomiar ${number(rates.actual_c_per_hour)}°C/h · model ${number(rates.forecast_c_per_hour)}°C/h` : 'Niepewność / liczba cykli według oceny', 'realization-state'),
      metric('Zachmurzenie', label(r.cloud), 'METAR: kategorie i podstawy chmur, nie dokładny procent', 'realization-state'),
      metric('Trend reszt', finite(rates.error_trend_c_per_hour) ? `${number(rates.error_trend_c_per_hour)}°C/h` : label(r.error_trend), finite(evidence.persistent_residual_c) ? `Mediana 3 reszt: ${number(evidence.persistent_residual_c)}°C` : 'Trwałe odchylenie oceniane osobno', 'realization-state'),
      metric('Ryzyko Tmax', label(r.tmax_risk ?? r.confidence), 'Klasyfikacja jakościowa, bez prawdopodobieństwa', `realization-state ${quality(r.confidence)}`),
      metric('Tmax RAW minus zgłoszony max', temp(r.raw_tmax_minus_reported_max_c), 'Różnica do maksimum rutynowych METAR, nie dokładny błąd ani wynik rozliczenia'),
      metric('Pozostałe ocieplenie', temp(evidence.remaining_warming_c ?? r.remaining_warming_c), finite(evidence.hours_to_tmax) ? evidence.hours_to_tmax < 0 ? `Szczyt minął ${number(-evidence.hours_to_tmax * 60, 0)} min temu` : `${number(evidence.hours_to_tmax * 60, 0)} min do prognozowanego szczytu` : 'Termin szczytu nieustalony'),
      metric('Rewizja prognozy', temp(r.forecast_revision_c), `Ocena ${local(r.created_at ?? data.asof ?? data.cutoff)}`)
    ];
    $('realization-metrics').innerHTML = metrics.join('');
    const explanation = Array.isArray(r.explanation) ? r.explanation.join(' ') : r.explanation;
    $('realization-explanation').textContent = `${explanation || 'Brak wystarczających przyczynowych obserwacji do oceny.'} Klasyfikacja badawcza; nie jest zwalidowaną pewnością ani sygnałem rzeczywistego zlecenia.`;
    $('realization-evidence').innerHTML = `<pre>${esc(JSON.stringify({rule_version:r.rule_version, created_at:r.created_at, data_quality:r.data_quality, evidence:r.evidence, supporting_metar_ids:r.supporting_metar_ids, eligible_pws_ids:r.eligible_pws_ids, history:r.history}, null, 2))}</pre>`;
  }
  function family(row) {
    const text = String(row.family ?? row.strategy ?? '').toUpperCase();
    if (text === 'SIMPLE_98_CONTROL') return text;
    return text.startsWith('HYBRID') || text.startsWith('WEATHER_GATED') ? 'HYBRID' : text.startsWith('WEATHER') ? 'WEATHER' : text.startsWith('SIMPLE') ? 'SIMPLE' : text;
  }
  function mode(row) { const text = String(row.mode ?? '').toUpperCase(); return text.includes('MAKER') ? 'MAKER' : text.includes('TAKER') ? 'TAKER' : text; }
  function scenario(row) { return String(row.scenario ?? '').replaceAll('-', '_').replaceAll(' ', '_').toUpperCase(); }
  function selected(row) {
    const f = $('battle-family').value, m = $('battle-mode').value, s = $('battle-scenario').value, l = $('battle-latency').value;
    if (f === 'ALL' && family(row) === 'SIMPLE_98_CONTROL') return false;
    if (f !== 'ALL' && family(row) !== f) return false;
    // Signal-only WEATHER is visible alongside any execution scenario.
    if (family(row) === 'WEATHER' && /SIGNAL/.test(String(row.status ?? ''))) return true;
    return (m === 'ALL' || mode(row) === m) && (s === 'ALL' || scenario(row) === s || s === 'EVIDENCE_SUPPORTED' && scenario(row) === 'DEPTH_SUPPORTED') && (l === 'ALL' || String(row.latency_ms) === l);
  }
  function variant(row) {
    return [family(row), mode(row), label(row.scenario), finite(row.latency_ms) ? `${row.latency_ms} ms` : ''].filter(Boolean).join(' · ');
  }
  function rowMetric(title, value) { return `<dt>${esc(title)}</dt><dd>${esc(value)}</dd>`; }
  function renderCards(data) {
    const rows = (data.strategies || []).filter(selected);
    const shown = rows.slice(0, 24);
    $('battle-cards').innerHTML = shown.length ? shown.map(r => {
      const f = family(r), signalOnly = /SIGNAL/.test(String(r.status ?? ''));
      const title = {SIMPLE:'SIMPLE 91–98 → 99',WEATHER:'WEATHER INTELLIGENCE',HYBRID:'HYBRID / WEATHER-GATED'}[f] || f;
      const pnlClass = finite(r.net_pnl) && Number(r.net_pnl) < 0 ? 'status-bad' : '';
      const metrics = [
        rowMetric('Zrealizowany PnL', dollars(r.realized_pnl)),
        rowMetric('Niezrealizowany PnL', dollars(r.unrealized_pnl)),
        rowMetric('Kapitał paper', dollars(r.equity)),
        rowMetric('Złożone BUY shadow', count(r.submitted_orders)),
        rowMetric('BUY fille poparte dowodami', count(r.supported_buy_fills)),
        rowMetric('Otwarte / rozpoczęte pozycje', `${count(r.open_positions)} / ${count(r.positions_opened)}`),
        rowMetric('Nieustalone wykonania / możliwe pozycje', `${count(r.unresolved_orders)} / ${count(r.unresolved_possible_positions)}`),
        rowMetric('Rezerwa na nieustalone wejście', dollars(r.pending_entry_debit_usd)),
        rowMetric('Wyjścia po 0,99 / niżej', `${count(r.exits_at_target)} / ${count(r.exits_below_target)}`),
        rowMetric('Fill / skuteczność wyjścia', `${ratio(r.fill_rate)} / ${ratio(r.exit_success_rate)}`),
        rowMetric('Ryzyko straty przy rozliczeniu', dollars(r.maximum_loss)),
        rowMetric('Otwarta ekspozycja', dollars(r.exposure_usd)),
        rowMetric('Wykorzystanie kapitału', ratio(r.capital_utilization)),
        rowMetric('Kapitał początkowy scenariusza', dollars(r.initial_capital))
      ];
      if (f === 'HYBRID') metrics.push(rowMetric('Odrzucenia filtra pogody', count(r.weather_rejections)));
      const uncertainty = typeof r.uncertainty === 'string' ? r.uncertainty : JSON.stringify(r.uncertainty ?? 'Brak wystarczającego dowodu wykonania');
      return `<article class="battle-card" data-family="${esc(f)}"><div class="battle-card-head"><h3>${esc(title)}</h3><span class="tag ${signalOnly ? 'amber' : ''}">${esc(signalOnly ? 'SIGNAL-ONLY' : label(r.status))}</span></div><div class="battle-variant">${esc(variant(r))}</div><div class="battle-pnl ${pnlClass}">${esc(signalOnly ? 'SIGNAL-ONLY' : dollars(r.net_pnl))}</div><div class="battle-pnl-label">${signalOnly ? 'Brak obronionej reguły transakcyjnej — wynik handlowy nieidentyfikowalny' : 'Pełny PnL tylko jeśli otwarte ryzyko można wycenić; bez pomijania strat'}</div><dl class="battle-numbers">${metrics.join('')}</dl><p class="uncertainty">${esc(uncertainty)}</p></article>`;
    }).join('') : '<article class="empty">Brak zapisanych wyników dla wybranego wariantu. Niewystarczające dane — nie zerowy PnL.</article>';
    if (rows.length > shown.length) $('battle-cards').insertAdjacentHTML('beforeend', `<p class="battle-variants-note">Wyświetlono ${shown.length} z ${rows.length} osobnych wariantów. Zawęź filtry, aby zobaczyć pozostałe; wyników nie sumujemy.</p>`);
  }
  function renderChart(data) {
    if (!window.echarts) return;
    if (!state.chart) {state.chart = echarts.init($('battle-chart')); state.chart.group = 'epwa-timeline'; echarts.connect('epwa-timeline');}
    const metric = $('battle-chart-metric').value;
    const groups = new Map();
    const end = utc(data.asof ?? data.cutoff);
    for (const r of (data.equity || []).filter(selected)) {
      if (!Number.isFinite(utc(r.at)) || Number.isFinite(end) && utc(r.at) > end || !finite(r[metric])) continue;
      const key = variant(r);
      if (!groups.has(key)) groups.set(key, {row:r,points:[]});
      groups.get(key).points.push([utc(r.at), Number(r[metric])]);
    }
    const colors = {SIMPLE:'#4ed6cf', WEATHER:'#efbc6b', HYBRID:'#afa6f5'};
    const series = [...groups.entries()].map(([name,group]) => {
      const points = group.points.sort((a,b) => a[0] - b[0]);
      const broken = [];
      for (let i = 0; i < points.length; i++) {
        if (i && points[i][0] - points[i-1][0] > 600000) broken.push([points[i-1][0] + 1, null]);
        broken.push(points[i]);
      }
      return {name, type:'line', data:broken, connectNulls:false, showSymbol:points.length < 3, symbolSize:5, lineStyle:{width:1.8,type:scenario(group.row)==='OPTIMISTIC_UPPER_BOUND'?'dashed':'solid'}, itemStyle:{color:colors[family(group.row)] || '#91a3bb'}};
    });
    const old = state.chart.getOption()?.dataZoom?.[0];
    state.chart.setOption({animation:false,backgroundColor:'transparent',textStyle:{color:'#91a3bb',fontFamily:'Segoe UI,Arial,sans-serif'},legend:{type:'scroll',top:5,textStyle:{color:'#aebed1',fontSize:9}},grid:{left:65,right:25,top:50,bottom:57},tooltip:{trigger:'axis',confine:true,formatter:items=>{const entries=Array.isArray(items)?items:[items];return `<strong>${esc(local(entries[0]?.value?.[0]))}</strong>`+entries.map(p=>`<br>${p.marker}${esc(p.seriesName)}: <b>${esc(dollars(p.value?.[1]))}</b>`).join('');}},xAxis:{type:'time',axisLabel:{color:'#91a3bb',fontSize:9,formatter:value=>new Intl.DateTimeFormat('pl-PL',{timeZone:TZ,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value))},splitLine:{show:false}},yAxis:{type:'value',scale:true,axisLabel:{color:'#91a3bb',fontSize:9,formatter:value=>`${number(value,1)} $`},splitLine:{lineStyle:{color:'#26374b',type:'dashed'}}},dataZoom:[{type:'slider',bottom:9,height:17,borderColor:'#33445e',textStyle:{color:'#91a3bb'},start:old?.start??0,end:old?.end??100},{type:'inside'}],graphic:series.length?[]:[{type:'text',left:'center',top:'middle',style:{text:'Brak identyfikowalnej ścieżki kapitału dla tego wariantu',fill:'#91a3bb',fontSize:12}}],series},{replaceMerge:['series','graphic']});
  }
  function renderEvents(data) {
    state.events.clear();
    const cutoff = utc(data.asof ?? data.cutoff);
    const selectedContract = window.dashboard?.state?.selectedMarket;
    const events = (data.events || []).filter(e => {
      const at = utc(e.at ?? e.created_at);
      const dated = !Number.isFinite(cutoff) || Number.isFinite(at) && at <= cutoff;
      const contract = !selectedContract || !e.condition_id || String(e.condition_id) === String(selectedContract);
      return dated && contract && (!e.family || selected(e));
    }).sort((a,b)=>utc(b.at ?? b.created_at)-utc(a.at ?? a.created_at)).slice(0,100);
    $('battle-events-body').innerHTML = events.length ? events.map((e,i)=>{
      state.events.set(String(i),e);
      const p=e.payload || {}, note=p.reason ?? p.explanation ?? p.uncertainty ?? p.fill_confidence ?? '';
      return `<tr data-event="${i}" tabindex="0"><td>${esc(local(e.at ?? e.created_at))}<span class="secondary">${esc(e.id ?? '')}</span></td><td>${esc(label(e.kind))}</td><td>${esc(e.family ? variant(e) : 'EXP-0014 / pogoda')}</td><td>${esc(typeof note==='string'?note:JSON.stringify(note))}</td></tr>`;
    }).join('') : '<tr><td colspan="4" class="empty">Brak zarejestrowanych zdarzeń dostępnych w tej chwili. Nie odtwarzamy fikcyjnych transakcji.</td></tr>';
  }
  function showEvent(id) {
    const event=state.events.get(id);
    if (!event) return;
    $('battle-event-title').textContent=label(event.kind);
    const summary = [['Czas utworzenia',local(event.at ?? event.created_at)],['Identyfikator',event.id],['Strategia / scenariusz',event.family?variant(event):'EXP-0014'],['Kontrakt',event.condition_id ?? '—']];
    $('battle-event-detail').innerHTML=`<dl class="event-summary">${summary.map(([key,value])=>`<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join('')}</dl><p class="event-caveat">Poniżej wyłącznie dowody zapisane i udostępnione do wybranej chwili. Zlecenie shadow nie jest rzeczywistą transakcją; optymistyczny fill nie jest obserwowanym wykonaniem.</p><pre class="event-json">${esc(JSON.stringify(event.payload ?? event,null,2))}</pre>`;
    $('battle-event-dialog').showModal();
  }
  function render(data) {
    const current=window.dashboard?.state;
    const target=current?.live?(current.hoverAt??Date.now()):(current?.replayAt??utc(current?.data?.cutoff));
    if (Number.isFinite(target) && utc(data.asof)>target) return;
    for (const element of document.querySelectorAll('.realization-panel,#battle-cards,#battle-chart,#battle-events-body')) element.style.visibility='';
    state.data=data;
    renderRealization(data);renderCards(data);renderChart(data);renderEvents(data);renderOverlays(data);
    $('battle-cutoff').textContent=`Stan na ${local(data.asof ?? data.cutoff)}`;
    $('battle-sample').textContent=finite(data.sample_days)?`${count(data.sample_days)} DNI OBSERWACJI (TAKŻE NIEPEŁNE)`:'LICZBA DNI NIEUSTALONA';
    const health=data.health;
    $('battle-health').textContent=typeof health==='string'?label(health):`Monitor: ${label(health?.status ?? health?.state)} · feed ${label(health?.feed_status)} · metryka ${local(health?.last_metric_at)} · dane ${local(health?.last_feed)}`;
    const limits=Array.isArray(data.limitations)?data.limitations:[];
    $('battle-warning').textContent=limits.length?limits.join(' · '):'Wyniki shadow zależą od dowodu wykonania, opłat i otwartego ryzyka. Brak jeszcze podstaw do twierdzenia o przewadze.';
    $('battle-warning').classList.remove('research-error');
  }
  function renderOverlays(data) {
    const included=new Set(['CONFIDENCE','FORECAST_REVISION','BUY_SUBMITTED','BUY_FILL','SELL_99_SUBMITTED','SELL_FILL','ORDER_EXPIRED','WEATHER_REJECT']);
    const events=(data.events||[]).filter(e=>included.has(e.kind) && utc(e.at)<=utc(data.asof) && (!e.family || selected(e))).slice(-100);
    for (const chart of [window.dashboard?.weatherChart,window.dashboard?.marketChart]) {
      if (!chart) continue;
      chart.setOption({series:[{id:'battle-event-overlay',name:'Zdarzenia EXP0014/15',type:'line',data:[],silent:false,markLine:{symbol:'none',lineStyle:{type:'dotted',color:'#efbc6b66'},label:{show:false},data:events.map(e=>({xAxis:utc(e.at),name:label(e.kind),researchEventId:String(e.id)}))}}]});
      if (!chart.__battleHandler) {
        chart.__battleHandler=true;
        chart.on('click',event=>{if(event.data?.researchEventId)showEvent(event.data.researchEventId);});
      }
    }
  }
  async function refresh() {
    const current=window.dashboard?.state;
    if (!current?.date) return;
    const point=current.live?(current.hoverAt??Date.now()):(current.replayAt??utc(current.data?.cutoff));
    const loaded=utc(state.data?.asof);
    const loadedDay=Number.isFinite(loaded)?new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(loaded)):'';
    if (state.data && (loaded>point || loadedDay!==current.date)) {
      for (const element of document.querySelectorAll('.realization-panel,#battle-cards,#battle-chart,#battle-events-body')) element.style.visibility='hidden';
      $('battle-warning').textContent='Zmiana czasu: oczekiwanie na odczyt as-of. Późniejsze dane ukryte.';
    }
    if (state.inflight || Date.now()-state.lastAttempt < 5000) return;
    if (!Number.isFinite(point)) return;
    const iso=new Date(Math.min(point,Date.now())).toISOString();
    const requestedDate=current.date, requestedMarket=current.selectedMarket;
    const key=`${current.date}|${current.live && current.hoverAt==null?'LIVE':iso}|${current.selectedMarket ?? ''}`;
    if (!current.live && !current.replay && key===state.requestKey && !state.apiError) return;
    state.lastAttempt=Date.now();state.inflight=true;
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
    try {
      const params=new URLSearchParams({date:current.date,at:iso});
      if (current.selectedMarket) params.set('market',current.selectedMarket);
      const response=await fetch(`/api/battle?${params}`,{signal:controller.signal,cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data=await response.json();
      // A day/hover may change while a read is in flight: discard that response.
      const latest=window.dashboard?.state;
      const latestPoint=latest?.live?(latest.hoverAt??Date.now()):(latest?.replayAt??utc(latest?.data?.cutoff));
      if (latest?.date!==requestedDate || latest?.selectedMarket!==requestedMarket || !Number.isFinite(latestPoint)) return;
      if (latest.replay ? point>latestPoint : !latest.live || latest.hoverAt!=null ? Math.abs(latestPoint-point)>1 : false) return;
      state.requestKey=key;state.apiError=false;render(data);
    } catch (error) {
      state.apiError=true;$('battle-warning').textContent=`Nie udało się odczytać rejestru badań (${error.name==='AbortError'?'przekroczony czas':error.message}). Poprzedni widok może być nieaktualny; nie oznacza to zerowego PnL.`;$('battle-warning').classList.add('research-error');
    } finally {clearTimeout(timer);state.inflight=false;}
  }
  function init() {
    for (const id of ['battle-family','battle-mode','battle-scenario','battle-latency','battle-chart-metric']) $(id).addEventListener('change',()=>{if(state.data)render(state.data);});
    $('battle-events-body').addEventListener('click',e=>{const row=e.target.closest('[data-event]');if(row)showEvent(row.dataset.event);});
    $('battle-events-body').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){const row=e.target.closest('[data-event]');if(row){e.preventDefault();showEvent(row.dataset.event);}}});
    $('close-battle-event').addEventListener('click',()=>$('battle-event-dialog').close());
    $('battle-event-dialog').addEventListener('click',e=>{if(e.target===$('battle-event-dialog'))$('battle-event-dialog').close();});
    window.addEventListener('resize',()=>state.chart?.resize());
    refresh();setInterval(refresh,500);
    window.researchBattle={render,refresh,state};
  }
  document.addEventListener('DOMContentLoaded',init);
})();
