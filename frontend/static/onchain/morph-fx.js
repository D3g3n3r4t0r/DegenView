/**
 * Morph the Why tab when a deep re-check replaces the old conclusions:
 * the gone points get struck through and dissolve into particles, the new
 * ones assemble from particles. Only transform and opacity move on DOM
 * nodes; particles live on one canvas. With prefers-reduced-motion the
 * body is simply repainted.
 */

const DPR = Math.min(2, window.devicePixelRatio || 1);
const STRIKE_MS = 260;
const DISSOLVE_MS = 640;
const ASSEMBLE_MS = 420;
const STRIKE_STAGGER = 40;
const STRIKE_MAX = 8;
const ASSEMBLE_STAGGER = 50;
const ASSEMBLE_MAX = 10;

const running = new WeakMap();

function units(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const out = [];
  tpl.content.querySelectorAll("li, p, h5").forEach((n) => {
    out.push({ text: n.textContent.trim(), node: n });
  });
  return out;
}

function diff(oldHtml, newHtml) {
  const oldUnits = units(oldHtml);
  const newUnits = units(newHtml);
  const newTexts = new Set(newUnits.map((u) => u.text));
  const oldTexts = new Set(oldUnits.map((u) => u.text));
  const gone = oldUnits.filter((u) => !newTexts.has(u.text));
  const added = newUnits.filter((u) => !oldTexts.has(u.text));
  return { gone, added };
}

function makeCanvas(host) {
  const c = document.createElement("canvas");
  c.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483000;";
  c.width = Math.round(window.innerWidth * DPR);
  c.height = Math.round(window.innerHeight * DPR);
  c.style.width = window.innerWidth + "px";
  c.style.height = window.innerHeight + "px";
  host.appendChild(c);
  return c;
}

function easeOutQuad(t) { return 1 - (1 - t) * (1 - t); }
function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

function runParticles(canvas, particles, onDone) {
  const ctx = canvas.getContext("2d");
  let last = 0;
  let raf = 0;
  function frame(ts) {
    if (!last) last = ts;
    const dt = Math.min(0.05, (ts - last) / 1000);
    last = ts;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.life -= dt * 1000;
      if (p.life <= 0) {
        particles[i] = particles[particles.length - 1];
        particles.pop();
        continue;
      }
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.vx += p.ax * dt;
      p.vy += p.ay * dt;
      const t = 1 - p.life / p.total;
      const a = p.fade === "in" ? easeOutCubic(t) : 1 - easeOutQuad(t);
      ctx.globalAlpha = Math.max(0, Math.min(1, a));
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x * DPR, p.y * DPR, p.size * DPR, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (particles.length > 0) {
      raf = requestAnimationFrame(frame);
    } else {
      cancelAnimationFrame(raf);
      onDone();
    }
  }
  raf = requestAnimationFrame(frame);
  return () => cancelAnimationFrame(raf);
}

function spawnDissolve(particles, rect, color, delayMs) {
  const count = Math.min(140, Math.round((rect.width * rect.height) / 90));
  for (let i = 0; i < count; i++) {
    const x = rect.left + Math.random() * rect.width;
    const y = rect.top + Math.random() * rect.height;
    const born = ((x - rect.left) / rect.width) * 320 + delayMs;
    const life = 450 + Math.random() * 300;
    particles.push({
      x, y,
      vx: 20 + Math.random() * 70,
      vy: -10 - Math.random() * 60,
      ax: (Math.random() - 0.5) * 40,
      ay: (Math.random() - 0.5) * 40,
      size: 1 + Math.random() * 1.2,
      color,
      life: life + born,
      total: life,
      fade: "out",
      born,
    });
  }
}

