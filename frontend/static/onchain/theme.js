/**
 * Dark mode for the phone skin (Lorenzo, 17/10 & 24/10: "l'app va in modalità
 * dark automaticamente al calare del sole", plus manual toggle button).
 * The choice lives in this browser (localStorage "lae:theme:mode":
 * light, dark or auto, defaulting to "auto"); the inline script at the top of
 * onchain-app.html applies it before the first paint, and this module keeps it
 * in step afterwards (checking sunset/sunrise every 60s).
 */

const KEY = "lae:theme";
const MODE_KEY = "lae:theme:mode";
const SYSTEM_DARK = matchMedia("(prefers-color-scheme: dark)");
let picked = null;   // this visit's choice, when the browser keeps no storage

export const THEMES = [["light", "Light"], ["dark", "Dark"], ["auto", "Auto"]];

export function isSolarNight(now = new Date()) {
  const doy = Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86_400_000);
  const jan = new Date(now.getFullYear(), 0, 1).getTimezoneOffset();
  const jul = new Date(now.getFullYear(), 6, 1).getTimezoneOffset();
  const dst = now.getTimezoneOffset() < Math.max(jan, jul) ? 60 : 0;
  const decl = (-23.44 * Math.PI / 180) * Math.cos((2 * Math.PI / 365) * (doy + 10));
  const cosH = Math.max(-0.95, Math.min(0.95, -Math.tan(42.5 * Math.PI / 180) * Math.tan(decl)));
  const halfMin = Math.round((12 / Math.PI) * Math.acos(cosH) * 60);
  const noon = 730 + dst;
  const cur = now.getHours() * 60 + now.getMinutes();
  return cur >= noon + halfMin || cur < noon - halfMin;
}

export function themePref() {
  if (picked) return picked;
  try {
    const v = localStorage.getItem(MODE_KEY);
    return THEMES.some(([k]) => k === v) ? v : "auto";
  } catch {
    return "auto";   // private mode
  }
}

// The phone's status bar takes the page colour: --c-bg comes from
// classic.css, which only the phone skin loads; the desktop skin is dark.
const DESKTOP_BAR = "#0d0e11";
function paintBar() {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) return;
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--c-bg").trim();
  meta.content = bg || DESKTOP_BAR;
}

function syncOnchainThemeBtn() {
  const btn = document.getElementById("theme-toggle-onchain");
  if (!btn) return;
  const isDark = document.documentElement.dataset.theme === "dark";
  btn.textContent = isDark ? "☀" : "☾";
  btn.title = isDark ? "Switch to light mode" : "Switch to dark mode";
}

function apply() {
  const pref = themePref();
  const dark = pref === "dark" || (pref === "auto" && (isSolarNight() || SYSTEM_DARK.matches));
  const next = dark ? "dark" : "light";
  if (document.documentElement.dataset.theme === next) { paintBar(); syncOnchainThemeBtn(); return; }
  document.documentElement.dataset.theme = next;
  // chart-theme.js repaints the canvases, which cannot read CSS.
  window.dispatchEvent(new Event("lae:theme"));
  paintBar();
  syncOnchainThemeBtn();
}

export function setTheme(pref) {
  picked = pref;
  try { localStorage.setItem(MODE_KEY, pref); localStorage.setItem(KEY, pref); } catch { /* private mode: this visit only */ }
  apply();
}

SYSTEM_DARK.addEventListener("change", () => { if (themePref() === "auto") apply(); });
matchMedia("(min-width:1100px)").addEventListener("change", paintBar);
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("theme-toggle-onchain");
  if (btn) {
    btn.addEventListener("click", () => {
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
  }
  syncOnchainThemeBtn();
});
setInterval(() => { if (themePref() === "auto") apply(); }, 60_000);
apply();
