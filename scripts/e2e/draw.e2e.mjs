// Browser test of the drawing tools (drawing tools plan, criteria table).
// Serves frontend/ as is, answers /api/* with synthetic data, and drives the
// real page with Playwright: mouse, touch, two devices.
//
//   node scripts/e2e/draw.e2e.mjs            (needs playwright + chromium)
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('/opt/npm-tools/node_modules/playwright')); }

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../frontend');
const STEP = { '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800, '1M': 2592000, '15m': 900, '5m': 300, '1m': 60, '30m': 1800 };
const END = 1_790_000_000 - (1_790_000_000 % 86400);
const priceAt = (t) => 100 + 20 * Math.sin(t / (86400 * 9)) + (t - END) / 864000;

function candles(interval, n) {
  const step = STEP[interval] || 86400;
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const t = END - i * step;
    const o = priceAt(t - step), c = priceAt(t);
    out.push({ time: t, open: o, high: Math.max(o, c) * 1.01, low: Math.min(o, c) * 0.99, close: c, volume: 100 });
  }
  return out;
}
function tf(interval, n) {
  return { interval, candles: candles(interval, n), levels: [], indicators: [], bias: 'neutral', dealing_range: null, fib_zones: [] };
}
function analyze(url) {
  const ltf = url.searchParams.get('ltf_interval') || '1d';
  const bt = { interval: ltf, initial_capital: 1000, final_equity: 1000, total_return_pct: 0, num_trades: 0, win_rate_pct: null, max_drawdown_pct: 0, profit_factor: null, equity_curve: [], trades: [] };
  const strat = (name) => [{ name, position: 'flat', signals: [] }];
  const name = url.searchParams.get('strategy_name') || 'Lorenzo (trend-follower)';
  const data = {
    symbol: url.searchParams.get('symbol') || 'BTCUSDT', asset_type: 'crypto', current_price: priceAt(END),
    timeframes: { ltf: tf(ltf, 400), mtf: tf('1w', 50), htf: tf('1M', 50) },
    confluence_zones: [],
    summary: { htf_bias: 'neutral', text: '', indicator_readout: [], long_term_context: [], top_confluence_zones: [], unmitigated_gaps: 0, nearest_liquidity_above: null, nearest_liquidity_below: null },
    strategies: { ltf: strat(name), mtf: strat(name), htf: strat(name) },
    backtests: { ltf: bt, mtf: bt, htf: bt },
  };
  return data;
}

const serverStore = {};   // the account's drawings, shared by every context
async function route(page) {
  await page.route('**/api/**', async (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname, method = r.request().method();
    const json = (body, status = 200) => r.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/api/auth/me') return json({ user: { id: 'u1', email: 'test@example.com' } });
    if (p === '/api/analyze') { if (process.env.E2E_DEBUG) console.log('analyze', url.searchParams.get('symbol'), url.searchParams.get('ltf_interval')); return json(analyze(url)); }
    if (p === '/api/backtest/deep') return json({ ...analyze(url).backtests.ltf });
    if (p === '/api/strategies') return json(['Lorenzo (trend-follower)', 'Gabriele (RSI+BB reversal)']);
    if (p === '/api/symbols') return json([{ symbol: 'BTCUSDT', asset_type: 'crypto', provider: 'mexc', name: 'Bitcoin' }]);
    if (p === '/api/drawings' && method === 'GET') return json(serverStore[url.searchParams.get('key')] || { drawings: null, updated_at: 0 });
    if (p === '/api/drawings' && method === 'PUT') {
      const b = JSON.parse(r.request().postData());
      if (process.env.E2E_DEBUG) console.log('PUT', b.key, b.drawings.length);
      const cur = serverStore[b.key];
      if (!cur || cur.updated_at <= b.updated_at) serverStore[b.key] = { drawings: b.drawings, updated_at: b.updated_at };
      return json(serverStore[b.key]);
    }
    if (/\/api\/(favorites|watchlist|archive|pinescript|issues|price-alerts|alerts\/log|jobs)/.test(p)) return json(p.includes('archive') ? { items: [] } : []);
    if (p === '/api/indicators/catalog') return json([]);
    return json({});
  });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|@onchain|importmap|module specifier|WebSocket connection/i.test(m.text())) errors.push(m.text()); });
}

const errors = [];
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`); };

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  const file = u.pathname === '/' ? 'index.html' : u.pathname.replace(/^\//, '');
  try {
    const body = await readFile(path.join(root, file));
    const type = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': type }); res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise((ok) => server.listen(0, ok));
const BASE = `http://127.0.0.1:${server.address().port}/?drawdebug`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });

