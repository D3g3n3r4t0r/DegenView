// Drawing engine for the classic chart (drawing tools plan, 12/10/2026).
//
// Pure geometry and painting, no DOM and no chart library: app.js hands it
// pixel points and a 2D context. Kept apart so the parts that went wrong —
// where a point lands, what a click hits, how a shape is painted — can be
// tested in node (frontend/tests/draw-engine.test.mjs).
//
// The core fix lives in makeTimeMapper: a drawing point is {time, price},
// and the chart only knew how to place a time that is EXACTLY one of its
// candles. On another timeframe, before the first candle or in the empty
// area after the last one there is no such candle, and the point was thrown
// to the canvas edge or not drawn at all. The mapper turns any time into a
// fractional "logical" bar index (interpolated between candles,
// extrapolated with the timeframe's step outside them), which the chart can
// always place with logicalToCoordinate.
//
// Classic script: sets globalThis.DrawEngine, and module.exports for tests.
(function (root) {
  "use strict";

  // 8 colours that read on the light paper and on the dark chart, and that
  // differ in lightness too, not only in hue.
  const PALETTE = ["#2f80ed", "#00b894", "#f2994a", "#eb5757", "#9b51e0", "#f2c94c", "#56ccf2", "#8d99ae"];
  const WIDTHS = [1, 2, 3];
  const DASHES = { solid: [], dashed: [6, 4], dotted: [1.5, 3.5] };
  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const FIB_EXTENSIONS = [1.272, 1.618];
  const POINTS = { cursor: 0, trend_line: 2, hline: 1, hray: 1, extended_line: 2, rectangle: 2, range: 2, fib: 2, text: 1, arrow: 2, channel: 3, ellipse: 2, fractal: 2 };

  // ---- time <-> logical bar index -------------------------------------
  function medianStep(times, fromEnd) {
    const n = times.length;
    if (n < 2) return 60;
    const diffs = [];
    const count = Math.min(20, n - 1);
    for (let k = 0; k < count; k++) {
      const i = fromEnd ? n - 1 - k : k + 1;
      const d = times[i] - times[i - 1];
      if (d > 0) diffs.push(d);
    }
    if (!diffs.length) return 60;
    diffs.sort((a, b) => a - b);
    return diffs[Math.floor(diffs.length / 2)];
  }

  function makeTimeMapper(times) {
    const t = Array.from(times || []);
    const n = t.length;
    const stepFirst = medianStep(t, false);
    const stepLast = medianStep(t, true);
    function timeToLogical(time) {
      if (!n || time == null || !isFinite(time)) return null;
      if (n === 1) return (time - t[0]) / stepLast;
      if (time <= t[0]) return (time - t[0]) / stepFirst;
      if (time >= t[n - 1]) return n - 1 + (time - t[n - 1]) / stepLast;
      let lo = 0, hi = n - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (t[mid] <= time) lo = mid; else hi = mid;
      }
      const span = t[hi] - t[lo];
      return lo + (span > 0 ? (time - t[lo]) / span : 0);
    }
    function logicalToTime(logical) {
      if (!n || logical == null || !isFinite(logical)) return null;
      if (logical <= 0) return Math.round(t[0] + logical * stepFirst);
      if (logical >= n - 1) return Math.round(t[n - 1] + (logical - (n - 1)) * stepLast);
      const i = Math.floor(logical);
      return Math.round(t[i] + (logical - i) * (t[i + 1] - t[i]));
    }
    function nearestIndex(logical) {
      if (!n || logical == null) return null;
      return Math.max(0, Math.min(n - 1, Math.round(logical)));
    }
    return { timeToLogical, logicalToTime, nearestIndex, size: n, stepLast };
  }

  // The measure tool reads the candles under the pointer: among the highs
  // and lows of the nearby bars it takes the one closest to the pointer (in
  // pixels), within maxPx. That is the point a trader means when measuring a
  // swing, even when the click lands a few pixels off the wick.
  function pickExtreme(candles, pointerY, priceToY, maxPx) {
    let best = null;
    (candles || []).forEach((c) => {
      [["high", c.high], ["low", c.low]].forEach(([side, price]) => {
        const y = priceToY(price);
        if (y == null) return;
        const d = Math.abs(y - pointerY);
        if (d <= (maxPx == null ? 40 : maxPx) && (!best || d < best.d)) best = { time: c.time, price, side, d };
      });
    });
    return best ? { time: best.time, price: best.price, side: best.side } : null;
  }

  // ---- geometry -------------------------------------------------------
  function distanceToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    let k = lenSq === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / lenSq;
    k = Math.max(0, Math.min(1, k));
    return Math.hypot(px - (x1 + k * dx), py - (y1 + k * dy));
  }

  function extendLine(x1, y1, x2, y2, w, h) {
    if (x1 === x2) return { x1, y1: 0, x2: x1, y2: h };
    const slope = (y2 - y1) / (x2 - x1);
    return { x1: 0, y1: y1 - slope * x1, x2: w, y2: y1 + slope * (w - x1) };
  }

  function pointInPolygon(px, py, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[i], b = poly[j];
      if ((a.y > py) !== (b.y > py) && px < ((b.x - a.x) * (py - a.y)) / (b.y - a.y || 1e-9) + a.x) inside = !inside;
    }
    return inside;
  }

  // Price of the line p1-p2 at `time`, straight in time.
  function priceOnLine(p1, p2, time) {
    if (p2.time === p1.time) return p1.price;
    return p1.price + ((p2.price - p1.price) * (time - p1.time)) / (p2.time - p1.time);
  }

  // How far, in price, the parallel line of a channel sits from the main
  // one. Version 2 channels pass through their third point; older ones
  // (no `v`) kept the third point's price minus the first's, which is how
  // they were drawn before, so they do not move.
  function channelOffset(d) {
    const [p1, p2, p3] = d.points;
    if (!p3) return 0;
    return d.v >= 2 ? p3.price - priceOnLine(p1, p2, p3.time) : p3.price - p1.price;
  }

  function fibLevels(d) {
    return d.extensions === false ? FIB_LEVELS : FIB_LEVELS.concat(FIB_EXTENSIONS);
  }

  // ---- hit test -------------------------------------------------------
  // P = the drawing's points in pixels ({x, y}), env = {w, h, priceToY,
  // textWidth}. Returns true when (px, py) is on the shape.
  function hitTest(d, P, px, py, env, tol) {
    tol = tol == null ? 6 : tol;
    const a = P[0], b = P[1];
    if (!a) return false;
    switch (d.type) {
      case "hline": return Math.abs(py - a.y) <= tol;
      case "hray": return px >= a.x - tol && Math.abs(py - a.y) <= tol;
      case "text": {
        const tw = env && env.textWidth ? env.textWidth(d.text || "Text") : 60;
        return px >= a.x - tol && px <= a.x + 8 + tw + tol && py >= a.y - 18 - tol && py <= a.y + 6 + tol;
      }
    }
    if (!b) return false;
    switch (d.type) {
      case "trend_line":
      case "arrow":
        return distanceToSegment(px, py, a.x, a.y, b.x, b.y) <= tol;
      case "extended_line": {
        const e = extendLine(a.x, a.y, b.x, b.y, env.w, env.h);
        return distanceToSegment(px, py, e.x1, e.y1, e.x2, e.y2) <= tol;
      }
      case "range":
        return distanceToSegment(px, py, a.x, a.y, b.x, b.y) <= tol
          || Math.hypot(px - a.x, py - a.y) <= tol + 4 || Math.hypot(px - b.x, py - b.y) <= tol + 4
          || (Math.abs(py - a.y) <= tol && px >= Math.min(a.x, b.x) && px <= Math.max(a.x, b.x))
          || (Math.abs(py - b.y) <= tol && px >= Math.min(a.x, b.x) && px <= Math.max(a.x, b.x));
      case "rectangle":
      case "fractal": {
        const xa = Math.min(a.x, b.x) - tol, xb = Math.max(a.x, b.x) + tol;
        if (d.type === "fractal") return px >= xa && px <= xb;
        const ya = Math.min(a.y, b.y) - tol, yb = Math.max(a.y, b.y) + tol;
        return px >= xa && px <= xb && py >= ya && py <= yb;
      }
      case "ellipse": {
        const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
        const rx = Math.max(Math.abs(b.x - a.x) / 2, 1), ry = Math.max(Math.abs(b.y - a.y) / 2, 1);
        const r = Math.hypot((px - cx) / rx, (py - cy) / ry);
        return r <= 1 + tol / Math.min(rx, ry);
      }
      case "fib": {
        const xa = Math.min(a.x, b.x) - tol, xb = Math.max(a.x, b.x) + tol;
        if (px < xa || px > xb) return false;
        const p1 = d.points[0], p2 = d.points[1];
        return fibLevels(d).some((ratio) => {
          const y = env.priceToY(p1.price + ratio * (p2.price - p1.price));
          return y != null && Math.abs(py - y) <= tol;
        });
      }
      case "channel": {
        const off = P.offsetY;
        if (distanceToSegment(px, py, a.x, a.y, b.x, b.y) <= tol) return true;
        if (off == null) return false;
        if (distanceToSegment(px, py, a.x, a.y + off.a, b.x, b.y + off.b) <= tol) return true;
        return pointInPolygon(px, py, [a, b, { x: b.x, y: b.y + off.b }, { x: a.x, y: a.y + off.a }]);
      }
    }
    return false;
  }

  // ---- painting -------------------------------------------------------
  function rgba(hex, alpha) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return hex;
    const v = parseInt(m[1], 16);
    return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${alpha})`;
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // Label in a pill: text on a translucent panel colour, readable on any
  // candle behind it. `align` is where (x, y) sits on the pill.
  function pill(ctx, text, x, y, look, opts) {
    opts = opts || {};
    ctx.save();
    ctx.font = opts.font || "600 11px -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif";
    const w = Math.ceil(ctx.measureText(text).width) + 12, h = 18;
    let left = x, top = y - h / 2;
    if (opts.align === "right") left = x - w;
    else if (opts.align === "center") left = x - w / 2;
    if (opts.fit) {
      left = Math.max(2, Math.min(left, opts.fit.w - w - 2));
      top = Math.max(2, Math.min(top, opts.fit.h - h - 2));
    }
    ctx.shadowColor = "rgba(0,0,0,0.18)";
    ctx.shadowBlur = 6;
    ctx.shadowOffsetY = 1;
    roundRect(ctx, left, top, w, h, 9);
    ctx.fillStyle = opts.bg || look.panel;
    ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.fillStyle = opts.fg || look.ink;
    ctx.textBaseline = "middle";
    ctx.fillText(text, left + 6, top + h / 2 + 0.5);
    ctx.restore();
    return { left, top, w, h };
  }

  function handle(ctx, x, y, color, active) {
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.28)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;
    ctx.beginPath();
    ctx.arc(x, y, active ? 6.5 : 5.5, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.lineWidth = 2;
    ctx.strokeStyle = color;
    ctx.stroke();
    ctx.restore();
  }

  function styleOf(d, look) {
    const color = d.color || look.defaultColor || PALETTE[0];
    const width = WIDTHS.includes(d.width) ? d.width : 2;
    const dash = DASHES[d.dash] || DASHES.solid;
    return { color, width, dash };
  }

  // The measure: no box. The two points it read, a line between them with
  // the direction, each price projected to the price scale, and the move
  // projected once more from the second point (the 1:1 "measured move"
  // target), faint. The label rides the line.
  function paintMeasure(ctx, d, a, b, env, look, st, fit) {
    const p1 = d.points[0], p2 = d.points[1];
    const up = p2.price >= p1.price;
    const tone = up ? look.bull : look.bear;
    const lw = st.selected ? 2 : 1.5;
    ctx.save();
    // projections of both prices to the price scale
    ctx.setLineDash([3, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = rgba(tone, 0.55);
    [a, b].forEach((p) => { ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(env.w, p.y); ctx.stroke(); });
    // 1:1 projection of the move, from the second point onward
    const target = p2.price + (p2.price - p1.price);
    const ty = env.priceToY ? env.priceToY(target) : null;
    if (ty != null && !st.ghost) {
      const tx = b.x + (b.x - a.x);
      ctx.strokeStyle = rgba(tone, 0.35);
      ctx.beginPath(); ctx.moveTo(b.x, b.y); ctx.lineTo(tx, ty); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(env.w, ty); ctx.stroke();
      ctx.setLineDash([]);
      pill(ctx, `1:1  ${env.formatPrice ? env.formatPrice(target) : target.toFixed(2)}`, Math.min(env.w - 4, tx + 6), ty, look,
        { fit, fg: tone, font: "600 10px -apple-system, system-ui, sans-serif" });
    }
    ctx.setLineDash([]);
    // the measured line, with its arrow
    if (st.selected || st.hover) {
      ctx.strokeStyle = rgba(tone, 0.25); ctx.lineWidth = lw + 6;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.strokeStyle = tone; ctx.lineWidth = lw;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    const ang = Math.atan2(b.y - a.y, b.x - a.x), sz = 9;
    ctx.fillStyle = tone;
    ctx.beginPath();
    ctx.moveTo(b.x, b.y);
    ctx.lineTo(b.x - sz * Math.cos(ang - Math.PI / 7), b.y - sz * Math.sin(ang - Math.PI / 7));
    ctx.lineTo(b.x - sz * Math.cos(ang + Math.PI / 7), b.y - sz * Math.sin(ang + Math.PI / 7));
    ctx.closePath(); ctx.fill();
    // the two points it read
    [a, b].forEach((p) => {
      ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff"; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = tone; ctx.stroke();
    });
    ctx.restore();
    // prices of both points on the price scale, always (not only when selected)
    {
      [[a, p1.price], [b, p2.price]].forEach(([p, price]) => {
        pill(ctx, env.formatPrice ? env.formatPrice(price) : price.toFixed(2), env.w - 2, p.y, look,
          { align: "right", bg: rgba(tone, 0.92), fg: "#ffffff", fit, font: "600 10px -apple-system, system-ui, sans-serif" });
      });
    }
    if (d.text) {
      // beside the end it measured to, on the side the move went: never on the line
      pill(ctx, d.text, b.x, b.y + (up ? -20 : 20), look, { align: "center", fit, bg: rgba(tone, 0.94), fg: "#ffffff" });
    }
  }

  // Paints one drawing. P = points in pixels (P.offsetY for channels),
  // env = {w, h, priceToY, formatPrice, look, state: {selected, hover,
  // ghost, appear (0..1)}}.
  function paint(ctx, d, P, env) {
    const look = env.look;
    const st = env.state || {};
    const s = styleOf(d, look);
    const a = P[0], b = P[1];
    if (!a) return;
    ctx.save();
    ctx.globalAlpha = (st.ghost ? 0.6 : 1) * (st.appear == null ? 1 : st.appear);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const stroke = (fn) => {
      if (st.selected || st.hover) {
        // a soft halo under the line: selected or under the pointer
        ctx.save();
        ctx.strokeStyle = rgba(s.color, st.selected ? 0.28 : 0.16);
        ctx.lineWidth = s.width + (st.selected ? 7 : 5);
        ctx.setLineDash([]);
        fn();
        ctx.stroke();
        ctx.restore();
      }
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width;
      ctx.setLineDash(s.dash);
      fn();
      ctx.stroke();
    };
    const line = (x1, y1, x2, y2) => () => { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); };
    const fillShape = (fn, alpha) => { ctx.save(); ctx.fillStyle = rgba(s.color, alpha); ctx.setLineDash([]); fn(); ctx.fill(); ctx.restore(); };
    const fit = { w: env.w, h: env.h };

    switch (d.type) {
      case "hline":
        stroke(line(0, a.y, env.w, a.y));
        if (d.text) pill(ctx, d.text, 8, a.y - 14, look, { fit, fg: s.color });
        break;
      case "hray":
        stroke(line(a.x, a.y, env.w, a.y));
        if (d.text) pill(ctx, d.text, a.x + 6, a.y - 14, look, { fit, fg: s.color });
        break;
      case "text": {
        ctx.save();
        ctx.font = `600 ${d.size || 13}px -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif`;
        ctx.fillStyle = s.color;
        ctx.textBaseline = "alphabetic";
        ctx.fillText(d.text || "Text", a.x + 8, a.y);
        ctx.restore();
        ctx.beginPath(); ctx.arc(a.x, a.y, 3, 0, Math.PI * 2); ctx.fillStyle = s.color; ctx.fill();
        break;
      }
      case "fractal":
        if (!b) break;
        ctx.save(); ctx.setLineDash([5, 3]); ctx.strokeStyle = s.color; ctx.lineWidth = 1.5;
        [a.x, b.x].forEach((x) => { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, env.h); ctx.stroke(); });
        ctx.restore();
        break;
    }
    if (b) {
      switch (d.type) {
        case "trend_line":
          stroke(line(a.x, a.y, b.x, b.y));
          break;
        case "arrow": {
          stroke(line(a.x, a.y, b.x, b.y));
          const ang = Math.atan2(b.y - a.y, b.x - a.x), sz = 8 + 3 * s.width;
          ctx.save();
          ctx.setLineDash([]);
          ctx.fillStyle = s.color;
          ctx.beginPath();
          ctx.moveTo(b.x, b.y);
          ctx.lineTo(b.x - sz * Math.cos(ang - Math.PI / 7), b.y - sz * Math.sin(ang - Math.PI / 7));
          ctx.lineTo(b.x - sz * Math.cos(ang + Math.PI / 7), b.y - sz * Math.sin(ang + Math.PI / 7));
          ctx.closePath();
          ctx.fill();
          ctx.restore();
          break;
        }
        case "extended_line": {
          const e = extendLine(a.x, a.y, b.x, b.y, env.w, env.h);
          stroke(line(e.x1, e.y1, e.x2, e.y2));
          break;
        }
        case "rectangle": {
          const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
          fillShape(() => { ctx.beginPath(); ctx.rect(x, y, w, h); }, 0.12);
          stroke(() => { ctx.beginPath(); ctx.rect(x, y, w, h); });
          break;
        }
        case "range":
          paintMeasure(ctx, d, a, b, env, look, st, fit);
          break;
        case "ellipse": {
          const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
          const rx = Math.max(Math.abs(b.x - a.x) / 2, 1), ry = Math.max(Math.abs(b.y - a.y) / 2, 1);
          const shape = () => { ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); };
          fillShape(shape, 0.10);
          stroke(shape);
          break;
        }
        case "fib": {
          const p1 = d.points[0], p2 = d.points[1];
          const xl = Math.min(a.x, b.x), xr = Math.max(a.x, b.x);
          const levels = fibLevels(d);
          let prevY = null;
          levels.forEach((ratio, i) => {
            const price = p1.price + ratio * (p2.price - p1.price);
            const y = env.priceToY(price);
            if (y == null) return;
            if (prevY != null && i <= FIB_LEVELS.length - 1) {
              fillShape(() => { ctx.beginPath(); ctx.rect(xl, Math.min(prevY, y), xr - xl, Math.abs(y - prevY)); }, ratio === 0.618 ? 0.10 : 0.05);
            }
            prevY = y;
            ctx.save();
            ctx.globalAlpha *= ratio > 1 ? 0.6 : 1;
            ctx.strokeStyle = s.color;
            ctx.lineWidth = ratio === 0.618 ? s.width + 0.5 : Math.max(1, s.width - 0.5);
            ctx.setLineDash(ratio === 0 || ratio === 1 ? [] : [4, 3]);
            ctx.beginPath(); ctx.moveTo(xl, y); ctx.lineTo(xr, y); ctx.stroke();
            ctx.restore();
            const label = `${ratio.toFixed(3)}  ${env.formatPrice ? env.formatPrice(price) : price.toFixed(2)}`;
            pill(ctx, label, xr + 6, y, look, { fit, fg: s.color, font: "600 10px -apple-system, system-ui, sans-serif" });
          });
          break;
        }
        case "channel": {
          stroke(line(a.x, a.y, b.x, b.y));
          const off = P.offsetY;
          if (off) {
            const c1 = { x: a.x, y: a.y + off.a }, c2 = { x: b.x, y: b.y + off.b };
            fillShape(() => { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.lineTo(c2.x, c2.y); ctx.lineTo(c1.x, c1.y); ctx.closePath(); }, 0.08);
            stroke(line(c1.x, c1.y, c2.x, c2.y));
            // the middle line, as on the reference platforms
            ctx.save(); ctx.globalAlpha *= 0.5; ctx.setLineDash([4, 4]); ctx.strokeStyle = s.color; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y + off.a / 2); ctx.lineTo(b.x, b.y + off.b / 2); ctx.stroke();
            ctx.restore();
          }
          break;
        }
      }
    }
    ctx.restore();
    if (st.selected && !st.ghost && !d.locked) {
      const pts = d.type === "hline" ? [] : P.slice(0, POINTS[d.type] || P.length);
      pts.forEach((p, i) => handle(ctx, p.x, p.y, s.color, st.activeHandle === i));
    }
  }

  function formatRange(p1, p2, bars, formatPrice) {
    const dPrice = p2.price - p1.price;
    const pct = p1.price !== 0 ? (dPrice / p1.price) * 100 : 0;
    const dSeconds = Math.abs(p2.time - p1.time);
    const dDays = dSeconds / 86400;
    const span = dDays >= 1 ? `${dDays.toFixed(1)}d` : dSeconds >= 3600 ? `${(dSeconds / 3600).toFixed(1)}h` : `${Math.round(dSeconds / 60)}m`;
    const sign = dPrice >= 0 ? "+" : "";
    const priceText = formatPrice ? formatPrice(Math.abs(dPrice)) : Math.abs(dPrice).toFixed(2);
    const barsText = bars != null ? ` · ${Math.abs(Math.round(bars))} bars` : "";
    return `${sign}${dPrice < 0 ? "-" : ""}${priceText} (${sign}${pct.toFixed(2)}%) · ${span}${barsText}`;
  }

  const api = {
    PALETTE, WIDTHS, DASHES, FIB_LEVELS, FIB_EXTENSIONS, POINTS,
    makeTimeMapper, distanceToSegment, extendLine, pointInPolygon, priceOnLine,
    channelOffset, fibLevels, hitTest, paint, pill, handle, rgba, formatRange, pickExtreme,
  };
  root.DrawEngine = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
