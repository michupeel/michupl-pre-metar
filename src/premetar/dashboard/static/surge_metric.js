/* Pure DOM component only; replay/fetch owned by integration layer. */
function surgeMetric(label, value) {
  var card = document.createElement('article');
  card.className = 'entry-timing-metric';
  var heading = document.createElement('span');
  heading.textContent = String(label);
  var count = document.createElement('strong');
  count.textContent = value == null ? '\u2014' : String(value);
  card.appendChild(heading);
  card.appendChild(count);
  return card;
}
window.michuplSurgeMetric = surgeMetric;
