/* Site languages (Lorenzo, 16/10: "una tendina che ti permette di cambiare
 * lingua [...] modalità inglese e modalità italiano con la possibilità poi di
 * aggiungere anche altre lingue successivamente").
 *
 * English is the language the site is written in and stays the default. A
 * language is a file in /static/i18n/<code>.json:
 *   { "lang": "it", "name": "Italiano",
 *     "strings":  { "<English text>": "<translation>", ... },
 *     "patterns": [ ["<regex on the English text>", "<translation with $1…>"], ... ] }
 * and one entry in LANGS below. Nothing else changes: the page and what the
 * app writes into it at runtime are translated where they are shown — text
 * nodes, title / placeholder / aria-label — so the app code keeps its
 * English strings. Text not in the dictionary stays in English. confirm()
 * and alert() messages go through the same dictionary.
 */
(function () {
  "use strict";
  const LANGS = { en: "English", it: "Italiano" };
  const KEY = "le-lang";
  let lang = "en";
  try { lang = localStorage.getItem(KEY) || "en"; } catch { /* storage blocked: English */ }
  if (!LANGS[lang]) lang = "en";
  document.documentElement.lang = lang;

  let dict = null;          // Map English -> translation
  let patterns = [];        // [RegExp, replacement]
  const ATTRS = ["title", "placeholder", "aria-label"];
  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE", "CANVAS", "SVG"]);

  function norm(s) { return s.replace(/\s+/g, " ").trim(); }

  function tr(text) {
    if (!dict || !text) return null;
    const key = norm(text);
    if (!key || key.length > 600) return null;
    const hit = dict.get(key);
    if (hit !== undefined) return hit;
    for (const [re, rep] of patterns) {
      if (re.test(key)) return key.replace(re, rep);
    }
    return null;
  }

  function skipped(node) {
    for (let el = node.nodeType === 1 ? node : node.parentElement; el; el = el.parentElement) {
      if (SKIP.has(el.tagName) || el.isContentEditable || (el.dataset && el.dataset.noI18n !== undefined)) return true;
    }
    return false;
  }

  function doText(node) {
    const v = node.nodeValue;
    if (!v || !/[A-Za-z]/.test(v) || skipped(node)) return;
    const t = tr(v);
    if (t != null && t !== norm(v)) {
      const m = v.match(/^(\s*)[\s\S]*?(\s*)$/);
      node.nodeValue = (m ? m[1] : "") + t + (m ? m[2] : "");
    }
  }

  function doAttrs(el) {
    if (skipped(el)) return;
    for (const a of ATTRS) {
      const v = el.getAttribute && el.getAttribute(a);
      if (!v) continue;
      const t = tr(v);
      if (t != null && t !== v) el.setAttribute(a, t);
    }
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) doAttrs(root);
    const it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n;
    while ((n = it.nextNode())) {
      if (n.nodeType === 3) doText(n); else doAttrs(n);
    }
  }

  function start() {
    if (document.title) { const t = tr(document.title); if (t) document.title = t; }
    walk(document.body);
    new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === "characterData") doText(m.target);
        else if (m.type === "attributes") doAttrs(m.target);
        else m.addedNodes.forEach(walk);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true,
                                attributes: true, attributeFilter: ATTRS });
  }

  // confirm() / alert() texts are not in the page
  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);
  window.confirm = (msg) => nativeConfirm(tr(String(msg ?? "")) ?? msg);
  window.alert = (msg) => nativeAlert(tr(String(msg ?? "")) ?? msg);

  // the switch in the top bar
  function mountSwitch() {
    const bar = document.querySelector("header.toolbar");
    if (!bar || document.getElementById("lang-select")) return;
    const sel = document.createElement("select");
    sel.id = "lang-select";
    sel.className = "lang-select";
    sel.title = `Language: ${LANGS[lang]}`;
    sel.setAttribute("aria-label", "Language");
    sel.dataset.noI18n = "";
    // short code in the bar, the full name in the tooltip
    for (const [code, name] of Object.entries(LANGS)) {
      const o = document.createElement("option");
      o.value = code;
      o.textContent = code.toUpperCase();
      o.title = name;
      if (code === lang) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => {
      try { localStorage.setItem(KEY, sel.value); } catch { /* not kept: this page only */ }
      location.reload();
    });
    const auth = bar.querySelector(".auth-widget");
    bar.insertBefore(sel, auth || null);
  }

  window.i18n = { lang, languages: LANGS, t: (s) => tr(s) ?? s };

  function boot() {
    mountSwitch();
    if (lang === "en") return;
    fetch(`/static/i18n/${lang}.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        dict = new Map(Object.entries(data.strings || {}));
        patterns = (data.patterns || []).map(([re, rep]) => [new RegExp(re), rep]);
        start();
      })
      .catch(() => { /* no dictionary: the site stays in English */ });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
