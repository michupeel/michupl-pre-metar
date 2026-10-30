/* EXP0017: read-only timing evidence; no trading or additional external requests. */
(() => {
  'use strict';
  const svgNS = 'http://www.w3.org/2000/svg';
  let catalog = null;
  let selection = 'ALL';
  let busy = false;
  let lastFetch = 0;
  let rendered = '';
  let liveCatalog = null;
  let liveRendered = '';
  let liveBusy = false;
  let lastLiveFetch = 0;
  let content;
  let stamp;
  let liveContent;

  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text != null) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  }

  function number(value, digits = 1) {
    return typeof value === 'number' && Number.isFinite(value)
      ? value.toLocaleString('pl-PL', { maximumFractionDigits: digits }) : '—';
  }

  function percent(value) {
    return typeof value === 'number' && Number.isFinite(value) ? `${number(value)}%` : '—';
  }

  function time(value) {
    const parsed = value ? new Date(value) : null;
    return parsed && Number.isFinite(parsed.getTime())
      ? `${parsed.toLocaleString('pl-PL', { timeZone: 'Europe/Warsaw', timeZoneName: 'short' })}` : '—';
  }

  function table(headers, rows) {
    const wrap = node('div', null, 'table-scroll');
    const result = node('table', null, 'data-table entry-timing-table');
    const head = node('thead');
    const header = node('tr');
    headers.forEach(text => header.append(node('th', text)));
    head.append(header);
    const body = node('tbody');
    rows.forEach(row => {
      const tr = node('tr');
      row.forEach(text => tr.append(node('td', text == null ? '—' : text)));
      body.append(tr);
    });
    if (!rows.length) {
      const tr = node('tr');
      const td = node('td', 'Brak danych w tej próbie.', 'empty');
      td.colSpan = headers.length;
      tr.append(td);
      body.append(tr);
    }
    result.append(head, body);
    wrap.append(result);
    return wrap;
  }

  function metric(label, value, note) {
    const result = node('article', null, 'entry-timing-metric');
    result.append(node('span', label, 'micro'), node('strong', value));
    if (note) result.append(node('span', note, 'micro'));
    return result;
  }

  function histogram(rows) {
    const figure = node('figure', null, 'entry-timing-histogram');
    figure.append(node('figcaption', 'Wykonane BUY NO względem najbliższego nominalnego METAR'));
    if (!rows.length) {
      figure.append(node('p', 'Brak zweryfikowanego dopasowania do harmonogramu.', 'empty'));
      return figure;
    }
    const width = 1020;
    const left = 300;
    const rowHeight = 34;
    const height = rows.length * rowHeight + 15;
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Histogram liczby wejść według przesunięcia od nominalnego METAR. Rozkład liczby transakcji nie jest skorygowaną częstością wejść.');
    const max = Math.max(1, ...rows.map(r => Number.isFinite(r.count) ? r.count : 0));
    rows.forEach((row, index) => {
      const y = index * rowHeight + 5;
      const count = typeof row.count === 'number' && Number.isFinite(row.count) && row.count >= 0 ? row.count : 0;
      const label = document.createElementNS(svgNS, 'text');
      label.setAttribute('x', left - 12);
      label.setAttribute('y', y + 17);
      label.setAttribute('text-anchor', 'end');
      label.textContent = String(row.label ?? 'Nieznany przedział');
      const rect = document.createElementNS(svgNS, 'rect');
      rect.setAttribute('x', left);
      rect.setAttribute('y', y);
      rect.setAttribute('height', 24);
      rect.setAttribute('width', Math.max(0, count / max * 610));
      rect.setAttribute('rx', 3);
      const countLabel = document.createElementNS(svgNS, 'text');
      countLabel.setAttribute('x', left + count / max * 610 + 9);
      countLabel.setAttribute('y', y + 17);
      countLabel.textContent = number(row.count, 0);
      svg.append(label, rect, countLabel);
    });
    figure.append(svg);
    figure.append(node('p', 'Liczba rekordów ≠ natężenie handlu. Przedziały mają różny czas trwania; dowód klastrowania wymaga kontroli dopasowanej do aktywności rynku.', 'micro'));
    return figure;
  }

  function effectiveCutoff() {
    const state = window.dashboard?.state;
    if (!state) return NaN;
    return state.live ? (state.hoverAt ?? Date.now()) : (state.replayAt ?? Date.parse(state.data?.cutoff));
  }

  function renderLive() {
    if (!liveContent) return;
    const cutoff = effectiveCutoff();
    const published = Date.parse(liveCatalog?.published_at);
    const known = Number.isFinite(cutoff) && Number.isFinite(published) && published <= cutoff;
    const heartbeat = Date.parse(liveCatalog?.last_heartbeat);
    const stale = !Number.isFinite(heartbeat) || Date.now() - heartbeat > 90000 || heartbeat > Date.now() + 1000;
    const key = `${liveCatalog?.published_at}|${known}|${selection}|${stale}`;
    if (liveRendered === key) return;
    liveRendered = key;
    liveContent.replaceChildren();
    liveContent.append(node('h3', 'Prospektywny obserwator EXP0017'));
    if (!liveCatalog) {
      liveContent.append(node('p', 'Status nieznany — lokalny eksport obserwatora jeszcze niedostępny. Nie oznacza to zera nowych transakcji.', 'micro'));
      return;
    }
    if (!known) {
      liveContent.append(node('p', 'Ten eksport obserwatora nie był jeszcze dostępny w wybranej chwili. Nie pokazujemy później zarejestrowanych wejść w historycznym as-of.', 'micro'));
      return;
    }
    const counts = liveCatalog.counts ?? {};
    const count = counts.ENTRY_OBSERVED ?? counts.ENTRY;
    const status = liveCatalog.status === 'RUNNING' ? (stale ? 'NIEAKTUALNY HEARTBEAT' : 'DZIAŁA') : (liveCatalog.status === 'STOPPED' ? 'ZATRZYMANY' : 'NIEZNANY');
    liveContent.append(node('p', `Stan: ${status} · PID: ${liveCatalog.pid ?? '—'} · ostatni heartbeat: ${time(liveCatalog.last_heartbeat)} · nowe wejścia NO (wszystkie lotniska): ${number(count, 0)}.`, 'micro'));
    liveContent.append(node('p', 'Wyłącznie zdarzenia PROSPECTIVE_POLL po uruchomieniu obserwatora. Pierwsza detekcja pochodzi z istniejącego monitora; zapis sidecara następuje później. Startowy ogon i backfill nie są dowodem prospektywnym. Zmiana zakresu filtruje przykłady, nie globalny licznik.', 'micro'));
    const entries = (Array.isArray(liveCatalog.latest_entries) ? liveCatalog.latest_entries : []).filter(row => {
      const received = Date.parse(row.sidecar_capture_time);
      const detected = Date.parse(row.original_first_detection);
      return row.evidence_class === 'PROSPECTIVE_POLL' && Number.isFinite(received) && Number.isFinite(detected)
        && received <= cutoff && detected <= cutoff && (selection !== 'EPWA' || row.station === 'EPWA');
    });
    liveContent.append(table(
      ['Wykonanie (Warszawa)', 'Pierwsza detekcja', 'Stacja', 'Cena NO', 'Ilość', 'Offset nominalny (s)', 'Pogoda przed wykonaniem', 'Transakcja'],
      entries.slice(-10).reverse().map(row => [time(row.source_trade_timestamp), time(row.original_first_detection), row.station, row.price, row.quantity, number(row.signed_offset_seconds), row.weather_status, row.transaction_hash])
    ));
    if (!entries.length) liveContent.append(node('p', 'Brak nowych, kwalifikujących się prospektywnych wejść w wyświetlanym zakresie. Nie tworzymy przykładów syntetycznych.', 'micro'));
  }

  function render() {
    renderLive();
    if (!catalog || !content) return;
    const cutoff = effectiveCutoff();
    const published = Date.parse(catalog.published_at);
    const known = Number.isFinite(cutoff) && Number.isFinite(published) && published <= cutoff;
    const key = `${catalog.published_at}|${known}|${selection}`;
    if (key === rendered) return;
    rendered = key;
    content.replaceChildren();
    stamp.textContent = `Audyt utworzony: ${time(catalog.published_at)} · odcięcie danych: ${time(catalog.snapshot_cutoff)} · ${catalog.version ?? 'Wersja nieznana'}`;
    if (!known) {
      content.append(node('p', 'Ten audyt nie był jeszcze dostępny w wybranej chwili. Wyników pozyskanych później nie pokazujemy jako wiedzy historycznej.', 'empty'));
      return;
    }
    const group = catalog.groups?.[selection];
    if (!group) {
      content.append(node('p', 'Brak danych dla wybranego zakresu. Nie przenosimy wyniku innych lotnisk na EPWA.', 'empty'));
      return;
    }
    const p = group.percentages ?? {};
    content.append(node('p', `Zakres główny: ${catalog.scope ?? 'Zakres nieudokumentowany — sprawdź eksport.'}`, 'entry-timing-warning'));
    content.append(node('p', `Typ oryginalnego raportu niezweryfikowany: ${number(group.nominal_type_unverified_n, 0)} rekordów. Dopasowania do cyklicznej serii nominalnej nie certyfikują wykluczenia SPECI ani czasu publicznej publikacji. Dopasowania ze ściśle znanym oryginalnym typem: ${number(group.strict_original_type_aligned_n, 0)}.`, 'micro'));
    const metrics = node('div', null, 'entry-timing-metrics');
    metrics.append(
      metric('Rekordy BUY NO', number(group.n, 0), `Dopasowane do harmonogramu: ${number(group.schedule_n, 0)}`),
      metric('Grupy wykonań', number(group.independent_executions, 0), 'Grupowanie wykonań nie dowodzi czasu decyzji'),
      metric('W ±30 sekund', percent(p.within_30s), 'Wśród rekordów z harmonogramem'),
      metric('W ±1 minutę', percent(p.within_60s), 'Wśród rekordów z harmonogramem'),
      metric('W ±3 minuty', percent(p.within_180s), 'Wśród rekordów z harmonogramem'),
      metric('Mediana przesunięcia', typeof group.median_offset_seconds === 'number' ? `${number(group.median_offset_seconds)} s` : '—', 'Minus: przed · plus: po nominalnym METAR')
    );
    content.append(metrics);
    content.append(node('p', `Przed nominalnym: ${percent(p.before)} · po nominalnym: ${percent(p.after)} · dokładnie nominalnie: ${percent(p.exact_nominal)}. Nieznana stacja: ${number(group.unknown_station_n, 0)}.`, 'micro'));
    content.append(histogram(Array.isArray(group.hist) ? group.hist : []));
    const controls = group.control ?? {};
    const evidence = node('div', null, 'entry-timing-evidence');
    evidence.append(node('h3', 'Potwierdzone odbiory i ograniczenia wnioskowania'));
    evidence.append(node('p', `Znany współczesny pierwszy odbiór METAR: ${number(group.receipt_known_n, 0)} rekordów. Odbiór poprzedzający zakup: ${number(group.known_before_trade_n, 0)}. To nasz lokalny odbiór, nie dowód pierwszej globalnej publikacji.`, 'micro'));
    evidence.append(node('p', `Kontrast opisowy: ${controls.status ?? 'NIEZNANE'}. ${controls.description ?? ''}`, 'micro'));
    evidence.append(node('p', `Kontrast z równomierną fazą — bez kontroli aktywności rynku: ${number(controls.rate_ratio)} · przedział bootstrap: ${number(controls.ci_low)}–${number(controls.ci_high)}. To nie jest iloraz skorygowanych natężeń ani dowód istotności względem dopasowanego handlu rynkowego.`, 'micro'));
    content.append(evidence);
    content.append(node('h3', 'Cena wejścia i czas do końca lokalnego dnia'));
    content.append(table(
      ['Cena', 'Rekordy', 'Z harmonogramem', 'Mediana offsetu (s)', '±1 min', 'Minuty do końca dnia'],
      (group.price_groups ?? []).map(r => [r.price_bucket, number(r.n, 0), number(r.schedule_n, 0), number(r.median_offset_seconds), percent(r.within_60s_pct), number(r.median_minutes_to_day_end)])
    ));
    content.append(node('p', 'Koniec lokalnego dnia nie jest potwierdzonym czasem ostatecznej rezolucji. Przedział 0,90–0,97 nie obejmuje 0,98, a przedział >0,95 i <0,98 zawiera też ceny ułamkowe powyżej 0,97; nie utożsamiamy tych kohort. Dokładne ceny pozostają w eksporcie badania.', 'micro'));
    const exits = group.exits ?? {};
    content.append(node('h3', 'Późniejsze wykonane SELL — nie czas wystawienia zlecenia'));
    content.append(node('p', `Znany pierwszy późniejszy SELL: ${number(exits.first_sell_known_n, 0)} · warunkowo odtworzone pełne zamknięcia: ${number(exits.conditional_full_closure_n, 0)} · SELL 0,99: ${number(exits.sold_at_099_n, 0)}. Stan rekonstrukcji: ${exits.inventory_status ?? 'NIEZNANY'}.`, 'micro'));
    content.append(node('p', 'Szybki wykonany SELL nie potwierdza wcześniejszego wystawienia limitu ani kompletnego kosztu transakcji. W tym panelu nie wyliczamy nieudokumentowanego PnL.', 'micro'));
    content.append(node('h3', 'Rzeczywiste przykłady — czas wykonania, nie złożenia zlecenia'));
    const examples = Array.isArray(group.examples) ? group.examples : [];
    content.append(table(
      ['Wykonanie (Warszawa)', 'Stacja', 'Cena', 'Offset (s)', 'Pierwszy odbiór METAR', 'Późniejszy SELL / stan', 'Transakcja'],
      examples.slice(0, 20).map(r => [time(r.source_trade_timestamp), r.station, r.price, number(r.nearest_offset_seconds), time(r.first_metar_receipt), r.exit_status, r.transaction_hash])
    ));
    const limits = node('ul', null, 'entry-timing-limits');
    (catalog.limitations ?? []).forEach(text => limits.append(node('li', text)));
    content.append(limits);
  }

  async function refresh() {
    if (busy || Date.now() - lastFetch < 60000) return;
    busy = true;
    lastFetch = Date.now();
    try {
      const response = await fetch('/static/entry_timing_summary.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('unavailable');
      const received = await response.json();
      if (!received || typeof received !== 'object' || !received.groups) throw new Error('invalid');
      catalog = received;
      rendered = '';
      render();
    } catch {
      if (!catalog) content.textContent = 'Audyt EXP-0017 jeszcze niedostępny. Brak danych nie oznacza braku transakcji.';
      else stamp.textContent = `Ostatnia próba odczytu nieudana. Wyświetlany audyt: ${time(catalog.published_at)}.`;
    } finally {
      busy = false;
    }
  }

  async function refreshLive() {
    if (liveBusy || Date.now() - lastLiveFetch < 60000) return;
    liveBusy = true;
    lastLiveFetch = Date.now();
    try {
      const response = await fetch('/static/entry_timing_live.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('unavailable');
      const received = await response.json();
      if (!received || typeof received !== 'object' || !received.published_at) throw new Error('invalid');
      liveCatalog = received;
      liveRendered = '';
    } catch {
      // Missing sidecar export must never invalidate the frozen historical audit.
    } finally {
      liveBusy = false;
      renderLive();
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const panel = node('section', null, 'panel entry-timing-panel');
    panel.id = 'entry-timing-panel';
    panel.setAttribute('aria-label', 'HighTempTation — czas wejścia względem METAR');
    const heading = node('div', null, 'panel-heading');
    const title = node('div');
    title.append(node('span', 'EXP-0017 / BADANIE MECHANIZMU', 'eyebrow'), node('h2', 'HIGH TEMPTATION — ENTRY TIMING'));
    const label = node('label', 'ZAKRES ', 'contract-label');
    const select = node('select');
    select.setAttribute('aria-label', 'Zakres badania czasu wejścia');
    [['ALL', 'Wszystkie lotniska'], ['EPWA', 'Tylko EPWA']].forEach(([value, text]) => {
      const option = node('option', text);
      option.value = value;
      select.append(option);
    });
    select.addEventListener('change', () => { selection = select.value; render(); });
    label.append(select);
    heading.append(title, label);
    stamp = node('p', 'Oczekiwanie na audyt…', 'micro');
    content = node('div', 'Wczytywanie rzeczywistych danych badawczych…');
    liveContent = node('div', null, 'entry-timing-live');
    panel.append(heading,
      node('p', 'Czas nominalnego METAR ≠ publikacja ≠ decyzja tradera. Histogram pokazuje wykonania on-chain / z publicznego feedu, nie moment złożenia zlecenia. Analiza nie uruchamia strategii.', 'entry-timing-warning'),
      liveContent, stamp, content);
    const anchor = document.getElementById('settlement-history-panel') ?? document.getElementById('d1-panel');
    if (anchor) anchor.after(panel);
    else document.querySelector('.shell')?.append(panel);
    refresh();
    refreshLive();
    setInterval(() => { refresh(); refreshLive(); render(); }, 1000);
  });
})();
