/* EXP0016 read-only presentation. No orders, wallet or provider calls. */
(() => {
  'use strict';
  const TZ = 'Europe/Warsaw';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const num = (value, digits=2) => finite(value) ? Number(value).toLocaleString('pl-PL',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—';
  const temperature = value => finite(value) ? `${num(value,1)}°C` : '—';
  const stamp = value => Date.parse(value || '');
  const local = value => Number.isFinite(stamp(value)) ? new Intl.DateTimeFormat('pl-PL',{timeZone:TZ,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'shortOffset',hourCycle:'h23'}).format(new Date(value)) : 'NIEZNANY';
  const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const list = value => Array.isArray(value) ? value : [];
  const state = {data:null,inflight:false,attempt:0,key:'',error:false};
  const labels = {'SIGNAL_ONLY':'TYLKO SYGNAŁY','PROBABILITY_UNVALIDATED':'PRAWDOPODOBIEŃSTWO NIEZWALIDOWANE','CALIBRATION_PENDING':'CALIBRATION PENDING','RESEARCH_CANDIDATE':'KANDYDAT BADAWCZY','NO_MARKETS':'BRAK RYNKÓW','STALE':'NIEŚWIEŻE','VALID':'AKTUALNY','UNAVAILABLE':'NIEDOSTĘPNY','RUNNING':'DZIAŁA'};
  const label = value => labels[String(value)] || String(value ?? 'NIEUSTALONE').replaceAll('_',' ');
  function currentPoint() {
    const s=window.dashboard?.state;
    if (!s?.date) return null;
    const point=s.live?(s.hoverAt??Date.now()):(s.replayAt??stamp(s.data?.cutoff));
    return Number.isFinite(point)?{point:Math.min(point,Date.now()),day:s.date,live:s.live && s.hoverAt==null}:null;
  }
  function metric(title,value,note='') {
    return `<div class="d1-metric"><label>${esc(title)}</label><strong>${esc(value)}</strong><span class="micro">${esc(note)}</span></div>`;
  }
  function probabilityView(value) {
    const p=obj(value), yes=p.yes_probability??p.p_yes, no=p.no_probability??p.p_no;
    const validated=p.validated===true || /^(CALIBRATED|VALIDATED)$/.test(String(p.calibration_status??p.status));
    const valid=validated && finite(yes) && finite(no) && Number(yes)>=0 && Number(yes)<=1 && Number(no)>=0 && Number(no)<=1;
    const n=p.sample_size??p.independent_days??p.n;
    if (!valid) return `<span class="d1-pending">CALIBRATION PENDING</span><span class="secondary">${esc(finite(n)?`${num(n,0)} dni historii`:'Brak zwalidowanej historii rozliczeń')}</span>`;
    const interval=p.uncertainty_interval??p.interval;
    return `<span>YES ${esc(num(Number(yes)*100,1))}% · NO ${esc(num(Number(no)*100,1))}%</span><span class="secondary">${esc(finite(n)?`${num(n,0)} niezależnych dni`:'Liczebność nieustalona')}${interval?` · przedział ${esc(JSON.stringify(interval))}`:''}</span>`;
  }
  function quote(book) {
    const b=obj(book), good=b.status==='VALID';
    const price=`${num(b.best_bid,3)} / ${num(b.best_ask,3)}`;
    return `<span class="d1-quote ${good?'':'d1-muted'}">${esc(price)}</span><span class="secondary">${esc(label(b.status??'NO_FULL_SNAPSHOT'))} · ${esc(local(b.received_at))}</span>`;
  }
  function outcome(value) {
    if (typeof value==='string') return value;
    const o=obj(value), t=o.temperature_c??o.value;
    const names={EXACT:'dokładnie',BELOW:'poniżej',AT_MOST:'co najwyżej',ABOVE:'powyżej',AT_LEAST:'co najmniej'};
    return o.label || `${names[o.kind]??label(o.kind)} ${temperature(t)}`;
  }
  function candidateSummary(value) {
    const c=obj(value), reasons=c.rejection_reasons??c.reasons??c.blockers;
    const status=c.status??c.classification??'PROBABILITY_UNVALIDATED';
    const notes=Array.isArray(reasons)?reasons.join(' · '):reasons;
    return `<strong class="d1-candidate">${esc(label(status))}</strong>${notes?`<span class="secondary">${esc(notes)}</span>`:''}`;
  }
  function renderForecasts(data) {
    const cutoff=stamp(data.asof), rows=list(data.forecasts).filter(f=>!f.first_received || stamp(f.first_received)<=cutoff);
    $('d1-forecast-body').innerHTML=rows.length?rows.map(f=>`<tr><td><strong>${esc(f.model)}</strong><span class="secondary">Rodzina: ${esc(f.family??'nieustalona')}</span></td><td>${esc(temperature(f.daily_tmax_c))}<span class="secondary">dobowa agregacja API</span></td><td>${esc(temperature(f.hourly_point_max_c))}<span class="secondary">${esc(local(f.tmax_time))}</span></td><td>${esc(finite(f.revision_c)?`${num(f.revision_c,1)}°C`:'—')}<span class="secondary">zmiana od poprzedniego zapisu</span></td><td>${esc(local(f.first_received))}<span class="secondary">Inicjalizacja: ${esc(local(f.initialization_time))}</span></td><td>${esc(label(f.status??'AVAILABLE'))}</td></tr>`).join(''):'<tr><td colspan="6" class="empty">Brak prognoz odebranych do wybranej chwili. Późniejszych uruchomień modelu nie podstawiamy do historii.</td></tr>';
  }
  function renderMarkets(data) {
    const markets=list(data.markets), cutoff=stamp(data.asof);
    $('d1-market-body').innerHTML=markets.length?markets.map((m,index)=>{
      const yes=obj(m.yes_book), no=obj(m.no_book);
      const filteredYes=stamp(yes.received_at)>cutoff?{status:'FUTURE_BOOK'}:yes;
      const filteredNo=stamp(no.received_at)>cutoff?{status:'FUTURE_BOOK'}:no;
      const detail={...m,yes_book:filteredYes,no_book:filteredNo};
      return `<tr><td><strong>${esc(outcome(m.outcome))}</strong><span class="secondary">${esc(m.title??'')}</span></td><td>${quote(filteredYes)}</td><td>${quote(filteredNo)}</td><td>${probabilityView(m.probability)}</td><td>${candidateSummary(m.candidate)}</td><td><span>${esc(label(m.rules_status??'UNVERIFIED'))}</span><details class="d1-details"><summary>Dowody kontraktu ${index+1}</summary><pre>${esc(JSON.stringify(detail,null,2))}</pre></details></td></tr>`;
    }).join(''):'<tr><td colspan="6" class="empty">Nie zapisano kontraktów dla wskazanego dnia rozliczenia. Brak ceny nie oznacza braku możliwej oferty na rynku.</td></tr>';
  }
  function renderStrategies(data) {
    const rows=Array.isArray(data.strategies)?data.strategies:Object.entries(obj(data.strategies)).map(([name,row])=>({name,...obj(row)}));
    $('d1-strategies').innerHTML=rows.length?rows.map(row=>{
      const status=row.status??'SIGNAL_ONLY';
      const realized=row.realized_pnl, unrealized=row.unrealized_pnl;
      return `<article class="d1-strategy"><span class="tag amber">${esc(label(status))}</span><h3>${esc(row.name??row.strategy??row.version)}</h3><p>${esc(row.exit_policy??row.description??'Zamrożone reguły shadow; brak rzeczywistych zleceń.')}</p><dl><dt>Próby / poparte fille</dt><dd>${esc(num(row.submitted_orders,0))} / ${esc(num(row.supported_buy_fills,0))}</dd><dt>Otwarte pozycje</dt><dd>${esc(num(row.open_positions,0))}</dd><dt>Zrealizowany / niezrealizowany PnL</dt><dd>${esc(finite(realized)?`${num(realized)} USD`:'NIEIDENTYFIKOWALNY')} / ${esc(finite(unrealized)?`${num(unrealized)} USD`:'NIEIDENTYFIKOWALNY')}</dd><dt>Ekspozycja</dt><dd>${esc(finite(row.exposure_usd)?`${num(row.exposure_usd)} USD`:'NIEUSTALONA')}</dd></dl></article>`;
    }).join(''):'<p class="empty">Reguły D−1 oczekują na kwalifikujące dane. Nie tworzymy fikcyjnych wejść ani PnL.</p>';
  }
  function render(data) {
    const target=currentPoint();
    if (!target || !Number.isFinite(stamp(data.asof)) || stamp(data.asof)>target.point) return;
    state.data=data;
    state.loadedDay=target.day;
    $('d1-content').hidden=false;
    const consensus=obj(data.consensus), families=consensus.families;
    const familiesText=Array.isArray(families)?families.join(', '):finite(families)?`${num(families,0)} rodzin`:'Nieustalona liczba rodzin';
    $('d1-date').textContent=`Rozliczenie ${data.settlement_date??'nieustalone'}`;
    $('d1-asof').textContent=`Informacje dostępne do ${local(data.asof)}`;
    $('d1-metrics').innerHTML=[
      metric('Dzień rynku',data.settlement_date??'—','Jutro względem wskazanej chwili w Europe/Warsaw'),
      metric('Zakres prognoz Tmax',finite(consensus.min_c)&&finite(consensus.max_c)?`${num(consensus.min_c,1)}–${num(consensus.max_c,1)}°C`:'—','Rozbieżność modeli nie jest rozkładem prawdopodobieństwa'),
      metric('Rozrzut modeli',temperature(consensus.spread_c),familiesText),
      metric('Kalibracja prawdopodobieństw',label(data.calibration_status??'CALIBRATION_PENDING'),'Powiązane modele nie są niezależnymi głosami')
    ].join('');
    renderForecasts(data);renderMarkets(data);renderStrategies(data);
    const health=obj(data.health);
    $('d1-health').textContent=`Monitor: ${label(health.state??health.status??data.health)} · ostatni zapis ${local(health.last_event??health.last_metric_at??health.last_received)}`;
    const warnings=list(data.limitations);
    $('d1-warning').textContent=warnings.length?warnings.join(' · '):'SHADOW ONLY · Brak zwalidowanego prawdopodobieństwa blokuje EV i wejścia. Ask oznacza ofertę sprzedaży; sam bid nie jest ceną zakupu. Widoczna płynność nie gwarantuje wykonania.';
    $('d1-warning').classList.remove('d1-error');
    state.error=false;
  }
  async function refresh() {
    const target=currentPoint();
    if (!target) return;
    const loaded=stamp(state.data?.asof);
    if (state.data && (loaded>target.point || state.loadedDay!==target.day)) {
      $('d1-content').hidden=true;
      $('d1-warning').textContent='Zmiana czasu: późniejsze informacje ukryte. Oczekiwanie na odczyt as-of.';
    }
    if (state.inflight || Date.now()-state.attempt<10000) return;
    const key=`${target.day}|${target.live?'LIVE':target.point}`;
    if (!target.live && key===state.key && !state.error) return;
    state.inflight=true;state.attempt=Date.now();
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
    try {
      const params=new URLSearchParams({at:new Date(target.point).toISOString()});
      const response=await fetch(`/api/tomorrow?${params}`,{cache:'no-store',signal:controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data=await response.json(), latest=currentPoint();
      if (!latest || target.day!==latest.day || !latest.live && Math.abs(target.point-latest.point)>1) return;
      state.key=key;render(data);
    } catch(error) {
      state.error=true;
      $('d1-warning').textContent=`Odczyt EXP-0016 niedostępny (${error.name==='AbortError'?'przekroczony czas':error.message}). Poprzedni zapis może być nieaktualny; to nie jest zerowy wynik strategii.`;
      $('d1-warning').classList.add('d1-error');
    } finally {clearTimeout(timer);state.inflight=false;}
  }
  function init() {
    if ($('d1-panel')) return;
    const panel=document.createElement('section');
    panel.id='d1-panel';panel.className='panel d1-panel';panel.setAttribute('aria-label','Jutro — prognoza a rynek EPWA');
    panel.innerHTML=`<div class="panel-heading"><div><span class="eyebrow">EXP-0016 / D−1 / WYŁĄCZNIE SHADOW</span><h2>Jutro — prognoza a rynek</h2><span class="micro">TOMORROW — FORECAST vs MARKET</span></div><span class="tag cyan" id="d1-date">Oczekiwanie na datę rozliczenia</span></div><div class="d1-intro"><span id="d1-asof" class="micro">Odczyt —</span><span class="micro">Wspólny dzień i suwak określają chwilę decyzji D−1; kontrakty dotyczą kolejnego dnia warszawskiego.</span></div><p id="d1-warning" class="d1-warning micro">Oczekiwanie na utrwalone prognozy i ceny. Brak danych nie oznacza zerowego PnL.</p><div id="d1-content"><div id="d1-metrics" class="d1-metrics"></div><div class="d1-subheading"><h3>Modele i czas dostępności</h3><span class="micro">Dobowy Tmax API ≠ maksimum punktów godzinowych</span></div><div class="table-scroll"><table class="data-table d1-table"><thead><tr><th>Model / rodzina</th><th>Tmax dobowy API</th><th>Max godzinowych punktów / pora</th><th>Rewizja</th><th>Pierwszy odbiór / inicjalizacja</th><th>Status</th></tr></thead><tbody id="d1-forecast-body"><tr><td colspan="6" class="empty">Brak odczytu.</td></tr></tbody></table></div><div class="d1-subheading"><h3>Kontrakty na jutro</h3><span class="micro">Bid / ask · zakup konsumuje ask, sprzedaż bid</span></div><div class="table-scroll"><table class="data-table d1-table d1-contracts"><thead><tr><th>Rzeczywisty przedział temperatury</th><th>YES bid / ask</th><th>NO bid / ask</th><th>Prawdopodobieństwo</th><th>Kandydatura / ograniczenia</th><th>Reguły i dowody</th></tr></thead><tbody id="d1-market-body"><tr><td colspan="6" class="empty">Brak odczytu.</td></tr></tbody></table></div><div class="d1-subheading"><h3>Strategie D−1</h3><span id="d1-health" class="micro">Stan monitora nieustalony</span></div><div id="d1-strategies" class="d1-strategies"></div></div>`;
    const anchor=document.querySelector('.realization-panel');
    if (anchor) anchor.after(panel); else document.querySelector('.battle-panel')?.before(panel);
    refresh();setInterval(refresh,500);
    window.researchD1={render,refresh,state};
  }
  document.addEventListener('DOMContentLoaded',init);
})();
