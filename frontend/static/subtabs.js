/* Sub-tabs inside Alert and Trading (layout B, 23/10: "Applica B per
 * entrambe"). One section at a time, full width: the CSS columns used before
 * rebalanced themselves whenever a section opened, and the sections jumped
 * from one column to the other.
 *
 * Markup: a [data-subtabs] bar of buttons with data-subtab-target, and its
 * sibling panels with data-subtab. A panel that is a <details> is opened
 * when its tab is chosen and closed when another is, so what loads on
 * opening (copy trading, the on-chain wallet) still loads then; a <details>
 * opened by other code switches to its tab. In these two areas the chart
 * starts closed (cockpit.chart-mini) and a button in the bar brings it back. */
(function () {
  "use strict";
  const CHART_KEY = "lae-chart-mini";
  const CHART_AREAS = new Set(["alert", "trading"]);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  function setup(bar) {
    const name = bar.dataset.subtabs;
    const tabs = [...bar.querySelectorAll("[data-subtab-target]")];
    const panels = [...bar.parentElement.querySelectorAll(":scope > [data-subtab]")];
    let current = null;

    function select(target, remember = true) {
      if (!panels.some((p) => p.dataset.subtab === target)) target = tabs[0].dataset.subtabTarget;
      current = target;
      for (const t of tabs) {
        const on = t.dataset.subtabTarget === target;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
      }
      for (const p of panels) {
        const on = p.dataset.subtab === target;
        p.hidden = !on;
        if (p.tagName === "DETAILS" && p.open !== on) p.open = on;
      }
      if (remember) store.set(`lae-subtab-${name}`, target);
    }

    bar.addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-subtab-target]");
      if (t) select(t.dataset.subtabTarget);
    });
    bar.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const i = tabs.findIndex((t) => t.dataset.subtabTarget === current);
      const next = tabs[(i + (ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      select(next.dataset.subtabTarget);
      next.focus();
    });
    for (const p of panels) {
      if (p.tagName !== "DETAILS") continue;
      // The open panel's own header no longer closes it (it would leave the tab empty).
      p.querySelector(":scope > summary")?.addEventListener("click", (ev) => ev.preventDefault());
      // Opened by other code (e.g. "set up a key"): show its tab.
      p.addEventListener("toggle", () => { if (p.open && p.dataset.subtab !== current) select(p.dataset.subtab); });
    }
    select(store.get(`lae-subtab-${name}`) || tabs[0].dataset.subtabTarget, false);
    return { select };
  }

  // Telegram not set up yet: the Alert bar says where to go.
  function watchTelegram() {
    const chip = document.getElementById("telegram-status-chip");
    const tab = document.querySelector('[data-subtabs="alert"] [data-subtab-target="telegram"]');
    if (!chip || !tab) return;
    const paint = () => tab.classList.toggle("needs-attention", chip.classList.contains("hidden"));
    new MutationObserver(paint).observe(chip, { attributes: true, attributeFilter: ["class"] });
    paint();
  }

  function setupChart() {
    const cockpit = document.querySelector(".cockpit");
    if (!cockpit) return;
    const buttons = [...document.querySelectorAll("[data-chart-toggle]")];
    const mini = () => store.get(CHART_KEY) === "1";
    const apply = () => {
      const on = mini() && CHART_AREAS.has(cockpit.dataset.area);
      const was = cockpit.classList.contains("chart-mini");
      cockpit.classList.toggle("chart-mini", on);
      for (const b of buttons) {
        b.textContent = mini() ? "Show chart" : "Hide chart";
        b.setAttribute("aria-pressed", String(!mini()));
      }
      // The chart measures itself on resize: tell it its box changed.
      if (was !== on) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    };
    for (const b of buttons) b.addEventListener("click", () => { store.set(CHART_KEY, mini() ? "0" : "1"); apply(); });
    new MutationObserver(apply).observe(cockpit, { attributes: true, attributeFilter: ["data-area"] });
    apply();
  }

  document.querySelectorAll("[data-subtabs]").forEach(setup);
  watchTelegram();
  setupChart();
})();
