/* Local, read-only EPWA interface. No external requests, wallet or order actions. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const TZ = 'Europe/Warsaw';
  const colors = ['#65d7bb', '#e4b06b', '#afa0f5', '#73b9ed', '#dc94bb', '#a7c978', '#79d3dd'];
  const state = {data:null, date:'', live:true, replay:false, replayAt:null, selectedMarket:'', receipts:false, showOtherSensors:false, showCalibrated:true, pwsMarkers:false, fetchId:0, inspectId:0, lastLoad:0, inspectTimer:null, refreshTimer:null, lastTick:performance.now(), asof:null, hoverAt:null};
  let weatherChart, marketChart;
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = (v, digits=1) => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)) ? Number(v).toLocaleString('pl-PL', {minimumFractionDigits:digits, maximumFractionDigits:digits}) : '—';
  const temp = v => `${number(v)}°C`;
  const preciseTemp = v => v==null || !Number.isFinite(Number(v)) ? '—' : `${Number(v).toLocaleString('pl-PL',{maximumFractionDigits:6})}°C`;
  const price = v => number(v, 3);
  const ms = v => typeof v === 'number' ? v : Date.parse(v || '');
  const iso = v => new Date(v).toISOString();
  function local(value, full=false) {
    if (!Number.isFinite(ms(value))) return '—';
    return new Intl.DateTimeFormat('pl-PL', {timeZone:TZ, ...(full ? {day:'2-digit',month:'2-digit',year:'numeric'} : {}), hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZoneName:'shortOffset'}).format(new Date(ms(value)));
  }
  function localDay(value=Date.now()) {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value)).map(x => [x.type,x.value]));
    return `${p.year}-${p.month}-${p.day}`;
  }
  function age(value, at=Date.now()) { const s=(at-ms(value))/1000; return !Number.isFinite(s) ? 'brak czasu' : s<0 ? 'czas przyszły' : s<90 ? `${Math.round(s)} s` : s<3600 ? `${Math.round(s/60)} min` : `${number(s/3600,1)} h`; }
  function countdown(seconds) { if(!Number.isFinite(Number(seconds))) return '—'; const s=Math.max(0,Math.floor(Number(seconds))); return s>=3600 ? `${Math.floor(s/3600)} h ${Math.floor(s%3600/60)} min` : `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`; }
  const text = (id, value) => { const node=$(id); if(node) node.textContent=value ?? '—'; };
  const good = status => /^(HEALTHY|LIVE|RUNNING|VALID|AVAILABLE|FRESH|OK)$/i.test(status || '');
  const statusClass = status => good(status) ? 'status-good' : /INVALID|QUARANT|FAILED|ERROR/i.test(status||'') ? 'status-bad' : 'status-warning';
  function reportTime(r) { return r?.observation_time_utc || r?.event_time || r?.measurement_time; }
  function receipt(r) { return r?.first_received_utc || r?.first_received || r?.first_receive_time || r?.collector_receive_time; }
  function labelStatus(status) { return ({VALID:'WAŻNY',AVAILABLE:'DOSTĘPNE',LIVE:'NA ŻYWO',FRESH:'ŚWIEŻE',OK:'OK',STALE:'NIEŚWIEŻY',STALE_DATA:'NIEŚWIEŻY',STALE_BOOK:'NIEŚWIEŻY ARKUSZ',HEALTHY:'AKTUALNY',RUNNING:'DZIAŁA',UNKNOWN:'NIEZNANY',UNAVAILABLE:'BRAK DANYCH',NO_DATA:'BRAK DANYCH',INVALID_TIMESTAMP:'BŁĘDNY CZAS',UNKNOWN_TIMESTAMP_PROVENANCE:'NIEZWERYFIKOWANY CZAS',QUARANTINED:'KWARANTANNA'})[status] || status || 'BRAK DANYCH'; }
  function safeURL(value) { try { const u=new URL(value); return /^https:$/.test(u.protocol) ? u.href : ''; } catch {return '';} }
  async function getJSON(url) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
    try { const response=await fetch(url,{signal:controller.signal,cache:'no-store'}); if(!response.ok) throw new Error(`API ${response.status}`); return await response.json(); } finally {clearTimeout(timer);}
  }
  function showError(error) { const node=$('error-banner'); node.classList.remove('hidden'); node.textContent=`Nie udało się odczytać danych: ${error.message || 'błąd połączenia'}. Ostatni widok może być nieaktualny.`; }
  function sourceStrip(data) {
    const health=data.health || {};
    const specs=[['METAR',health.weather, data.observed?.latest && receipt(data.observed.latest)],['PROGNOZA',health.forecast,data.forecast?.first_received],['PWS',health.pws,null],['POLYMARKET WS',health.market,null]];
    $('source-strip').innerHTML=specs.map(([name,s, fallback]) => {s=s||{};const when=s.last_received || s.last_measurement || s.heartbeat || fallback; return `<span class="source-item"><i class="source-status ${good(s.status)?'':when?'stale':'missing'}"></i><span class="source-name">${esc(name)}</span><span>${esc(labelStatus(s.status))} · ${esc(when?`${local(when)} / ${age(when)}`:'brak odczytu')}</span></span>`;}).join('')+`<span class="source-item">ZEGAR <span class="status-warning">${esc(labelStatus(health.clock_status || 'UNKNOWN'))}</span></span>`;
  }
  function hero(data) {
    const f=data.forecast || {}, t=f.tmax || {}, obs=data.observed || {}, latest=obs.latest;
    $('forecast-tmax').innerHTML=`${number(t.temperature_c)}<small>°C</small>`;
    const peaks=Array.isArray(t.times)?t.times:[];
    text('forecast-peak', peaks.length ? `Oczekiwane: ${peaks.map(p=>local(p).replace(/:\d{2} (?=GMT)/,' ')).join(' · ')} Europe/Warsaw${t.complete===false?' · NIEPEŁNY DZIEŃ':''}` : 'Brak kompletnej prognozy wybranego dnia');
    const reference=state.live?Date.now():ms(data.cutoff), upcomingPeak=peaks.map(ms).filter(t=>Number.isFinite(t)&&t>=reference).sort((a,b)=>a-b)[0];
    text('forecast-countdown',upcomingPeak!=null?`Do prognozowanego szczytu: ${countdown((upcomingPeak-reference)/1000)}`:peaks.length?'Prognozowany termin szczytu już minął':'Termin szczytu: brak danych');
    text('forecast-model', `${f.model || 'Model nieznany'} · max punktów godzinowych`);
    const delta=f.delta_tmax;
    text('forecast-change', delta==null ? 'Poprzedni Tmax —' : `Poprzednio ${temp(f.previous_tmax)} · ${Number(delta)>0?'+':''}${number(delta)}°C`);
    text('forecast-meta', `Odbiór: ${local(f.first_received)} · przebieg: ${f.run_time || 'niepotwierdzony'} · publikacja: ${f.publication_time || 'nieznana'}`);
    const calibration=f.calibration || {}, validated=calibration.status==='VALIDATED' && calibration.temperature_c!=null;
    $('calibrated-tmax').innerHTML=`${validated?number(calibration.temperature_c):'—'}<small>°C</small>`;
    $('calibrated-tmax').classList.toggle('pending',!validated);
    text('forecast-calibration-status',validated?'ZWALIDOWANE':'CALIBRATION PENDING');
    $('forecast-calibration-status').className=`tag ${validated?'cyan':'amber'}`;
    const calibratedTimes=validated && Array.isArray(calibration.times)?calibration.times:[];
    text('calibrated-peak',calibratedTimes.length?`Oczekiwane: ${calibratedTimes.map(t=>local(t)).join(' · ')} Europe/Warsaw`:'Brak zwalidowanego Tmax — bez kopiowania wartości RAW');
    text('calibrated-version',calibration.version || 'EPWA-FC-CAL-v1');
    text('calibrated-samples',`${calibration.daily_sample_count ?? calibration.sample_count ?? 0} dni walidacji`);
    const validation=calibration.validated_error;
    const errorValue=typeof validation==='number'?validation:validation?.mae_c ?? validation?.mae ?? validation?.interval_aware_mae;
    text('calibrated-error',errorValue==null?'Błąd walidacyjny: brak potwierdzonej oceny':`Ostatni zwalidowany MAE: ${number(errorValue,2)}°C`);
    const calibrationReason=calibration.reason==='NO_VERIFIED_FINAL_SETTLEMENT_HISTORY'?'Brak zweryfikowanej historii końcowych rozliczeń':calibration.reason==='INSUFFICIENT_DATA'?'Za mało danych do walidacji':calibration.reason || 'Kalibracja oczekuje walidacji';
    text('calibrated-freshness',validated?`Parametry dostępne: ${local(calibration.asof_available_at)} · dane prognozy: ${age(f.first_received)}`:`${calibrationReason} · dane RAW: ${age(f.first_received)}`);

    $('observed-max').innerHTML=`${number(obs.max_temperature_c,0)}<small>°C</small>`;
    const maxReports=obs.max_reports || [];
    text('observed-max-time',maxReports.length ? `Pomiar ${local(reportTime(maxReports[0]))} · odbiór ${local(receipt(maxReports[0]))}` : 'Brak otrzymanych raportów w tym dniu');
    text('routine-count',`${obs.routine_count || 0} raportów rutynowych`);
    const speciText=({SPECI_WIDOCZNE_NIE_WLICZANE_DO_MAKSIMUM:'widoczne, poza maksimum',ROUTINE_ONLY:'poza maksimum',EXCLUDED:'poza maksimum',INCLUDED:'wliczane'})[obs.speci_policy] || String(obs.speci_policy || 'poza maksimum').replaceAll('_',' ').toLowerCase();
    text('speci-policy',`SPECI: ${speciText}`);
    text('official-maximum',obs.official_maximum_c==null?'—':temp(obs.official_maximum_c));
    text('settlement-value',obs.final_settlement_value==null?'Rozliczenie rynku: nieustalone.':`Oficjalne rozliczenie: ${temp(obs.final_settlement_value)}`);
    $('latest-temperature').innerHTML=`${number(latest?.temperature_c,0)}<small>°C</small>`;
    text('latest-report-type',latest ? `${latest.report_type || 'METAR'}${latest.correction?' COR':''}` : 'BRAK');
    text('latest-report-time',latest ? `Pomiar ${local(reportTime(latest))} · odbiór ${local(receipt(latest))}` : 'Brak otrzymanych raportów');
    text('latest-tac',latest?.raw_text || 'Brak surowego raportu');
    const current=typeof f.current_hour==='object' ? f.current_hour?.temperature_c : f.current_hour;
    text('current-forecast',`Prognoza teraz ${temp(f.temperature_c ?? current)}`);
    const points=f.points || [], nowAt=state.live?Date.now():ms(data.cutoff), next=points.find(p=>ms(p.valid_time)>nowAt);
    text('forecast-trend',next && (f.temperature_c ?? current)!=null ? `Następna godzina ${temp(next.temperature_c)}` : 'Trend: brak kolejnej godziny');
    const warnings=(data.warnings || []).map(x=>typeof x==='string'?x:JSON.stringify(x));
    $('warnings').classList.toggle('hidden',!warnings.length);
    text('warnings',warnings.join(' · '));
    text('chart-cutoff',`Odczyt: ${local(data.generated_at)}${!state.live?' · historia':''}`);
  }
  function chartBase(min,max) {
    return {animation:false,backgroundColor:'transparent',textStyle:{fontFamily:'Segoe UI, Arial, sans-serif'},grid:{left:48,right:22,top:57,bottom:58},legend:{top:6,left:18,right:18,type:'scroll',textStyle:{color:'#a8bdd2',fontSize:10},pageTextStyle:{color:'#a8bdd2'}},tooltip:{trigger:'axis',axisPointer:{type:'cross',label:{show:false}},backgroundColor:'#0b1524',borderColor:'#38506c',textStyle:{color:'#dce9f5',fontSize:11},confine:true},axisPointer:{link:[{xAxisIndex:'all'}]},xAxis:{type:'time',min,max,axisLine:{lineStyle:{color:'#38506c'}},axisLabel:{color:'#91a3bb',fontSize:10,formatter:v=>new Intl.DateTimeFormat('pl-PL',{timeZone:TZ,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(v))},splitLine:{show:false}},yAxis:{type:'value',scale:true,axisLabel:{color:'#91a3bb',fontSize:10},splitLine:{lineStyle:{color:'#203148',type:'dashed'}},axisLine:{show:false}},dataZoom:[{type:'inside',xAxisIndex:0,filterMode:'none'},{type:'slider',height:16,bottom:10,borderColor:'#2b3f59',backgroundColor:'#0c1727',fillerColor:'#3b718044',handleStyle:{color:'#73bec7'},textStyle:{color:'#90a5bd'},xAxisIndex:0,filterMode:'none'}]};
  }
  function gaps(points,maxGap=15*60*1000) {
    const sorted=points.filter(p=>Number.isFinite(p.value[0]) && p.value[1]!=null).sort((a,b)=>a.value[0]-b.value[0]), result=[];
    sorted.forEach((p,i)=>{if(i && p.value[0]-sorted[i-1].value[0]>maxGap) result.push({value:[sorted[i-1].value[0]+1,null]});result.push(p);});return result;
  }
  function weatherOptions(data) {
    const base=chartBase(ms(data.day_start),ms(data.day_end)), f=data.forecast || {}, series=[];
    if((f.points||[]).length) series.push({name:'Prognoza punktowa · godzinowa',type:'line',data:gaps(f.points.map(p=>({value:[ms(p.valid_time),p.temperature_c],source:p,kind:'forecast'})),90*60000),symbol:'circle',symbolSize:5,smooth:false,connectNulls:false,lineStyle:{width:2,color:'#4ed6cf'},itemStyle:{color:'#4ed6cf'}});
    if(Array.isArray(f.hourly_maximum)) series.push({name:'Prognozowane maksimum przedziału',type:'line',data:f.hourly_maximum.map(p=>({value:[ms(p.valid_time),p.temperature_c],source:p,kind:'hourly_max'})),lineStyle:{type:'dashed',color:'#b5e4dc'},itemStyle:{color:'#b5e4dc'},connectNulls:false});
    const metars=data.metars || [];
    series.push({name:'METAR · integer °C',type:'scatter',data:metars.filter(r=>r.temperature_c!=null).map(r=>({value:[ms(reportTime(r)),r.temperature_c],source:r,kind:'metar'})),symbol:'diamond',symbolSize:8,itemStyle:{color:'#edf3fc',borderColor:'#15283d',borderWidth:1},z:5});
    const selectedSensorIds=new Set((data.stations||[]).filter(s=>s.selected===true).map(s=>s.sensor_id));
    const selectedStationIds=new Set((data.stations||[]).filter(s=>s.selected===true).map(s=>s.station_id));
    const visibleSensors=(data.pws_series||[]).filter(s=>state.showOtherSensors || s.selected===true || selectedSensorIds.has(s.sensor_id) || (!s.sensor_id && selectedStationIds.has(s.station_id)));
    for(const [index,s] of visibleSensors.entries()) {
      const color=s.color || colors[index%colors.length], points=s.points || [];
      series.push({name:`${s.name || s.sensor_id} · surowe`,type:'line',data:gaps(points.map(p=>({value:[ms(p.measurement_time),p.temperature_c],source:p,kind:'pws',sensor:s}))),symbol:'circle',symbolSize:3,showSymbol:points.length<100,lineStyle:{width:1.5,color},itemStyle:{color},connectNulls:false});
      const corrected=points.filter(p=>p.calibrated_temperature_c!=null);
      if(state.showCalibrated && corrected.length) series.push({name:`${s.name || s.sensor_id} · kalibracja`,type:'line',data:gaps(corrected.map(p=>({value:[ms(p.measurement_time),p.calibrated_temperature_c],source:p,kind:'calibrated',sensor:s}))),symbol:'none',lineStyle:{width:1.5,type:'dashed',color},itemStyle:{color},connectNulls:false});
    }
    if((f.tmax?.times || []).length && f.tmax.temperature_c!=null) series.push({name:'Prognozowany Tmax punktowy',type:'scatter',data:f.tmax.times.map(t=>({value:[ms(t),f.tmax.temperature_c],kind:'forecast_peak'})),symbol:'pin',symbolSize:25,itemStyle:{color:'#efbc6b'},z:6});
    if(state.receipts) series.push({name:'Odbiór METAR',type:'scatter',data:metars.filter(r=>r.temperature_c!=null).map(r=>({value:[ms(receipt(r)),r.temperature_c],source:r,kind:'receipt'})),symbol:'emptyCircle',symbolSize:9,itemStyle:{color:'#efbc6b'},z:6});
    base.tooltip.formatter=params=>{
      const entries=(Array.isArray(params)?params:[params]).filter(p=>p.data && p.value?.[1]!=null);
      return `<strong>${esc(local(entries[0]?.value?.[0],true))}</strong>`+entries.slice(0,13).map(p=>{const r=p.data.source || {},kind=p.data.kind;const info=kind==='forecast'?`Ważna: ${local(r.valid_time)} · snapshot odebrany ${local(r.first_received || f.first_received)}`:kind==='forecast_peak'?'Maksimum próbek godzinowych, nie maksimum ciągłe':`Pomiar: ${local(r.measurement_time || reportTime(r))}<br>Odbiór: ${local(receipt(r))}${r.provenance?` · ${r.provenance}`:''}`;return `<div class="tip-item">${p.marker}<b>${esc(p.seriesName)}</b> ${esc(preciseTemp(p.value[1]))}<br><small>${esc(info).replace(/&lt;br&gt;/g,'<br>')}</small></div>`;}).join('');
    };
    return {...base,series};
  }
  function selectedMarket(data) {return (data.markets||[]).find(m=>m.condition_id===state.selectedMarket) || null;}
  function marketOptions(data) {
    const base=chartBase(ms(data.day_start),ms(data.day_end)), selected=selectedMarket(data), history=(data.market_history||[]).filter(p=>p.condition_id===state.selectedMarket), series=[];
    const defs=[['yes','bid','YES bid','#7cdbb0','solid'],['yes','ask','YES ask','#7cdbb0','dashed'],['no','bid','NO bid','#b0a3f6','solid'],['no','ask','NO ask','#b0a3f6','dashed']];
    for(const [side,field,name,color,dash] of defs) series.push({name,type:'line',data:gaps(history.filter(p=>p[side]?.[field]!=null && (!p.status || good(p.status))).map(p=>({value:[ms(p.time),Number(p[side][field])],source:p,kind:'book'})),20000),showSymbol:true,symbolSize:3,connectNulls:false,lineStyle:{color,type:dash,width:1.6},itemStyle:{color}});
    const marks=(data.metars||[]).filter(m=>receipt(m)).map(m=>({xAxis:ms(receipt(m)),name:`Odbiór ${m.report_type || 'METAR'}`,lineStyle:{color:'#efbc6b66',type:'dotted'},label:{show:false}}));
    const revisions=(data.signals||[]).filter(s=>(/FORECAST_REVISION/.test(s.kind || s.payload?.kind || '') || state.pwsMarkers && /PWS_CONFIRMS/.test(s.kind || s.payload?.kind || ''))).map(s=>({xAxis:ms(s.created_at || s.payload?.created_at),name:s.kind || s.payload?.kind,lineStyle:{color:'#4ed6cf55',type:'dotted'},label:{show:false}}));
    if(series.length) series[0].markLine={silent:false,symbol:'none',data:[...marks,...revisions]};
    base.yAxis={...base.yAxis,min:0,max:1,axisLabel:{color:'#91a3bb',fontSize:10,formatter:v=>number(v,2)}};
    base.tooltip.formatter=params=>{const p=Array.isArray(params)?params:[params];return `<strong>${esc(selected?.outcome_label || selected?.title || 'Kontrakt')}</strong><br>${esc(local(p[0]?.value?.[0],true))}`+p.filter(x=>x.value?.[1]!=null).map(x=>`<br>${x.marker}${esc(x.seriesName)} <b>${esc(price(x.value[1]))}</b>`).join('')+'<br><small>Cena ofertowa ≠ gwarantowane wykonanie.</small>';};
    return {...base,series};
  }
  function preserveZoom(chart, option) {const current=chart?.getOption()?.dataZoom;if(current?.length) option.dataZoom.forEach((z,i)=>{if(current[i]) {z.start=current[i].start;z.end=current[i].end;}});return option;}
  function renderCharts(data) {
    if(!window.echarts) {text('weather-chart','Biblioteka wykresu nie jest dostępna. Sprawdź lokalny plik ECharts.');return;}
    if(!weatherChart) {
      weatherChart=echarts.init($('weather-chart'),null,{renderer:'canvas'});marketChart=echarts.init($('market-chart'),null,{renderer:'canvas'});
      weatherChart.group=marketChart.group='epwa-timeline';echarts.connect('epwa-timeline');
      [weatherChart,marketChart].forEach(chart=>{

        const inspectPointer=event=>{if(chart.containPixel({gridIndex:0},[event.offsetX,event.offsetY])) {const value=Number(chart.convertFromPixel({xAxisIndex:0},event.offsetX));if(Number.isFinite(value)){state.hoverAt=value;scheduleInspect(value);}}};chart.getZr().on('mousemove',inspectPointer);chart.getZr().on('click',inspectPointer);
      });
      [weatherChart,marketChart].forEach(chart=>chart.getZr().on('globalout',()=>{if(state.live&&!state.replay){state.hoverAt=null;scheduleInspect(Date.now());}}));
      window.addEventListener('resize',()=>{weatherChart.resize();marketChart.resize();});
    }
    weatherChart.setOption(preserveZoom(weatherChart,weatherOptions(data)),{replaceMerge:['series']});
    marketChart.setOption(preserveZoom(marketChart,marketOptions(data)),{replaceMerge:['series']});
  }
  function hours(data) {
    const rows=data.hours || [];
    $('hours-body').innerHTML=rows.length?rows.map((h,index)=>{const reports=h.metars||[],pws=h.pws||[];const raw=pws.filter(p=>p.temperature_c!=null);return `<tr tabindex="0" data-hour="${index}"><td>${esc(h.label || local(h.start))}</td><td>${esc(temp(h.forecast_c))}</td><td>${esc(temp(h.forecast_max_c))}</td><td class="${Number(h.revision_c)>0?'positive':Number(h.revision_c)<0?'negative':''}">${h.revision_c==null?'—':esc(`${Number(h.revision_c)>0?'+':''}${number(h.revision_c)}°C`)}</td><td>${reports.length?reports.map(r=>`<span class="temperature-chip" title="${esc(r.raw_text || '')}">${esc(local(reportTime(r)).split(' ')[0])} ${esc(number(r.temperature_c,0))}°${r.correction?' COR':''}${r.report_type==='SPECI'?' SPECI':''}</span>`).join(''):'—'}</td><td>${esc(temp(h.last_metar?.temperature_c ?? h.last_metar))}</td><td>${raw.length?`${raw.length} pom. · ${esc(temp(Math.min(...raw.map(x=>Number(x.temperature_c)))))} – ${esc(temp(Math.max(...raw.map(x=>Number(x.temperature_c)))))}<span class="secondary">kalibracja: ${pws.filter(p=>p.calibrated_temperature_c!=null).length} pom.${raw.some(p=>p.delta_metar_c!=null)?` · Δ METAR ${number(Math.min(...raw.filter(p=>p.delta_metar_c!=null).map(p=>p.delta_metar_c)))}…${number(Math.max(...raw.filter(p=>p.delta_metar_c!=null).map(p=>p.delta_metar_c)))}°C`:''}</span>`:'—'}</td><td class="${statusClass(h.quality)}">${esc(labelStatus(h.quality || (reports.length || pws.length?'AVAILABLE':'NO_DATA')))}</td></tr>`;}).join(''):'<tr><td colspan="8" class="empty">Brak tabeli wybranego dnia.</td></tr>';
    document.querySelectorAll('[data-hour]').forEach(row=>{row.addEventListener('click',()=>openHour(Number(row.dataset.hour)));row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')openHour(Number(row.dataset.hour));});});
  }
  function openHour(index) {
    const h=state.data?.hours?.[index];if(!h)return;text('hour-title',`${state.date} · ${h.label || local(h.start)}`);
    const reports=h.metars||[],pws=h.pws||[];
    $('hour-detail').innerHTML=`<section class="detail-section"><h3>Oficjalne raporty · temperatura całkowita °C</h3><div class="table-scroll"><table class="data-table detail-table"><thead><tr><th>Nominalny pomiar</th><th>Pierwszy odbiór</th><th>°C</th><th>Typ</th><th>Oryginalny raport</th></tr></thead><tbody>${reports.length?reports.map(r=>`<tr><td>${esc(local(reportTime(r),true))}</td><td>${esc(local(receipt(r),true))}</td><td>${esc(number(r.temperature_c,0))}</td><td>${esc(r.report_type || 'METAR')}${r.correction?' COR':''}</td><td>${esc(r.raw_text)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">Brak otrzymanych raportów.</td></tr>'}</tbody></table></div></section><section class="detail-section"><h3>Indywidualne pomiary PWS · bez interpolacji</h3><div class="table-scroll"><table class="data-table detail-table"><thead><tr><th>Stacja / czujnik</th><th>Pomiar</th><th>Pierwszy odbiór</th><th>Surowe °C</th><th>Kalibracja °C</th><th>Jakość / pochodzenie czasu</th></tr></thead><tbody>${pws.length?pws.map(p=>`<tr><td>${esc(p.name || p.station_name || p.sensor_id || p.station_id)}</td><td>${esc(local(p.measurement_time || p.observation_time,true))}</td><td>${esc(local(receipt(p),true))}</td><td>${esc(number(p.temperature_c,2))}</td><td>${esc(number(p.calibrated_temperature_c,2))}</td><td>${esc(labelStatus(p.qc_status || p.status || '—'))}<span class="secondary">${esc(p.provenance || p.timestamp_provenance || '')}</span></td></tr>`).join(''):'<tr><td colspan="6" class="empty">Brak kwalifikujących się pomiarów.</td></tr>'}</tbody></table></div></section>`;
    $('hour-dialog').showModal();
  }
  function marketTable(data) {
    const markets=data.markets||[];
    if(!markets.some(m=>m.condition_id===state.selectedMarket))state.selectedMarket=markets[0]?.condition_id || '';
    $('market-select').innerHTML=markets.length?markets.map(m=>`<option value="${esc(m.condition_id)}">${esc(m.outcome_label || m.title || m.slug)}</option>`).join(''):'<option value="">Brak kontraktów EPWA</option>';
    $('market-select').value=state.selectedMarket;
    $('market-body').innerHTML=markets.length?markets.map((m,index)=>{const yes=m.yes||{},no=m.no||{},when=m.book_time || yes.received_at || no.received_at;return `<tr data-market="${index}" tabindex="0" class="${state.selectedMarket===m.condition_id?'selected':''}"><td>${esc(m.outcome_label || m.title || '—')}<span class="secondary">${esc(m.station || 'nieznana stacja')}</span></td><td class="yes-color">${esc(price(yes.bid))} / ${esc(price(yes.ask))}<span class="secondary">spread ${esc(price(yes.spread))}</span></td><td class="no-color">${esc(price(no.bid))} / ${esc(price(no.ask))}<span class="secondary">spread ${esc(price(no.spread))}</span></td><td><span class="yes-color">Y ${esc(number(yes.bid_size,1))} / ${esc(number(yes.ask_size,1))}</span><span class="secondary">N ${esc(number(no.bid_size,1))} / ${esc(number(no.ask_size,1))}</span></td><td class="${statusClass(yes.status)}">${esc(labelStatus(yes.status || m.status))}<span class="secondary">${esc(local(when))}</span></td></tr>`;}).join(''):'<tr><td colspan="5" class="empty">Brak dostępnych kontraktów ze zweryfikowaną referencją EPWA.</td></tr>';
    document.querySelectorAll('[data-market]').forEach(row=>{const choose=()=>chooseMarket(markets[Number(row.dataset.market)]?.condition_id);row.addEventListener('click',choose);row.addEventListener('keydown',e=>{if(e.key==='Enter')choose();});});
    const selected=selectedMarket(data);text('market-detail',selected ? `${selected.title || selected.outcome_label || ''} · ${labelStatus(selected.status)} · last trade YES ${price(selected.yes?.last_trade)}, NO ${price(selected.no?.last_trade)}. Bid/ask i ilości są obserwacjami ofert, nie gwarantowanym wykonaniem.` : 'Brak poprawnie zidentyfikowanego rynku.');
  }
  function chooseMarket(id) {state.selectedMarket=id||'';if(!state.data)return;marketTable(state.data);if(marketChart)marketChart.setOption(preserveZoom(marketChart,marketOptions(state.data)),{replaceMerge:['series']});scheduleInspect(state.replayAt || Date.now());}
  function stations(data) {
    const list=data.stations||[],selected=list.filter(s=>s.selected!==false);
    text('station-count',`${selected.length} wybranych instrumentów · ${new Set(selected.map(s=>s.station_id)).size} stacji`);
    $('station-grid').innerHTML=selected.length?selected.map((s,index)=>`<article class="panel station-card"><div class="station-heading"><div><h3 style="color:${colors[index%colors.length]}">${esc(s.name || s.station_id)}</h3><span class="micro">${esc(s.model || 'Model instrumentu nieznany')}</span></div><span class="station-distance">${esc(number(s.distance_km,2))} km</span></div><div class="station-values"><div><strong>${esc(number(s.raw_temperature_c,2))}°</strong><label>surowe</label></div><div class="corrected"><strong>${esc(number(s.calibrated_temperature_c,2))}°</strong><label>kalibracja przyczynowa</label></div></div><div class="station-meta"><span>Pomiar lokalny</span><span>${esc(local(s.measurement_time))}</span><span>Pierwszy odbiór</span><span>${esc(local(s.first_received))}</span><span>Wiek przy odbiorze</span><span>${s.age_seconds==null?'—':`${esc(number(s.age_seconds,0))} s`}</span><span>Offset / integer</span><span>${esc(temp(s.bias_c))} / ${esc(s.predicted_integer ?? '—')}°</span></div><div class="station-status ${statusClass(s.status || s.qc_status)}">${esc(labelStatus(s.status || s.qc_status))}<span class="secondary micro"> · ${esc(s.provenance || 'nieznane pochodzenie czasu')}</span></div><div class="station-id">${esc(s.sensor_id || s.station_id)}</div></article>`).join(''):'<article class="panel empty">Nie znaleziono wybranych czujników. Brak danych nie oznacza temperatury zero.</article>';
    const references=data.weathercloud || [];
    $('weathercloud-links').innerHTML=references.length?references.map(s=>`<div><a href="${esc(safeURL(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a><div class="micro">${esc(s.model || 'Sprzęt nieznany')} · ${s.verification==='PROFILE_VERIFIED_READ_API_UNKNOWN'?'profil potwierdzony; odczyt API nieznany':'przypisanie niepotwierdzone'}</div></div>`).join(''):'<span class="micro">Brak zweryfikowanych przypisań referencji.</span>';
  }
  function render(data) {sourceStrip(data);hero(data);marketTable(data);renderCharts(data);hours(data);stations(data);const start=ms(data.day_start),end=ms(data.day_end);$('time-scrubber').max=String(Math.max(1,Math.round((end-start)/1000)-1));if(state.replayAt==null)state.replayAt=Math.min(Date.now(),end-1);$('time-scrubber').value=String(Math.max(0,Math.round((state.replayAt-start)/1000)));text('scrub-time',local(state.replayAt));text('footer-status',`Odczyt ${local(data.generated_at)} · strefa Europe/Warsaw · ${Math.round((end-start)/3600000)} h w tym dniu`);}
  async function loadDay() {
    const id=++state.fetchId,date=state.date;let url=`/api/day?date=${encodeURIComponent(date)}`;
    if(!state.live && state.replayAt!=null)url+=`&asof=${encodeURIComponent(iso(state.replayAt))}`;
    try {const data=await getJSON(url);if(id!==state.fetchId)return;state.data=data;state.lastLoad=Date.now();$('error-banner').classList.add('hidden');render(data);scheduleInspect(state.live?(state.hoverAt??Date.now()):state.replayAt || ms(data.cutoff));}catch(error){if(id===state.fetchId)showError(error);}
  }
  function scheduleRefresh() {if(state.replay)return;clearTimeout(state.refreshTimer);state.refreshTimer=setTimeout(()=>{if(Date.now()-state.lastLoad>=4000)loadDay();},300);}
  function scheduleInspect(value) {if(!state.data || !Number.isFinite(value))return;clearTimeout(state.inspectTimer);const at=Math.min(value,Date.now(),ms(state.data.day_end)-1);state.inspectTimer=setTimeout(()=>inspect(at),160);}
  async function inspect(at) {
    const id=++state.inspectId;try {const result=await getJSON(`/api/asof?date=${encodeURIComponent(state.date)}&at=${encodeURIComponent(iso(at))}&market=${encodeURIComponent(state.selectedMarket)}`);if(id!==state.inspectId)return;state.asof=result;renderInspect(result);}catch(error){if(id===state.inspectId)text('inspect-warning',`Podgląd czasu niedostępny: ${error.message}`);}
  }
  function renderInspect(data) {
    const at=data.at || data.cutoff, r=data.metar, f=data.forecast || {}, pws=data.pws||[];
    text('inspect-time',local(at,true));text('inspection-mode',state.replay?'ODTWARZANIE':Math.abs(Date.now()-ms(at))<15000?'TERAZ':'HISTORIA');
    text('inspect-metar',r?temp(r.temperature_c):'brak');text('inspect-metar-time',r?`Pomiar ${local(reportTime(r))} · odbiór ${local(receipt(r))}`:'Żaden raport nie był jeszcze dostępny.');
    text('inspect-forecast',temp(f.tmax?.temperature_c));text('inspect-forecast-time',f.first_received?`Snapshot odebrany ${local(f.first_received)} · max próbek godzinowych`:'Brak prognozy odebranej do tej chwili.');text('inspect-countdown',data.next_nominal_metar?`${local(data.next_nominal_metar).split(' ')[0]} · ${countdown(data.seconds_to_metar)}`:'—');
    $('inspect-pws').innerHTML=pws.length?pws.map(p=>`<div class="inspect-sensor"><span>${esc(p.name || p.sensor_id || p.station_id)}</span><strong>${esc(temp(p.raw_temperature_c ?? p.temperature_c))}</strong></div>`).join(''):'<span class="micro">Brak świeżych pomiarów z zaakceptowanym czasem.</span>';
    const market=data.market || (data.markets || []).find(m=>m.condition_id===state.selectedMarket) || data.markets?.[0];
    text('inspect-market',market?`${market.outcome_label || market.title || 'Kontrakt'} · YES ${price(market.yes?.bid)} / ${price(market.yes?.ask)} · NO ${price(market.no?.bid)} / ${price(market.no?.ask)} · ${labelStatus(market.yes?.status || market.status)}`:'Brak dostępnego arkusza dla tego momentu.');
    text('inspect-warning',(data.warnings||[]).map(x=>typeof x==='string'?x:JSON.stringify(x)).join(' · '));
  }
  function replayChanged(value) {if(!state.data)return;state.live=false;state.replayAt=ms(state.data.day_start)+Number(value)*1000;$('live-button').classList.remove('primary');text('scrub-time',local(state.replayAt));scheduleInspect(state.replayAt);}
  function goLive() {state.date=localDay();$('date-select').value=state.date;state.live=true;state.replay=false;state.replayAt=null;text('replay-toggle','▶ Odtwarzaj');$('replay-toggle').classList.remove('active');$('live-button').classList.add('primary');loadDay();}
  function tick() {
    const current=Date.now(),mono=performance.now(),elapsed=mono-state.lastTick;state.lastTick=mono;
    text('local-clock',new Intl.DateTimeFormat('pl-PL',{timeZone:TZ,day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(current)));
    text('utc-clock',`${new Date(current).toISOString().replace('T',' ').slice(0,19)} UTC`);
    if(state.replay && state.data) {
      const end=Math.min(ms(state.data.day_end)-1,current);state.replayAt=Math.min(end,(state.replayAt ?? ms(state.data.day_start))+elapsed*Number($('replay-speed').value));$('time-scrubber').value=String(Math.round((state.replayAt-ms(state.data.day_start))/1000));text('scrub-time',local(state.replayAt));if(state.replayAt>=end){state.replay=false;text('replay-toggle','▶ Odtwarzaj');$('replay-toggle').classList.remove('active');}scheduleInspect(state.replayAt);
      if(current-state.lastLoad>3000)loadDay();
    } else if(state.live && state.data) {state.replayAt=Math.min(current,ms(state.data.day_end)-1);$('time-scrubber').value=String(Math.round((state.replayAt-ms(state.data.day_start))/1000));text('scrub-time',local(state.replayAt));}
  }
  function init() {
    state.date=localDay();$('date-select').value=state.date;
    $('date-select').addEventListener('change',()=>{state.date=$('date-select').value;state.live=state.date===localDay();state.replay=false;state.replayAt=null;state.selectedMarket='';text('replay-toggle','▶ Odtwarzaj');$('live-button').classList.toggle('primary',state.live);loadDay();});
    $('live-button').addEventListener('click',goLive);
    $('market-select').addEventListener('change',e=>chooseMarket(e.target.value));
    $('time-scrubber').addEventListener('input',e=>replayChanged(e.target.value));
    $('time-scrubber').addEventListener('change',()=>loadDay());
    $('replay-toggle').addEventListener('click',()=>{if(!state.data)return;state.live=false;state.replay=!state.replay;if(state.replay && (!state.replayAt || state.replayAt>=Math.min(Date.now(),ms(state.data.day_end)-1)-1000))state.replayAt=ms(state.data.day_start);text('replay-toggle',state.replay?'Ⅱ Pauza':'▶ Odtwarzaj');$('replay-toggle').classList.toggle('active',state.replay);$('live-button').classList.remove('primary');state.lastTick=performance.now();loadDay();});
    $('close-hour').addEventListener('click',()=>$('hour-dialog').close());
    $('hour-dialog').addEventListener('click',event=>{if(event.target===$('hour-dialog'))$('hour-dialog').close();});
    const label=document.createElement('label');label.className='micro receipt-toggle';label.innerHTML='<input type="checkbox" id="receipt-toggle"> Pokaż momenty odbioru METAR';$('weather-chart').previousElementSibling.appendChild(label);$('receipt-toggle').addEventListener('change',event=>{state.receipts=event.target.checked;if(state.data)renderCharts(state.data);});
    const controls=document.createElement('div');controls.className='chart-filter-row';controls.innerHTML='<label class="micro"><input type="checkbox" id="other-sensors-toggle"> Pozostałe czujniki</label><label class="micro"><input type="checkbox" id="calibrated-series-toggle" checked> Linie kalibrowane PWS</label><span class="micro">Domyślnie: aktualnie wybrane instrumenty</span>';$('weather-chart').parentElement.insertBefore(controls,$('weather-chart'));
    $('other-sensors-toggle').addEventListener('change',event=>{state.showOtherSensors=event.target.checked;if(state.data)renderCharts(state.data);});
    $('calibrated-series-toggle').addEventListener('change',event=>{state.showCalibrated=event.target.checked;if(state.data)renderCharts(state.data);});

    const markerControls=document.createElement('label');markerControls.className='micro';markerControls.innerHTML='<input type="checkbox" id="pws-marker-toggle"> Znaczniki sygnałów PWS';$('market-chart').parentElement.insertBefore(markerControls,$('market-chart'));$('pws-marker-toggle').addEventListener('change',event=>{state.pwsMarkers=event.target.checked;if(state.data)renderCharts(state.data);});
    loadDay();tick();setInterval(tick,1000);setInterval(()=>{if(state.live)loadDay();},15000);
    if(window.EventSource) {const events=new EventSource('/api/events');const update=()=>{text('connection','● API połączone');$('connection').className='connection';if(state.live)scheduleRefresh();};events.onopen=update;events.onmessage=update;['refresh','update','change','tick'].forEach(type=>events.addEventListener(type,update));events.onerror=()=>{text('connection','● Ponowne łączenie');$('connection').className='connection degraded';};}
    window.dashboard={state,loadDay,inspect,goLive,chooseMarket,openHour,get weatherChart(){return weatherChart;},get marketChart(){return marketChart;}};
  }
  document.addEventListener('DOMContentLoaded',init);
})();
