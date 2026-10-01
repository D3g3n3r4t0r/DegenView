/**
 * Which backtest a gem shows: one rule for the Top list and the chart.
 *
 * Lorenzo, 30/09 (MERRYMEN, Rank #2): the list said about +400%, the chart
 * said "The strategy stayed out". The list fell back to the 5-minute
 * backtest when the 8h/1d trend follower had no trade, the chart only ever
 * drew the 8h/1d one. Now both ask this module: the higher return between
 * the 8h/1d trend follower and the best 5-minute listed strategy, else
 * nothing. The number in the list and the arrows on the chart always come
 * from the same trades.
 *
 * Pure functions, no DOM: frontend/tests/lab-shown.test.mjs checks them.
 */

const traded = (row) => row && (row.trades ?? 0) > 0 && row.return_pct != null;
// system.SPOT_LABELS: the trend followers and, since Lorenzo's 30/09
// evening message ("l'RSI piu' BB funziona apparentemente bene"), RSI+BB
// reversal, long only. The Top row shows the higher return between the
// 8h/1d trend follower and the best 5-minute listed strategy, a tie to
// the 8h/1d (system.shown).
const SPOT = new Set(["Trend EMA", "Trend HF", "RSI+BB"]);

/** From /api/onchain/top's summary (main._lab_summary). */
export function shownSummary(s) {
  if (!s) return null;
  const d = s.daily;
  const daily = d && (d.trades ?? 0) > 0 && d.return_pct != null
    ? { source: "daily", interval: d.interval ?? "1d", return_pct: d.return_pct, trades: d.trades,
      in_position: Boolean(d.in_position), win_rate: d.win_rate ?? null } : null;
  const fast = traded(s.best)
    ? { source: "fast", interval: "5m", label: s.best.label, return_pct: s.best.return_pct, trades: s.best.trades,
      in_position: false, win_rate: s.best.win_rate ?? null } : null;
  if (daily && fast) return fast.return_pct > daily.return_pct ? fast : daily;
  return daily ?? fast;
}

// The row whose trades are the saved chart events: same strategy, one
// sell per closed trade (system.drawn_row). Anything else would draw
// another strategy's arrows.
function drawnRow(part) {
  const best = part?.best;
  if (!best) return null;
  const row = (part.rows ?? []).find((r) => r.label === best.label && SPOT.has(r.label) && traded(r));
  if (!row) return null;
  return (best.events ?? []).filter((e) => e.side === "sell").length === row.trades ? row : null;
}

/** From the full lab result (/api/onchain/token backtests: strategy_lab.get). */
export function shownTrades(lab) {
  if (!lab) return null;
  const d = lab.daily;
  const drow = d ? drawnRow(d) : null;
  const frow = drawnRow(lab);
  const daily = drow ? { source: "daily", interval: d.interval ?? "1d", label: drow.label, events: d.best.events,
    rug: d.rug ?? null, backtests: d, return_pct: drow.return_pct } : null;
  const fast = frow ? { source: "fast", interval: "5m", label: frow.label, events: lab.best.events,
    rug: lab.rug ?? null, backtests: lab, return_pct: frow.return_pct } : null;
  if (daily && fast) return fast.return_pct > daily.return_pct ? fast : daily;
  return daily ?? fast;
}
