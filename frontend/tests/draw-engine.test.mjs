// Drawing engine (drawing tools plan): where a point lands and what a
// click hits. node --test frontend/tests/draw-engine.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const E = require('../static/draw-engine.js');

const H4 = 4 * 3600, DAY = 86400;
const times4h = Array.from({ length: 300 }, (_, i) => 1_700_000_000 + i * H4);
const timesDay = Array.from({ length: 50 }, (_, i) => 1_700_000_000 + i * DAY);

test('a candle time maps to its own index, and back', () => {
  const m = E.makeTimeMapper(times4h);
  assert.equal(m.timeToLogical(times4h[42]), 42);
  assert.equal(m.logicalToTime(42), times4h[42]);
});

test('a 4h point on a daily chart lands between two candles, not on an edge', () => {
  const m = E.makeTimeMapper(timesDay);
  const t = 1_700_000_000 + 10 * DAY + 2 * H4;   // 10 days + 8 hours
  const l = m.timeToLogical(t);
  assert.ok(Math.abs(l - (10 + 8 / 24)) < 1e-9);
  assert.equal(m.logicalToTime(l), t);
});

test('before the first and after the last candle the step of the timeframe is used', () => {
  const m = E.makeTimeMapper(times4h);
  assert.equal(m.timeToLogical(times4h[0] - 5 * H4), -5);
  assert.equal(m.timeToLogical(times4h[299] + 12 * H4), 311);
  assert.equal(m.logicalToTime(311), times4h[299] + 12 * H4);
});

test('a weekend gap does not change the step used for the future', () => {
  const t = [];
  let x = 1_700_000_000;
  for (let i = 0; i < 40; i++) { t.push(x); x += (i % 5 === 4) ? 3 * DAY : DAY; }
  const m = E.makeTimeMapper(t);
  assert.equal(m.stepLast, DAY);
});

test('hit test: line, extended line, rectangle, ellipse contour vs corner', () => {
  const env = { w: 800, h: 400, priceToY: (p) => 400 - p };
  const P = [{ x: 100, y: 100 }, { x: 300, y: 300 }];
  assert.ok(E.hitTest({ type: 'trend_line' }, P, 200, 203, env));
  assert.ok(!E.hitTest({ type: 'trend_line' }, P, 400, 400, env));
  assert.ok(E.hitTest({ type: 'extended_line' }, P, 500, 500, env));
  assert.ok(E.hitTest({ type: 'rectangle' }, P, 150, 250, env));
  assert.ok(E.hitTest({ type: 'ellipse' }, P, 200, 200, env));
  assert.ok(!E.hitTest({ type: 'ellipse' }, P, 105, 105, env), 'empty corner of the box is not the ellipse');
});

test('channel: v2 passes through its third point, legacy keeps its old offset', () => {
  const p1 = { time: 0, price: 100 }, p2 = { time: 10, price: 110 }, p3 = { time: 5, price: 120 };
  assert.equal(E.channelOffset({ v: 2, points: [p1, p2, p3] }), 15);   // line is 105 at t=5
  assert.equal(E.channelOffset({ points: [p1, p2, p3] }), 20);         // old: p3 - p1
});

test('channel hit includes the parallel line and the band between', () => {
  const env = { w: 800, h: 400 };
  const P = [{ x: 0, y: 100 }, { x: 200, y: 100 }];
  P.offsetY = { a: 50, b: 50 };
  assert.ok(E.hitTest({ type: 'channel' }, P, 100, 150, env));
  assert.ok(E.hitTest({ type: 'channel' }, P, 100, 125, env));
  assert.ok(!E.hitTest({ type: 'channel' }, P, 100, 190, env));
});

test('fib hits its levels and its extensions', () => {
  const env = { w: 800, h: 400, priceToY: (p) => 400 - p };
  const d = { type: 'fib', points: [{ time: 0, price: 100 }, { time: 1, price: 200 }] };
  const P = [{ x: 100, y: 300 }, { x: 300, y: 200 }];
  assert.ok(E.hitTest(d, P, 200, 400 - 161.8, env));      // 0.618
  assert.ok(E.hitTest(d, P, 200, 400 - 261.8, env));      // 1.618 extension
  assert.ok(!E.hitTest(d, P, 200, 400 - 130, env));      // between 0.236 and 0.382
});

test('range label counts bars and keeps the sign', () => {
  const s = E.formatRange({ time: 0, price: 100 }, { time: 2 * DAY, price: 90 }, 12, (v) => v.toFixed(2));
  assert.equal(s, '-10.00 (-10.00%) · 2.0d · 12 bars');
});

test('paint runs for every tool on a recording context', () => {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (o, k) => (k in o ? o[k] : k === 'measureText' ? () => ({ width: 40 }) : (...a) => calls.push(k)),
    set: (o, k, v) => { o[k] = v; return true; },
  });
  const env = { w: 800, h: 400, priceToY: (p) => 400 - p, look: { panel: '#fff', ink: '#000', bull: '#00b894', bear: '#eb5757' }, state: { selected: true } };
  for (const type of Object.keys(E.POINTS).filter((t) => t !== 'cursor')) {
    const points = [{ time: 0, price: 100 }, { time: 1, price: 150 }, { time: 2, price: 170 }];
    const P = [{ x: 10, y: 300 }, { x: 200, y: 250 }, { x: 300, y: 230 }];
    P.offsetY = { a: 20, b: 20 };
    E.paint(ctx, { type, points, text: 'x', v: 2 }, P, env);
  }
  assert.ok(calls.includes('stroke') && calls.includes('fill'));
});

test('measure reads the nearest high or low under the pointer', () => {
  const candles = [{ time: 1, high: 110, low: 100 }, { time: 2, high: 120, low: 105 }, { time: 3, high: 115, low: 98 }];
  const priceToY = (p) => 500 - p * 2;          // 120 -> 260, 98 -> 304
  assert.deepEqual(E.pickExtreme(candles, 262, priceToY, 40), { time: 2, price: 120, side: 'high' });
  assert.deepEqual(E.pickExtreme(candles, 305, priceToY, 40), { time: 3, price: 98, side: 'low' });
  assert.equal(E.pickExtreme(candles, 100, priceToY, 40), null);   // too far from any wick
});

test('measure is hit on its line and its points, not inside a box', () => {
  const env = { w: 800, h: 400 };
  const P = [{ x: 100, y: 300 }, { x: 300, y: 100 }];
  assert.ok(E.hitTest({ type: 'range' }, P, 200, 200, env));
  assert.ok(E.hitTest({ type: 'range' }, P, 300, 100, env));
  assert.ok(!E.hitTest({ type: 'range' }, P, 280, 280, env), 'the empty corner of the old box');
});
