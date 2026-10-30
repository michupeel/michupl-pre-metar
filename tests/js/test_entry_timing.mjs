/* Dependency-free DOM behavior tests; synthetic values are fixtures only. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const byId = new Map();
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.textContent = ''; }
  set id(value) { byId.set(value, this); }
  set innerHTML(value) { throw new Error(`Untrusted HTML insertion: ${value}`); }
  append(...children) { this.children.push(...children); }
  after(child) { this.append(child); }
  replaceChildren(...children) { this.children = [...children]; this.textContent = ''; }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
const text = element => [element.textContent, ...element.children.map(text)].join(' ');
const elements = (element, tag) => [
  ...(element.tag === tag ? [element] : []), ...element.children.flatMap(child => elements(child, tag))
];
const anchor = new Element('section');
anchor.id = 'd1-panel';
let initialize;
let tick;
let requested = 0;
const catalog = {
  version: 'SYNTHETIC_TEST', published_at: '2026-10-29T12:00:00Z', snapshot_cutoff: '2026-10-29T11:59:00Z',
  groups: {
    ALL: {
      n: 12, schedule_n: 10, unknown_station_n: 2, independent_executions: 8,
      percentages: { within_30s: 20, within_60s: 30, within_180s: 60, before: 40, after: 60, exact_nominal: 0 },
      median_offset_seconds: 45,
      hist: [{ label: '<img src=x onerror=evil()>', count: 4 }],
      control: { status: 'NOT_IDENTIFIABLE' },
      examples: [{ station: '<script>evil()</script>', price: '0.98' }]
    },
    EPWA: { n: 2, schedule_n: 2, hist: [], percentages: {}, examples: [] }
  }, limitations: ['Uncertainty is retained.']
};
const context = {
  window: { dashboard: { state: { live: true, hoverAt: Date.parse('2026-10-29T13:00:00Z') } } },
  document: {
    createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag),
    getElementById: id => byId.get(id), querySelector: () => anchor,
    addEventListener: (name, callback) => { initialize = callback; }
  },
  fetch: async url => {
    assert.equal(url, '/static/entry_timing_summary.json'); requested++;
    return { ok: true, json: async () => catalog };
  },
  setInterval: callback => { tick = callback; }, Date, Number, String, Math, NaN
};
vm.runInNewContext(await readFile('src/premetar/dashboard/static/entry_timing.js', 'utf8'), context);
initialize();
await new Promise(resolve => setImmediate(resolve));
const panel = byId.get('entry-timing-panel');
assert(panel);
assert.match(text(panel), /HIGH TEMPTATION — ENTRY TIMING/);
assert.match(text(panel), /NOT_IDENTIFIABLE/);
assert.match(text(panel), /<script>evil\(\)<\/script>/); // Text, never executable HTML.
assert.match(text(panel), /30%/);
const select = elements(panel, 'select')[0];
select.value = 'EPWA'; select.events.change();
assert.match(text(panel), /Brak zweryfikowanego dopasowania do harmonogramu/);
assert.doesNotMatch(text(panel), /<script>/);
context.window.dashboard.state.live = false;
context.window.dashboard.state.replayAt = Date.parse('2026-10-28T13:00:00Z');
tick();
assert.match(text(panel), /Ten audyt nie był jeszcze dostępny/);
assert.doesNotMatch(text(panel), /Rekordy BUY NO/);
assert.equal(requested, 1); // Replay ticks cannot multiply source/API requests.
console.log('entry_timing DOM: rendering, safe text, EPWA switch, replay cutoff and bounded fetch PASS');
