import * as api from "@onchain/api.js";

// This panel renders stored evidence only. Refreshing never launches research.
export function mountQuantPanel(root) {
  root.className = "quant-panel";
  root.innerHTML = `<header><h3>Quantitative engine</h3><span>Local computation · no AI calls</span></header>
    <p data-q-status role="status">Loading evidence…</p><div data-q-counts class="quant-counts"></div>
    <p data-q-policy></p><label>Follow a project <select data-q-project><option value="">Select a project</option></select></label>
    <p data-q-coverage>Most recent 100 observed projects. These are observations, not recommendations.</p>
    <div data-q-detail></div><h4>Stored research reports</h4><div data-q-reports></div>`;
  let alive = true, busy = false, received = 0, generation = 0, selection = "";
  const $ = (s) => root.querySelector(s);
  const when = (t) => t == null ? "unavailable" : new Date(t * 1000).toLocaleString();
  function line(parent, text) { const p = document.createElement("p"); p.textContent = text; parent.append(p); }
  async function project() {
    const id = ++generation;
    selection = $("[data-q-project]").value;
    const box = $("[data-q-detail]"); box.replaceChildren();
    if (!selection) return;
    const [chain, token] = JSON.parse(selection);
    line(box, "Loading recorded evidence…");
    try {
      const data = await api.getQuantProject(chain, token);
      if (!alive || id !== generation) return;
      box.replaceChildren();
      line(box, `${data.chain} · ${data.token}`);
      line(box, `${data.candles} closed candles · ${data.status}`);
      line(box, `Signal: ${data.signal.state ?? "unavailable"} · evaluated ${when(data.signal.evaluated_at)}`);
      for (const w of data.windows) {
        line(box, `${w.horizon / 86400} days: ${w.complete ? "collection complete; validation still required" : "collecting"} · through ${when(w.end)}`);
      }
      const details = document.createElement("details"), summary = document.createElement("summary"), pre = document.createElement("pre");
      summary.textContent = "Evidence at first observation"; pre.textContent = JSON.stringify(data.windows[0]?.features ?? {}, null, 2);
      details.append(summary, pre); box.append(details);
    } catch {
      if (alive && id === generation) { box.replaceChildren(); line(box, "Project evidence unavailable. Select again to retry."); }
    }
  }
  $("[data-q-project]").addEventListener("change", project);
  async function refresh() {
    if (!alive || busy) return;
    busy = true;
    try {
      const data = await api.getQuant();
      if (!alive) return;
      received = Date.now();
      $("[data-q-status]").textContent = `Evidence received ${new Date(received).toLocaleTimeString()}`;
      const counts = $("[data-q-counts]"); counts.replaceChildren();
      for (const text of [`${data.incident_projects} outcome projects`, `${data.incident_versions} outcome versions`, `${data.candles} closed candles`]) line(counts, text);
      for (const days of [1, 7, 30]) {
        const w = data.windows[String(days * 86400)] ?? { windows: 0, complete: 0 };
        line(counts, `${days} days: ${w.complete}/${w.windows} windows complete`);
      }
      const a = data.approval;
      $("[data-q-policy]").textContent = a
        ? `${a.mode === "paper" ? "Paper only" : "Reviewed for real entries"} · ${a.strategy} · effective ${when(a.active_from)}. Wallet settings and entry checks still apply.`
        : "New entries blocked: no valid reviewed policy. Evidence collection continues.";
      const select = $("[data-q-project]"); select.replaceChildren(new Option("Select a project", ""));
      for (const p of data.projects) select.add(new Option(`${p.symbol || p.token} · ${p.chain}`, JSON.stringify([p.chain, p.token])));
      select.value = selection;
      if (selection && select.value === selection) project();
      const reports = $("[data-q-reports]"); reports.replaceChildren();
      if (!data.reports.length) line(reports, "No research reports stored. No performance has been established.");
      for (const report of data.reports) {
        const details = document.createElement("details"), summary = document.createElement("summary"), pre = document.createElement("pre");
        summary.textContent = `${when(report.at)} · ${report.status} · ${report.id.slice(0, 12)}`;
        details.append(summary, pre); reports.append(details);
        let loaded = false;
        details.addEventListener("toggle", async () => {
          if (!details.open || loaded) return;
          loaded = true; pre.textContent = "Loading report…";
          try { const value = await api.getQuantReport(report.id); if (alive) pre.textContent = JSON.stringify(value, null, 2); }
          catch { loaded = false; if (alive) pre.textContent = "Report unavailable. Close and reopen to retry."; }
        });
      }
    } catch {
      if (alive) $("[data-q-status]").textContent = received
        ? `Updates interrupted. Showing evidence received ${new Date(received).toLocaleTimeString()}.`
        : "Quantitative evidence unavailable. Retrying automatically.";
    } finally { busy = false; }
  }
  return { refresh, dispose() { alive = false; generation++; } };
}
