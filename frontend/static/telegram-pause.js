/* Pause Telegram notifications per group (Alert tab). Server: notify/pause.py,
 * routes/telegram_pause.py. Text is English and goes through i18n.js. */
(function () {
  "use strict";
  const box = document.getElementById("tg-pause");
  const list = document.getElementById("tg-pause-list");
  if (!box || !list) return;
  const REFRESH_MS = 60_000;
  const DURATIONS = [["60", "1 hour"], ["480", "8 hours"], ["1440", "24 hours"], ["", "Until I resume"]];

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clock = (t) => {
    const d = new Date(t * 1000);
    const sameDay = d.toDateString() === new Date().toDateString();
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return sameDay ? hm : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${hm}`;
  };

  async function api(path, body) {
    const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
    return data;
  }

  function render(groups) {
    box.classList.toggle("hidden", !groups.length);
    list.innerHTML = groups.map((g) => `
      <li class="tg-pause-row ${g.paused ? "is-paused" : ""}" data-kind="${esc(g.kind)}">
        <span class="tg-pause-dot" aria-hidden="true"></span>
        <span class="tg-pause-name"><b>${esc(g.label)}</b><small>${esc(g.what)}</small></span>
        <span class="tg-pause-state">${g.paused
          ? `<span>${g.until ? `Paused until ${esc(clock(g.until))}` : "Paused until you resume"}</span>${g.skipped ? ` <small>${g.skipped} skipped</small>` : ""}`
          : "<span>Notifications on</span>"}</span>
        <span class="tg-pause-actions">${g.paused
          ? `<button type="button" data-act="resume">Resume</button>`
          : `<select aria-label="How long">${DURATIONS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
             <button type="button" data-act="pause">Pause</button>`}</span>
      </li>`).join("");
  }

  async function load() {
    try { render(await api("/api/telegram/groups")); }
    catch { box.classList.add("hidden"); }          // logged out, or no chat saved
  }

  list.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const row = btn.closest("li");
    const kind = row.dataset.kind;
    btn.disabled = true;
    try {
      if (btn.dataset.act === "pause") {
        const v = row.querySelector("select").value;
        await api("/api/telegram/pause", { kind, minutes: v ? Number(v) : null });
      } else {
        await api("/api/telegram/resume", { kind });
      }
      await load();
    } catch (e) {
      btn.disabled = false;
      alert(e.message);
    }
  });

  // The groups change when the chat ids are saved.
  document.getElementById("telegram-chat-id-save")?.addEventListener("click", () => setTimeout(load, 1500));
  // Also picks the section up after a login without a page reload.
  const signedIn = document.getElementById("alert-authenticated");
  const isSignedIn = () => signedIn && !signedIn.classList.contains("hidden");
  setInterval(() => { if (document.visibilityState === "visible" && isSignedIn()) load(); }, REFRESH_MS);
  // Asked only once someone is logged in: before, every anonymous visit
  // collected a 401 here. The section appears as soon as login unhides it.
  let wasSignedIn = isSignedIn();
  if (signedIn) {
    new MutationObserver(() => {
      const now = isSignedIn();
      if (now && !wasSignedIn) load();
      wasSignedIn = now;
    }).observe(signedIn, { attributes: true, attributeFilter: ["class"] });
  }
  if (wasSignedIn) load();
})();
