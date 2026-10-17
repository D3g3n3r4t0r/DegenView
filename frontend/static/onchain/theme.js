/**
 * Dark mode for the phone skin (Lorenzo, 17/10: "aggiungi anche modalità
 * dark"). The choice lives in this browser (localStorage "lae:theme":
 * light, dark or auto, light when unset so nothing changes until it is
 * picked); the inline script at the top of onchain-app.html applies it
 * before the first paint, this module keeps it in step afterwards. The
 * desktop skin is dark already and does not read it.
 */

const KEY = "lae:theme";
const SYSTEM_DARK = matchMedia("(prefers-color-scheme: dark)");
let picked = null;   // this visit's choice, when the browser keeps no storage

export const THEMES = [["light", "Light"], ["dark", "Dark"], ["auto", "Auto"]];

export function themePref() {
  if (picked) return picked;
  try {
    const v = localStorage.getItem(KEY);
    return THEMES.some(([k]) => k === v) ? v : "light";
  } catch {
    return "light";   // private mode
  }
}

function apply() {
  const pref = themePref();
  const dark = pref === "dark" || (pref === "auto" && SYSTEM_DARK.matches);
  const next = dark ? "dark" : "light";
  if (document.documentElement.dataset.theme === next) return;
  document.documentElement.dataset.theme = next;
  // chart-theme.js repaints the canvases, which cannot read CSS.
  window.dispatchEvent(new Event("lae:theme"));
}

export function setTheme(pref) {
  picked = pref;
  try { localStorage.setItem(KEY, pref); } catch { /* private mode: this visit only */ }
  apply();
}

SYSTEM_DARK.addEventListener("change", () => { if (themePref() === "auto") apply(); });
apply();