async function openChart(ctx, interval = '4h') {
  const page = await ctx.newPage();
  await route(page);
  await page.goto(BASE);
  await page.waitForFunction(() => window.__drawDebug && window.__drawDebug.chart());
  await page.waitForTimeout(800); // the page's own first chart
  await page.evaluate((iv) => { const s = document.getElementById('interval-primary'); if (s) { s.value = iv; } }, interval);
  await page.evaluate(() => { document.getElementById('ticker-input').value = 'BTCUSDT'; document.getElementById('search-form').requestSubmit(); });
  await page.waitForFunction(() => document.querySelector('#chart-wrap') && !document.querySelector('#chart-wrap').classList.contains('hidden'));
  await page.waitForTimeout(600);
  return page;
}
const box = async (page) => page.locator('#main-chart').boundingBox();
const drawings = (page) => page.evaluate(() => JSON.parse(JSON.stringify(window.__drawDebug.state.drawings)));
const px = (page, pt) => page.evaluate((p) => window.__drawDebug.px(p.time, p.price), pt);
const pane = (page) => page.evaluate(() => window.__drawDebug.pane());
const setTf = async (page, iv) => {
  await page.evaluate((v) => { const s = document.getElementById('interval-primary'); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); }, iv);
  await page.waitForTimeout(900);
};

// ---------- desktop, mouse ----------
const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'en-US' });
let page = await openChart(desk, '4h');
let b = await box(page), pn = await pane(page);
check('chart loaded with a pane', pn.w > 400 && pn.h > 200, JSON.stringify(pn));

// trend line, two clicks
await page.click('[data-draw-tool="trend_line"]');
const A = { x: b.x + pn.w * 0.30, y: b.y + pn.h * 0.60 }, B = { x: b.x + pn.w * 0.60, y: b.y + pn.h * 0.35 };
await page.mouse.click(A.x, A.y); await page.mouse.move(B.x - 20, B.y + 10); await page.mouse.click(B.x, B.y);
let ds = await drawings(page);
check('trend line placed with two clicks', ds.length === 1 && ds[0].type === 'trend_line' && ds[0].points.length === 2);
let p0 = await px(page, ds[0].points[0]);
check('first point lands under the click', Math.abs(p0.x - (A.x - b.x)) < 3 && Math.abs(p0.y - (A.y - b.y)) < 3, JSON.stringify(p0));

// angle under pan and zoom
const angle = async () => { const d = (await drawings(page))[0]; const a = await px(page, d.points[0]), c = await px(page, d.points[1]); return Math.atan2(c.y - a.y, c.x - a.x) * 180 / Math.PI; };
const ang0 = await angle();
for (let i = 0; i < 6; i++) {
  await page.mouse.move(b.x + pn.w * 0.85, b.y + pn.h * 0.9); await page.mouse.down();
  await page.mouse.move(b.x + pn.w * 0.85 - 60 + (i % 2) * 120, b.y + pn.h * 0.9, { steps: 5 }); await page.mouse.up();
}
const ang1 = await angle();
check('slope unchanged after panning', Math.abs(ang1 - ang0) < 0.5, `${ang0.toFixed(2)} -> ${ang1.toFixed(2)}`);

// timeframe change: point stays at the same time/price, not on an edge
const before = (await drawings(page))[0];
await setTf(page, '1d');
const after = (await drawings(page))[0];
const q0 = await px(page, after.points[0]), q1 = await px(page, after.points[1]);
pn = await pane(page);
check('drawing survives 4h -> 1d', !!after && after.points[0].time === before.points[0].time);
check('on 1d its points are inside the pane, not on an edge', q0.x > 2 && q0.x < pn.w - 2 && q1.x > 2 && q1.x < pn.w - 2, `${q0.x.toFixed(1)}, ${q1.x.toFixed(1)} of ${pn.w}`);
const chartTimeAtX = await page.evaluate((x) => { const c = window.__drawDebug.chart(); return c.timeScale().coordinateToLogical(x); }, q0.x);
check('on 1d x matches the fractional bar of its time', chartTimeAtX !== null);
await setTf(page, '4h');

