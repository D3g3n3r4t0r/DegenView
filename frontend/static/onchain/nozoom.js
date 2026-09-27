/**
 * The phone page never zooms or shifts when a box gets focus. Lorenzo,
 * 27/09: "quando apro l'app non risulta centrata perfettamente nel telefono,
 * non voglio mai avere questo problema neanche quando inserisco testo in
 * caselle". iOS Safari zooms onto any input, textarea or select whose text
 * is under 16px and leaves the page zoomed and shifted afterwards: on touch
 * screens every such box is raised to 16px before it takes focus, including
 * the ones views build later.
 */
const FIELD = "input:not([type=checkbox]):not([type=radio]):not([type=range]), textarea, select";

function fix(t) {
  if (t instanceof HTMLElement && t.matches(FIELD) && parseFloat(getComputedStyle(t).fontSize) < 16) {
    t.style.fontSize = "16px";
  }
}

if (matchMedia("(pointer: coarse)").matches) {
  // pointerdown comes before focus: iOS sees 16px when it decides whether to zoom.
  document.addEventListener("pointerdown", (e) => fix(e.target.closest?.(FIELD) ?? e.target), { capture: true, passive: true });
  document.addEventListener("focusin", (e) => fix(e.target), true);
}