function spawnAssemble(particles, rect, color, delayMs) {
  const count = Math.min(140, Math.round((rect.width * rect.height) / 90));
  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const dist = 30 + Math.random() * 40;
    const sx = rect.left + rect.width / 2 + Math.cos(angle) * dist;
    const sy = rect.top + rect.height / 2 + Math.sin(angle) * dist;
    const tx = rect.left + Math.random() * rect.width;
    const ty = rect.top + Math.random() * rect.height;
    const life = ASSEMBLE_MS;
    particles.push({
      x: sx, y: sy,
      vx: (tx - sx) / (life / 1000),
      vy: (ty - sy) / (life / 1000),
      ax: 0, ay: 0,
      size: 1 + Math.random() * 1.2,
      color,
      life: life + delayMs,
      total: life,
      fade: "in",
      born: delayMs,
    });
  }
}

function colorOf(node) {
  const tone = node.getAttribute("data-tone");
  if (tone === "good") return "#34d399";
  if (tone === "bad") return "#f87171";
  return getComputedStyle(node).color;
}

export async function morph(body, html) {
  const prev = running.get(body);
  if (prev) {
    prev.finish();
    running.delete(body);
  }

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const oldHtml = body.innerHTML;
  const { gone, added } = diff(oldHtml, html);

  if (reduced || (gone.length === 0 && added.length === 0)) {
    body.innerHTML = html;
    return;
  }

  const host = body.closest("dialog") ?? document.body;
  const canvas = makeCanvas(host);
  const particles = [];
  let cancelled = false;
  let stopRaf = null;

  const finish = () => {
    cancelled = true;
    if (stopRaf) stopRaf();
    particles.length = 0;
    canvas.remove();
    body.innerHTML = html;
  };
  running.set(body, { finish });

  // Strike phase: mark gone nodes and let CSS draw the line.
  const goneNodes = gone.map((u) => {
    const live = [...body.querySelectorAll("li, p, h5")].find((n) => n.textContent.trim() === u.text);
    return live;
  }).filter(Boolean);

  goneNodes.forEach((node, i) => {
    node.setAttribute("data-fx", "strike");
    const delay = Math.min(i, STRIKE_MAX - 1) * STRIKE_STAGGER;
    node.style.animationDelay = delay + "ms";
  });

  await new Promise((r) => setTimeout(r, STRIKE_MS + Math.min(goneNodes.length, STRIKE_MAX) * STRIKE_STAGGER));
  if (cancelled) return;

  // Dissolve phase: particles over each gone node, node fades out.
  const rects = goneNodes.map((n) => ({ node: n, rect: n.getBoundingClientRect(), color: colorOf(n) }));
  rects.forEach(({ node, rect, color }, i) => {
    const delay = Math.min(i, STRIKE_MAX - 1) * STRIKE_STAGGER;
    spawnDissolve(particles, rect, color, delay);
    node.animate(
      [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(6px)" }],
      { duration: 320, delay, fill: "forwards", easing: "ease-out" }
    );
  });

  stopRaf = runParticles(canvas, particles, () => {});
  await new Promise((r) => setTimeout(r, DISSOLVE_MS));
  if (cancelled) return;

  // Swap the markup, then assemble the new nodes.
  body.innerHTML = html;
  const addedNodes = added.map((u) => {
    return [...body.querySelectorAll("li, p, h5")].find((n) => n.textContent.trim() === u.text);
  }).filter(Boolean);

  addedNodes.forEach((node, i) => {
    node.style.opacity = "0";
    node.style.transform = "translateY(6px)";
    const delay = Math.min(i, ASSEMBLE_MAX - 1) * ASSEMBLE_STAGGER;
    const rect = node.getBoundingClientRect();
    spawnAssemble(particles, rect, colorOf(node), delay);
    setTimeout(() => {
      if (cancelled) return;
      node.animate(
        [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }],
        { duration: 220, fill: "forwards", easing: "ease-out" }
      );
      node.style.opacity = "";
      node.style.transform = "";
    }, delay + ASSEMBLE_MS);
  });

  await new Promise((r) => setTimeout(r, ASSEMBLE_MS + Math.min(addedNodes.length, ASSEMBLE_MAX) * ASSEMBLE_STAGGER + 220));
  if (cancelled) return;

  if (stopRaf) stopRaf();
  particles.length = 0;
  canvas.remove();
  running.delete(body);
}
