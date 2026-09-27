/**
 * The leaderboard podium, "Champions stage". Chosen among three prototypes
 * built by separate designers (request: "progetta la leaderboard con agenti
 * specializzati, voglio qualcosa che catturi attenzione, animata con
 * fluidita' 120fps"). Metal blocks rise 3-2-1, the logos drop in on a
 * spring, a spotlight sweeps and settles on #1, the crown lands, the value
 * counts up, confetti bursts; then a calm idle loop (breathing halo, glints
 * on the metal, twinkles).
 *
 * Performance (from the audit): every CSS animation moves only transform
 * and opacity; entrance animations use fill "backwards" so they never fight
 * the infinite ones on the same property (which would push them to the main
 * thread); confetti runs on the compositor through the Web Animations API
 * with precomputed keyframes, nothing per frame in JS; the counting number
 * has its final width reserved so nothing relayouts around it. Only the
 * count-up is JS (one short rAF loop that stops).
 *
 * renderPodium(container, items, {still}) with items [{id, symbol, value,
 * logoHtml}] in rank order 1..3. Each place is a button with data-open=id:
 * the token page (detail.js) opens on tap.
 */

const CROWN = `<svg viewBox="0 0 48 32" aria-hidden="true"><defs><linearGradient id="pa-cg" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#fef9c3"/><stop offset=".45" stop-color="#facc15"/><stop offset="1" stop-color="#c07503"/></linearGradient></defs>
  <path d="M4 10 L14 19 L24 4 L34 19 L44 10 L40 28 H8 Z" fill="url(#pa-cg)" stroke="#7c4a02" stroke-width="1.2" stroke-linejoin="round"/>
  <rect x="8" y="24" width="32" height="4" fill="#92400e" opacity=".5"/>
  <circle cx="24" cy="4" r="2.7" fill="#fef3c7"/><circle cx="4" cy="10" r="2.4" fill="#fef3c7"/><circle cx="44" cy="10" r="2.4" fill="#fef3c7"/>
  <circle cx="24" cy="20" r="2.4" fill="#f87171"/><circle cx="15.5" cy="23" r="1.7" fill="#82e28d"/><circle cx="32.5" cy="23" r="1.7" fill="#82e28d"/></svg>`;
const STAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 0C13 8 16 11 24 12C16 13 13 16 12 24C11 16 8 13 0 12C8 11 11 8 12 0Z" fill="#fef3c7"/></svg>`;
const COLORS = ["#facc15", "#fde68a", "#c07503", "#e4e4e7", "#fdba74", "#82e28d", "#ffffff"];
const COUNT_AT = 900;
const COUNT_DUR = 620;
const BURST_AT = 1250;

function parse(v) {
  const m = String(v).trim().match(/^([+\-−]?)(\d+(?:[.,]\d+)?)(.*)$/);
  if (!m) return { sign: "", num: NaN, dec: 0, unit: "", raw: String(v) };
  const n = m[2].replace(",", ".");
  return { sign: m[1], num: parseFloat(n), dec: (n.split(".")[1] || "").length, unit: m[3], raw: m[1] + m[2] };
}

function h(tag, cls, attrs) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/** Confetti on the compositor: each piece gets precomputed keyframes. */
function burst(fx, origin) {
  const G = 820;
  for (let k = 0; k < 22; k++) {
    const el = document.createElement("div");
    const round = k % 5 === 0;
    el.className = "pa-conf" + (round ? " round" : "");
    const w = round ? 6 : 4 + Math.random() * 4;
    const hh = round ? 6 : 7 + Math.random() * 6;
    el.style.width = `${w}px`;
    el.style.height = `${hh}px`;
    el.style.background = COLORS[k % COLORS.length];
    const ang = (-90 + (Math.random() * 2 - 1) * 72) * Math.PI / 180;
    const sp = 190 + Math.random() * 230;
    const vx = Math.cos(ang) * sp, vy = Math.sin(ang) * sp;
    const rot = Math.random() * 360, vr = (Math.random() < 0.5 ? -1 : 1) * (320 + Math.random() * 520);
    const flip = 6 + Math.random() * 10, life = 1300 + Math.random() * 500;
    const frames = [];
    for (let i = 0; i <= 12; i++) {
      const t = (life / 1000) * (i / 12);
      const drag = 1 - Math.min(0.55, t * 0.35);
      const x = origin.x + vx * t * drag - w / 2;
      const y = origin.y + vy * t * drag + 0.5 * G * t * t;
      const k2 = i / 12;
      frames.push({
        transform: `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) rotate(${(rot + vr * t).toFixed(1)}deg) scaleY(${Math.cos(t * flip).toFixed(3)})`,
        opacity: k2 < 0.08 ? k2 / 0.08 : k2 > 0.6 ? 1 - (k2 - 0.6) / 0.4 : 1,
      });
    }
    fx.append(el);
    el.animate(frames, { duration: life, delay: BURST_AT, easing: "linear", fill: "backwards" }).finished
      .then(() => el.remove(), () => el.remove());
  }
}

