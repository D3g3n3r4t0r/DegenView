import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../static/onchain/lab-shown.js', import.meta.url), 'utf8');
const { shownSummary, shownTrades } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

// main._lab_summary, the same fields the Top list receives
function summaryOf(lab) {
  const traded = (lab.rows ?? []).filter((r) => r.trades && r.return_pct != null && ['Trend EMA', 'Trend HF'].includes(r.label));
  const best = traded.sort((a, b) => b.return_pct - a.return_pct)[0];
  const d = lab.daily, drow = d?.rows?.[0];
  return { best: best ? { label: best.label, return_pct: best.return_pct, trades: best.trades } : null,
    daily: drow?.trades ? { interval: d.interval, return_pct: drow.return_pct, trades: drow.trades, in_position: drow.in_position } : null };
}
const buy = (t) => ({ t, side: 'buy', price: 1 }), sell = (t, ret) => ({ t, side: 'sell', price: 2, ret });
const fast = { rows: [{ label: 'Trend HF', trades: 2, return_pct: 400 }, { label: 'RSI+BB', trades: 5, return_pct: 900 }],
  best: { label: 'Trend HF', events: [buy(1), sell(2, 1), buy(3), sell(4, 1)] } };

test('a gem whose 8h trend follower stayed out shows the 5-minute trades it lists (MERRYMEN)', () => {
  const lab = { ...fast, daily: { interval: '8h', rows: [{ label: 'Trend EMA', trades: 0, return_pct: 0 }], best: null } };
  const s = shownSummary(summaryOf(lab)), c = shownTrades(lab);
  assert.equal(s.return_pct, 400); assert.equal(s.interval, '5m');
  assert.equal(c.interval, s.interval); assert.equal(c.events.filter((e) => e.side === 'sell').length, s.trades);
});
test('the 8h/1d trend follower leads when it traded, on both sides', () => {
  const lab = { ...fast, daily: { interval: '8h', rows: [{ label: 'Trend EMA', trades: 1, return_pct: 30 }],
    best: { label: 'Trend EMA', events: [buy(10), sell(20, 0.3)] } } };
  const s = shownSummary(summaryOf(lab)), c = shownTrades(lab);
  assert.equal(s.interval, '8h'); assert.equal(c.interval, '8h'); assert.equal(c.events.length, 2);
  assert.equal(c.events.filter((e) => e.side === 'sell').length, s.trades);
});
test('no trade anywhere: nothing in the list, nothing claimed on the chart', () => {
  const lab = { rows: [{ label: 'Trend EMA', trades: 0, return_pct: 0 }], daily: null };
  assert.equal(shownSummary(summaryOf(lab)), null); assert.equal(shownTrades(lab), null);
});
test('a mean-reversion result is never listed nor drawn for a gem', () => {
  const lab = { rows: [{ label: 'RSI+BB', trades: 3, return_pct: 500 }], best: null, daily: null };
  assert.equal(shownSummary(summaryOf(lab)), null); assert.equal(shownTrades(lab), null);
});