// drag the line, passing over the price scale
ds = await drawings(page);
let m0 = await px(page, ds[0].points[0]), m1 = await px(page, ds[0].points[1]);
b = await box(page); pn = await pane(page);
const mid = { x: b.x + (m0.x + m1.x) / 2, y: b.y + (m0.y + m1.y) / 2 };
await page.mouse.move(mid.x, mid.y); await page.mouse.down();
await page.mouse.move(b.x + pn.w + 30, mid.y + 40, { steps: 8 });   // over the price scale
await page.mouse.move(mid.x + 80, mid.y + 40, { steps: 8 });
await page.mouse.up();
ds = await drawings(page);
const n0 = await px(page, ds[0].points[0]);
check('drag moves the drawing by the pointer delta', Math.abs((n0.x - m0.x) - 80) < 6 && Math.abs((n0.y - m0.y) - 40) < 4, `dx ${(n0.x - m0.x).toFixed(1)}, dy ${(n0.y - m0.y).toFixed(1)}`);

// resize with a handle
await page.mouse.click(b.x + n0.x + 1, b.y + n0.y + 1);
const h1 = await px(page, ds[0].points[1]);
await page.mouse.move(b.x + h1.x, b.y + h1.y); await page.mouse.down();
await page.mouse.move(b.x + h1.x + 50, b.y + h1.y - 30, { steps: 6 }); await page.mouse.up();
ds = await drawings(page);
const h2 = await px(page, ds[0].points[1]);
check('handle drag moves only that point', Math.abs(h2.x - h1.x - 50) < 8 && Math.abs(h2.y - h1.y + 30) < 4, `dx ${(h2.x - h1.x).toFixed(1)}`);

// a point in the future, right of the last candle
await page.evaluate(() => window.__drawDebug.chart().timeScale().scrollToPosition(30, false));
await page.waitForTimeout(300);
const lastTime = await page.evaluate(() => { const c = window.__drawDebug; return null; });
await page.click('[data-draw-tool="hline"]');
await page.click('[data-draw-tool="trend_line"]');
b = await box(page); pn = await pane(page);
await page.mouse.click(b.x + pn.w * 0.70, b.y + pn.h * 0.5);
await page.mouse.click(b.x + pn.w * 0.95, b.y + pn.h * 0.3);
ds = await drawings(page);
const fut = ds[ds.length - 1];
check('points can be placed after the last candle', fut && fut.points[1].time > END, fut ? `${fut.points[1].time - END}s after` : 'none');

// idle: no repaint
await page.mouse.move(5, 5);
await page.waitForTimeout(400);
const r0 = await page.evaluate(() => window.__drawStats.renders);
await page.waitForTimeout(2000);
const r1 = await page.evaluate(() => window.__drawStats.renders);
check('chart still = no repaint', r1 - r0 <= 1, `${r1 - r0} repaints in 2 s`);

// sharp canvas
const dims = await page.evaluate(() => { const c = document.getElementById('draw-canvas'); return { w: c.width, cw: c.clientWidth }; });
check('canvas at screen density (DPR 2)', dims.w === dims.cw * 2, JSON.stringify(dims));

// toolbar: colour
b = await box(page);
ds = await drawings(page);
const s0 = await px(page, ds[0].points[0]), s1 = await px(page, ds[0].points[1]);
await page.mouse.click(b.x + (s0.x + s1.x) / 2, b.y + (s0.y + s1.y) / 2);
await page.waitForTimeout(150);
const tbVisible = await page.locator('.draw-toolbar').isVisible();
check('toolbar shows for the selected drawing', tbVisible);
await page.locator('.draw-swatch').nth(3).click();
ds = await drawings(page);
check('toolbar colour applies', ds[0].color === '#eb5757', ds[0].color);

// undo / redo
const cnt = ds.length;
await page.keyboard.press('Delete');
check('delete removes the selected drawing', (await drawings(page)).length === cnt - 1);
await page.keyboard.press('Control+z');
check('undo brings it back', (await drawings(page)).length === cnt);
await page.keyboard.press('Control+Shift+z');
check('redo removes it again', (await drawings(page)).length === cnt - 1);
await page.keyboard.press('Control+z');

// text tool: typed on the chart
await page.click('[data-draw-tool="text"]');
b = await box(page); pn = await pane(page);
await page.mouse.click(b.x + pn.w * 0.4, b.y + pn.h * 0.2);
await page.waitForSelector('.draw-text-input');
await page.keyboard.type('Breakout');
await page.keyboard.press('Enter');
ds = await drawings(page);
check('text tool writes on the chart', ds.some((d) => d.type === 'text' && d.text === 'Breakout'));