export function renderPodium(container, items, { still = false } = {}) {
  if (container._pa) cancelAnimationFrame(container._pa);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const quiet = still || reduce;

  const root = h("div", "podium-a" + (quiet ? " is-still" : ""));
  root.append(h("div", "pa-spot", { "aria-hidden": "true" }), h("div", "pa-pool", { "aria-hidden": "true" }),
    h("div", "pa-floor", { "aria-hidden": "true" }));
  const list = h("ol", "pa-list", { "aria-label": "Top 3" });
  const fx = h("div", "pa-fx", { "aria-hidden": "true" });
  root.append(list, fx);

  let countEl = null;
  let countInfo = null;
  let head1 = null;

  items.slice(0, 3).forEach((it, i) => {
    const rank = i + 1;
    const p = parse(it.value);
    const li = h("li", `pa-slot pa-r${rank}`);
    const btn = h("button", "pa-place", { type: "button", "data-open": it.id, "aria-label": `Number ${rank}: ${it.symbol} ${it.value}` });
    const head = h("div", "pa-head", { "aria-hidden": "true" });
    if (rank === 1) {
      head1 = head;
      head.append(h("div", "pa-halo"));
      const crown = h("div", "pa-crown");
      crown.innerHTML = CROWN;
      head.append(crown);
      for (const s of ["s1", "s2", "s3"]) { const sp = h("div", `pa-spark ${s}`); sp.innerHTML = STAR; head.append(sp); }
    }
    const av = h("div", "pa-avatar");
    const ring = h("div", "pa-ring");
    ring.innerHTML = it.logoHtml;        // the token's real logo (format.tile)
    av.append(ring);
    head.append(av);

    const label = h("div", "pa-label");
    const sym = h("span", "pa-sym");
    sym.textContent = it.symbol;
    const neg = p.sign === "-" || p.sign === "−";
    const val = h("span", `pa-val ${/pt/i.test(p.unit) ? "is-pts" : neg ? "is-neg" : "is-pos"}`);
    const n = h("span", "pa-n");
    n.textContent = p.raw;
    if (rank === 1) n.style.minWidth = `${p.raw.length}ch`;   // reserved: the count-up never relayouts
    const u = h("span", "pa-u");
    u.textContent = p.unit.trim();
    val.append(n, u);
    label.append(sym, val);
    head.append(label);

    const base = h("div", "pa-base", { "aria-hidden": "true" });
    const block = h("div", "pa-block");
    const front = h("div", "pa-front");
    const num = h("span", "pa-num");
    num.textContent = String(rank);
    front.append(num, h("span", "pa-glint"));
    block.append(h("div", "pa-top"), front);
    base.append(block);

    btn.append(head, base);
    li.append(btn);
    list.append(li);
    if (rank === 1 && !Number.isNaN(p.num)) { countEl = n; countInfo = p; }
  });

  container.replaceChildren(root);
  if (quiet) return;

  // One layout read, before anything else writes: where the burst starts.
  if (head1) {
    const r = root.getBoundingClientRect();
    const hr = head1.getBoundingClientRect();
    burst(fx, { x: hr.left - r.left + hr.width / 2, y: hr.top - r.top + 40 });
  }
  if (!countEl) return;
  const fmt = (x) => countInfo.sign + x.toFixed(countInfo.dec);
  countEl.textContent = fmt(0);
  const start = performance.now();
  const tick = (now) => {
    const e = now - start;
    if (e >= COUNT_AT) {
      const t = Math.min(1, (e - COUNT_AT) / COUNT_DUR);
      countEl.textContent = t < 1 ? fmt(countInfo.num * (1 - (1 - t) ** 3)) : countInfo.raw;
      if (t >= 1) { container._pa = 0; return; }
    }
    container._pa = requestAnimationFrame(tick);
  };
  container._pa = requestAnimationFrame(tick);
}
