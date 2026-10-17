/**
 * The charts wear the app's skin (07/10: "il tema dei grafici deve essere
 * allineato ai colori del sito e al tema utilizzato nell'app in ogni
 * aspetto"). Lightweight Charts draws on a canvas and cannot read CSS, so
 * the colours and the font are read from the same tokens the page uses:
 * on the phone the black-and-amber terminal (classic.css), on the desktop
 * its own skin. Crossing the 1100px line swaps the skin, and every live
 * chart is repainted with it.
 */

const SKIN = matchMedia("(max-width:1099px)");
const live = new Set();   // { chart, series, kind }

// Canvas gradients want a plain colour: "#7fd17f" at 22% -> rgba().
function alpha(hex, a) {
  let m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex)?.[1];
  if (!m) return hex;
  if (m.length === 3) m = [...m].map((x) => x + x).join("");
  const n = parseInt(m, 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

function token(style, names, fallback) {
  for (const n of names) {
    const v = style.getPropertyValue(n).trim();
    if (v) return v;
  }
  return fallback;
}

/** The palette of the skin on screen now. */
export function chartTheme() {
  const s = getComputedStyle(document.documentElement);
  return {
    up: token(s, ["--up", "--k-green"], "#2de0a8"),
    down: token(s, ["--down", "--k-red"], "#f87171"),
    amber: token(s, ["--amber", "--k-amber"], "#f0b90b"),
    ink: token(s, ["--ink", "--k-text"], "#e8e3d3"),
    faint: token(s, ["--ink-faint", "--k-text-3"], "#9aa0ab"),
    line: token(s, ["--line", "--k-line"], "#2a2924"),
    raised: token(s, ["--raised", "--c-pill", "--k-surface"], "#181713"),
    bg: token(s, ["--bg", "--k-bg"], "#0b0b09"),
    font: token(s, ["--mono"], "ui-monospace, monospace"),
  };
}

/** Chart-wide options: axes, grid, crosshair, font. Dashed rules like the
 *  app's lists, no vertical grid, labels in the app's mono. */
export function chartOptions(t = chartTheme()) {
  return {
    layout: { background: { color: "transparent" }, textColor: t.faint, fontSize: 11, fontFamily: t.font, attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: t.line, style: 2 } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false },
    crosshair: {
      vertLine: { color: t.faint, style: 2, labelBackgroundColor: t.raised },
      horzLine: { color: t.faint, style: 2, labelBackgroundColor: t.raised },
    },
  };
}

/** Series options for the two kinds the app draws. */
export function seriesOptions(kind, t = chartTheme()) {
  if (kind === "candles") {
    return { upColor: t.up, downColor: t.down, borderVisible: false, wickUpColor: t.up, wickDownColor: t.down };
  }
  return { lineColor: t.up, topColor: alpha(t.up, 0.22), bottomColor: alpha(t.up, 0.02) };
}

/** Keep a chart in the current skin until it is dropped. */
export function track(chart, series, kind) {
  const item = { chart, series, kind };
  live.add(item);
  return () => live.delete(item);
}

// A new skin (crossing 1100px) or a new theme (theme.js, dark mode): the
// stylesheet applies on the same frame, so the colours are read on the next.
function repaint() {
  requestAnimationFrame(() => {
    const t = chartTheme();
    for (const item of live) {
      try {
        item.chart.applyOptions(chartOptions(t));
        item.series.applyOptions(seriesOptions(item.kind, t));
      } catch { live.delete(item); }
    }
  });
}

SKIN.addEventListener("change", repaint);
window.addEventListener("lae:theme", repaint);
