/**
 * The Scout's mark: the ENGN cube in miniature, opening and closing on its
 * core (Lorenzo, 30/09: "il logo dello scout deve essere lo stesso cubo del
 * nostro engine in miniatura che si anima aprendosi e chiudendosi"). The
 * faces come from the solid cube in motion.js; scout-cube.css moves them with
 * transform and opacity only. The container keeps its data-state (idle,
 * working, off), so the cube breathes, works with a ring, or sits still.
 * The top bar in onchain-app.html carries the same markup inline.
 */
export const scoutCube = `<svg class="sc-svg" viewBox="-30 -23 200 200" aria-hidden="true" focusable="false">`
  + `<circle class="sc-ring" cx="70" cy="77" r="94" pathLength="100"/>`
  + `<circle class="sc-core" cx="70" cy="64" r="17"/>`
  + `<g class="sc-left"><path class="sc-face" d="M0 38 70 76 70 153 0 115Z"/><path class="sc-band" d="M3 81 70 117"/></g>`
  + `<g class="sc-right"><path class="sc-face" d="M70 76 140 38 140 115 70 153Z"/><path class="sc-band" d="M70 117 137 81"/></g>`
  + `<g class="sc-top"><path class="sc-face" d="M70 0 140 38 70 76 0 38Z"/></g>`
  + `</svg>`;
