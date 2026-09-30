/**
 * Which backtest a gem shows: one rule for the Top list and the chart.
 *
 * Lorenzo, 30/09 (MERRYMEN, Rank #2): the list said about +400%, the chart
 * said "The strategy stayed out". The list fell back to the 5-minute
 * backtest when the 8h/1d trend follower had no trade, the chart only ever
 * drew the 8h/1d one. Now both ask this module: the 8h/1d trend follower
 * when it traded, else the best 5-minute trend follower, else nothing. The number in the
 * list and the arrows on the chart always come from the same trades.
 *
 * Pure functions, no DOM: frontend/tests/lab-shown.test.mjs checks them.
 */

const traded = (row) => row && (row.trades ?? 0) > 0 && row.return_pct != null;
// system.TREND_LABELS: only trend followers are listed and drawn for gems.
const TREND = new Set(["Trend EMA", "Trend HF"]);

/** From /api/onchain/top's summary (main._lab_summary). */
export function shownSummary(s) {
  if (!s) return null;
  const d = s.daily;
  if (d && (d.trades ?? 0) > 0) {
    return { source: "daily", interval: d.interval ?? "1d", return_pct: d.return_pct, trades: d.trades,
      in_position: Boolean(d.in_position), win_rate: d.win_rate ?? null };
  }
  if (traded(s.best)) {
    return { source: "fast", interval: "5m", label: s.best.label, return_pct: s.best.return_pct, trades: s.best.trades,
      in_position: false, win_rate: s.best.win_rate ?? null };
  }
  return null;
}

/** From the full lab result (/api/onchain/token backtests: strategy_lab.get). */
export function shownTrades(lab) {
  if (!lab) return null;
  const d = lab.daily;
  const drow = d?.rows?.[0];
  if (traded(drow)) {
    return { source: "daily", interval: d.interval ?? "1d", label: drow.label, events: d.best?.events ?? [],
      rug: d.rug ?? null, backtests: d };
  }
  const rows = (lab.rows ?? []).filter((r) => traded(r) && TREND.has(r.label)).sort((a, b) => b.return_pct - a.return_pct);
  if (rows.length) {
    return { source: "fast", interval: "5m", label: rows[0].label, events: lab.best?.events ?? [],
      rug: lab.rug ?? null, backtests: lab };
  }
  return null;
}
