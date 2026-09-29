/**
 * The leaderboard podium, in the site's own style. Lorenzo, 28/09: "il podio
 * mi fa schifo, cartoonesco, rifallo in stile cyberpunk come il logo del
 * nostro sito" (and "qui è tutto grosso, fin troppo"). The logo is a dark
 * isometric cube cut by a glowing mint slit: each step of the podium is that
 * cube, taller for #1, with its slit lit in the rank's colour. Mono type,
 * chamfered frames, a faint grid behind. No spotlight, confetti or metal.
 *
 * Motion (the ENGN motion kit's "engine boot", PR #383): each cube starts as
 * 27 loose modules that fly together 3-2-1, the solid cube takes their place,
 * the slits draw themselves (the splash's stroke-dashoffset trick), then only
 * the slits' glow breathes. Everything else is transform and opacity; nothing
 * runs in JS per frame. A still podium (same three as the last paint) or
 * reduced motion gets the solid cube only, no modules.
 *
 * renderPodium(container, items, {still}) with items [{id, symbol, value,
 * logoHtml}] in rank order 1..3. Each place is a button with data-open=id:
 * the token page (detail.js) opens on tap.
 */

// Body height of each cube (viewBox units, width 100): #1 stands tallest.
const BODY = { 1: 64, 2: 44, 3: 30 };

const TROPHY = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4M12 14v4M8.5 20h7"/></svg>`;

function h(tag, cls, attrs) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

const f = (n) => Math.round(n * 100) / 100;

/** The cube cut in 3x3x3 modules, each pushed out from the centre (--dx/--dy)
 * so the CSS can fly it home. Painted back to front: lower layers first,
 * then from the far corner to the near one. */
function modules(b) {
  const u = [49 / 3, 17 / 3], v = [49 / 3, -17 / 3], h = b / 3;
  const cells = [];
  for (let k = 2; k >= 0; k--)
    for (let i = 0; i < 3; i++)
      for (let j = 0; j < 3; j++) cells.push([i, j, k]);
  cells.sort((a, c) => (c[2] - a[2]) || ((a[0] - a[1]) - (c[0] - c[1])));
  return cells.map(([i, j, k]) => {
    const x = 1 + i * u[0] + j * v[0], y = 18 + i * u[1] + j * v[1] + k * h;
    const p = (dx, dy) => `${f(x + dx)} ${f(y + dy)}`;
    const dx = f(((i - 1) + (j - 1)) * 13), dy = f(((i - 1) - (j - 1)) * 5 + (k - 1) * (h + 8) - 10);
    return `<g class="pc-mod" style="--dx:${dx}px;--dy:${dy}px;--i:${(i + 2 - j + 2 - k) * 0.02}s">`
      + `<path class="pc-top" d="M${p(0, 0)} L${p(u[0], u[1])} L${p(u[0] + v[0], u[1] + v[1])} L${p(v[0], v[1])} Z"/>`
      + `<path class="pc-left" d="M${p(0, 0)} L${p(u[0], u[1])} L${p(u[0], u[1] + h)} L${p(0, h)} Z"/>`
      + `<path class="pc-right" d="M${p(u[0], u[1])} L${p(u[0] + v[0], u[1] + v[1])} L${p(u[0] + v[0], u[1] + v[1] + h)} L${p(u[0], u[1] + h)} Z"/>`
      + `</g>`;
  }).join("");
}

/** The logo's cube: top face, two side faces, the slit and its glow. */
function cube(rank, assemble) {
  const b = BODY[rank];
  const s = Math.round(b * 0.42);
  const H = 36 + b + 1;
  const slit = `M1 ${18 + s} L50 ${36 + s} L99 ${18 + s}`;
  return `<svg class="pc-cube" viewBox="0 0 100 ${H}" preserveAspectRatio="xMidYMax meet" aria-hidden="true">
    ${assemble ? `<g class="pc-mods">${modules(b)}</g>` : ""}
    <g class="pc-solid">
    <path class="pc-top" d="M50 1 L99 18 L50 35 L1 18 Z"/>
    <path class="pc-left" d="M1 18 L50 35 L50 ${35 + b} L1 ${18 + b} Z"/>
    <path class="pc-right" d="M50 35 L99 18 L99 ${18 + b} L50 ${35 + b} Z"/>
    <path class="pc-edge" d="M50 35 L50 ${35 + b}"/>
    </g>
    <path class="pc-glow" d="${slit}" pathLength="1"/>
    <path class="pc-slit" d="${slit}" pathLength="1"/>
    <text class="pc-rank" x="25" y="${27 + s + 14}" text-anchor="middle">0${rank}</text>
  </svg>`;
}

export function renderPodium(container, items, { still = false } = {}) {
  const quiet = still || matchMedia("(prefers-reduced-motion: reduce)").matches;
  const root = h("div", "pod-cy" + (quiet ? " is-still" : ""));
  const list = h("ol", "pc-list", { "aria-label": "Top 3" });
  items.slice(0, 3).forEach((it, i) => {
    const rank = i + 1;
    const li = h("li", `pc-slot pc-r${rank}`);
    const btn = h("button", "pc-place", { type: "button", "data-open": it.id, "aria-label": `Number ${rank}: ${it.symbol} ${it.value}` });
    const head = h("div", "pc-head", { "aria-hidden": "true" });
    if (rank === 1) {
      const t = h("span", "pc-trophy");
      t.innerHTML = TROPHY;
      head.append(t);
    }
    const frame = h("div", "pc-frame");
    frame.innerHTML = it.logoHtml;        // the token's real logo (format.tile)
    const sym = h("span", "pc-sym");
    sym.textContent = it.symbol;
    const val = h("span", "pc-val");
    val.textContent = it.value;
    if (/^[-−]/.test(String(it.value).trim())) val.dataset.sign = "down";
    head.append(frame, sym, val);
    const base = h("div", "pc-base", { "aria-hidden": "true" });
    base.innerHTML = cube(rank, !quiet);
    // The loose modules are spent once the solid cube shows: drop them.
    base.querySelector(".pc-mods")?.addEventListener("animationend", (e) => {
      if (e.target === e.currentTarget) e.currentTarget.remove();
    });
    btn.append(head, base);
    li.append(btn);
    list.append(li);
  });
  root.append(list);
  container.replaceChildren(root);
}