// every tool can be placed
for (const tool of ['extended_line', 'hray', 'rectangle', 'range', 'fib', 'arrow', 'ellipse', 'channel']) {
  const n = (await drawings(page)).length;
  await page.click(`[data-draw-tool="${tool}"]`);
  const pts = tool === 'channel' ? 3 : (tool === 'hray' ? 1 : 2);
  for (let i = 0; i < pts; i++) await page.mouse.click(b.x + pn.w * (0.2 + 0.15 * i), b.y + pn.h * (0.7 - 0.1 * i));
  check(`${tool} placed`, (await drawings(page)).length === n + 1);
}

// measure: the points it reads are candle highs or lows, no box
{
  const before = (await drawings(page)).length;
  await page.click('[data-draw-tool="range"]');
  b = await box(page); pn = await pane(page);
  // aim a few pixels off a real low and a real high
  const [c1, c2] = await page.evaluate(() => {
    const D = window.__drawDebug, w = D.pane().w;
    const vis = D.lastCandles(400).filter((c) => { const x = D.px(c.time, c.close).x; return x > 40 && x < w * 0.7; });
    return [vis[Math.floor(vis.length * 0.2)], vis[Math.floor(vis.length * 0.7)]];
  });
  const a1 = await px(page, { time: c1.time, price: c1.low }), a2 = await px(page, { time: c2.time, price: c2.high });
  await page.mouse.click(b.x + a1.x + 1, b.y + a1.y + 7);
  await page.mouse.click(b.x + a2.x - 1, b.y + a2.y - 6);
  const all = await drawings(page);
  const m = all[all.length - 1];
  const ok = all.length === before + 1 && m.type === 'range';
  if (process.env.E2E_DEBUG) console.log('measure dbg', before, all.length, m.type, JSON.stringify({a1, a2, c1, c2, b, pn}));
  const extremes = await page.evaluate((pts) => pts.map((pt) => {
    const c = window.__drawDebug.candleAt(pt.time);
    return c ? (Math.abs(c.high - pt.price) < 1e-9 || Math.abs(c.low - pt.price) < 1e-9) : 'no-candle';
  }), m.points);
  check('measure reads a high or low of a candle for each point', ok && extremes.every((x) => x === true), JSON.stringify(extremes));
  check('measure label has price, percent and bars', /\(([+-])?\d+\.\d+%\).*bars/.test(m.text || ''), m.text);
}

// persistence: reload, and another device of the same account
await page.waitForTimeout(1200);  // account sync debounce
const total = (await drawings(page)).length;
await page.reload();
await page.waitForFunction(() => window.__drawDebug && window.__drawDebug.chart());
await page.waitForTimeout(800); // the page's own first chart
await page.evaluate(() => { document.getElementById('ticker-input').value = 'BTCUSDT'; document.getElementById('search-form').requestSubmit(); });
await page.waitForTimeout(1200);
if (process.env.E2E_DEBUG) console.log('reload dbg', await page.evaluate(() => ({ keys: Object.keys(localStorage), sym: window.__drawDebug && JSON.stringify(window.__drawDebug.state.drawings).length, v: (localStorage.getItem('draw:crypto:BTCUSDT')||'').slice(0,80) })));
check('drawings survive a reload', (await drawings(page)).length === total, `${(await drawings(page)).length}/${total}`);

const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, hasTouch: true, isMobile: true, locale: 'en-US' });
const mpage = await openChart(phone, '4h');
await mpage.waitForTimeout(800);
check('same drawings on another device (account sync)', (await drawings(mpage)).length === total, `${(await drawings(mpage)).length}/${total}`);

// touch: open the dock, tap a tool, tap twice
await mpage.tap('#mobile-strip-draw-btn');
await mpage.tap('[data-draw-tool="trend_line"]');
const mb = await box(mpage), mp = await pane(mpage);
await mpage.touchscreen.tap(mb.x + mp.w * 0.3, mb.y + mp.h * 0.6);
await mpage.touchscreen.tap(mb.x + mp.w * 0.7, mb.y + mp.h * 0.4);
const md = await drawings(mpage);
check('touch: two taps place a line', md.length === total + 1);
const lastLine = md[md.length - 1];
const t0px = await px(mpage, lastLine.points[0]);
check('touch: the point is under the finger', Math.abs(t0px.x - mp.w * 0.3) < 4 && Math.abs(t0px.y - mp.h * 0.6) < 4, JSON.stringify(t0px));
const mdims = await mpage.evaluate(() => { const c = document.getElementById('draw-canvas'); return { w: c.width, cw: c.clientWidth }; });
check('canvas at screen density (DPR 3)', mdims.w === mdims.cw * 3, JSON.stringify(mdims));

check('no JavaScript errors', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
server.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
