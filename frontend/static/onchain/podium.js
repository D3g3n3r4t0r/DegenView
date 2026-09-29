/**
 * The leaderboard podium. Lorenzo, 29/09: follow the ENGN motion kit ChatGPT
 * made (design/engn-motion-kit/CLAUDE.md, step 1): the renderer is the kit's
 * adapter, each place an <engn-motion> cube that assembles, with the same
 * public contract as before for top.js, alerts.js and leaderboard.js:
 * renderPodium(container, items, {still}) with items [{id, symbol, value,
 * logoHtml}] in rank order 1..3, .pc-slot in DOM order 1,2,3 (the 2,1,3 look
 * is CSS order), each place a button with data-open=id.
 */
export { renderPodium } from "@onchain/podium-adapter.js";
