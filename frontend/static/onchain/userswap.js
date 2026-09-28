/**
 * Buy or sell from the user's own connected wallet (backend: user_swaps.py).
 *
 * The server prepares the transactions, the wallet signs and sends them: no
 * key ever reaches us. Robinhood Chain through MetaMask / Rabby (approve if
 * needed, then the Uniswap v3 swap; the chain is added to the wallet if it
 * doesn't know it), Solana through Phantom (a Jupiter transaction, read with
 * @solana/web3.js from unpkg, the one script host the page allows).
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";
import * as phantom from "@onchain/phantomlink.js";

const RH = {
  chainId: "0x1237", chainName: "Robinhood Chain", nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
  rpcUrls: ["https://rpc.mainnet.chain.robinhood.com"], blockExplorerUrls: ["https://robinhoodchain.blockscout.com"],
};
const USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168";
const SOL = "So11111111111111111111111111111111111111112";
const USDC_SOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
const WEB3 = "https://unpkg.com/@solana/web3.js@1.95.3/lib/index.iife.min.js";

let linked = { wallets: [], usdc_robinhood: null };
let dlg = null;
let ctx = null;          // {e, wallet, side, built}

export async function loadLinked() {
  try { linked = await api.getLinkedWallets(); } catch { /* not signed in, or no wallet */ }
  return linked;
}

/** The connected wallet that can trade this chain, if any. */
export function walletFor(chain) {
  const kind = chain === "robinhood" ? "evm" : chain === "solana" ? "solana" : null;
  return kind ? (linked.wallets ?? []).find((w) => w.kind === kind) ?? null : null;
}

const pays = (kind) => (kind === "evm"
  ? [[USDG, "USDG"], ...(linked.usdc_robinhood ? [[linked.usdc_robinhood, "USDC"]] : [])]
  : [[SOL, "SOL"], [USDC_SOL, "USDC"]]);

function sheet() {
  if (dlg) return dlg;
  dlg = document.createElement("dialog");
  dlg.className = "sheet us-sheet";
  dlg.setAttribute("aria-label", "Swap with your wallet");
  document.body.append(dlg);
  dlg.addEventListener("click", onClick);
  dlg.addEventListener("click", (event) => { if (event.target === dlg) dlg.close(); });
  return dlg;
}

function paint(state = "") {
  const { e, wallet, side, built } = ctx;
  const kind = wallet.kind;
  const out = built ? (built.out / 10 ** (built.decimals_out ?? 6)) : null;
  dlg.innerHTML = `
    <h3>${side === "buy" ? "Buy" : "Sell"} ${escapeHtml(e.symbol)} <small>with ${escapeHtml(wallet.address.slice(0, 5))}…${escapeHtml(wallet.address.slice(-4))}</small></h3>
    <nav class="us-side">${["buy", "sell"].map((s) => `<button type="button" data-side="${s}" aria-pressed="${s === side}">${s === "buy" ? "Buy" : "Sell"}</button>`).join("")}</nav>
    ${side === "buy" ? `
      <label class="us-amt">You pay<span><input type="number" inputmode="decimal" min="0" step="any" data-amount value="${escapeHtml(ctx.amount ?? "")}" placeholder="0.00" />
        <select data-pay>${pays(kind).map(([a, l]) => `<option value="${a}" ${a === ctx.pay ? "selected" : ""}>${l}</option>`).join("")}</select></span></label>`
    : `<div class="us-pct">${[25, 50, 100].map((p) => `<button type="button" data-pct="${p}" aria-pressed="${p === ctx.pct}">${p}%</button>`).join("")}</div>`}
    ${built ? `<dl class="us-quote">
        <div><dt>You get about</dt><dd>${out == null ? "—" : out.toLocaleString("en-US", { maximumFractionDigits: 6 })}</dd></div>
        <div><dt>At least</dt><dd>${(built.min_out / 10 ** (built.decimals_out ?? 6)).toLocaleString("en-US", { maximumFractionDigits: 6 })}</dd></div>
        <div><dt>Price impact</dt><dd>${built.impact == null ? "—" : `${Number(built.impact).toFixed(2)}%`}</dd></div>
        ${kind === "evm" ? `<div><dt>Wallet asks you</dt><dd>${built.txs.length === 2 ? "twice (allow, then swap)" : "once"}</dd></div>` : ""}
      </dl>` : ""}
    <p class="us-state">${state}</p>
    <div class="us-actions">
      <button type="button" data-close>Cancel</button>
      ${built ? `<button type="button" class="us-go" data-sign>Confirm in wallet</button>` : `<button type="button" class="us-go" data-review>Review</button>`}
    </div>`;
}

export function openUserSwap(e) {
  const wallet = walletFor(e.chain);
  if (!wallet) return;
  ctx = { e, wallet, side: "buy", built: null, pct: 100, amount: "", pay: pays(wallet.kind)[0][0] };
  if (wallet.kind === "solana" && phantom.needed()) phantom.preload().catch(() => {});
  sheet();
  paint();
  dlg.showModal();
}

function read() {
  const a = dlg.querySelector("[data-amount]");
  if (a) ctx.amount = a.value;
  const p = dlg.querySelector("[data-pay]");
  if (p) ctx.pay = p.value;
}

const keyOf = () => JSON.stringify([ctx.side, ctx.amount, ctx.pay, ctx.pct]);

async function review() {
  read();
  ctx.builtFor = keyOf();
  paint("Preparing…");
  try {
    ctx.built = await api.buildUserSwap({
      kind: ctx.wallet.kind, owner: ctx.wallet.address, side: ctx.side, token: ctx.e.token,
      amount: ctx.side === "buy" ? Number(ctx.amount) : null, pct: ctx.side === "sell" ? ctx.pct : null, pay: ctx.pay,
    });
    paint();
  } catch (err) { paint(escapeHtml(err?.message ?? "Couldn't prepare the swap.")); }
}

async function ensureRobinhood(eth) {
  try {
    await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: RH.chainId }] });
  } catch (err) {
    if (err?.code !== 4902) throw err;
    await eth.request({ method: "wallet_addEthereumChain", params: [RH] });
  }
}

async function receipt(eth, hash, ms = 120_000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    const r = await eth.request({ method: "eth_getTransactionReceipt", params: [hash] });
    if (r) { if (r.status === "0x0") throw new Error("The approval failed on chain."); return r; }
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error("The approval is taking long: try again in a minute.");
}

function loadWeb3() {
  if (window.solanaWeb3) return Promise.resolve(window.solanaWeb3);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = WEB3;
    s.onload = () => resolve(window.solanaWeb3);
    s.onerror = () => reject(new Error("Couldn't load the Solana library."));
    document.head.append(s);
  });
}

async function sign() {
  read();
  if (keyOf() !== ctx.builtFor) { review(); return; }   // the amount changed since the quote
  const b = ctx.built;
  try {
    if (b.kind === "evm") {
      const eth = window.ethereum;
      if (!eth) throw new Error("Open this page in your wallet's browser.");
      await ensureRobinhood(eth);
      let last = null;
      for (const [i, tx] of b.txs.entries()) {
        paint(`${tx.label}: confirm in your wallet (${i + 1}/${b.txs.length})…`);
        last = await eth.request({ method: "eth_sendTransaction", params: [{ from: ctx.wallet.address, to: tx.to, data: tx.data, value: tx.value }] });
        if (i < b.txs.length - 1) { paint("Waiting for the approval to land…"); await receipt(eth, last); }
      }
      paint(`Sent. <a href="${RH.blockExplorerUrls[0]}/tx/${escapeHtml(last)}" target="_blank" rel="noopener">See it on the explorer ↗</a>`);
    } else {
      const sol = window.phantom?.solana ?? window.solana;
      if (!sol) {
        // Safari on a phone: Phantom by deeplink, back to this page after
        // Face ID (phantomlink.js). Synchronous: iOS needs the tap.
        const s = phantom.session();
        if (!s) { phantom.connect({ op: "swap" }); return; }
        if (s.publicKey !== ctx.wallet.address) throw new Error(`Phantom is on ${s.publicKey.slice(0, 4)}…${s.publicKey.slice(-4)}, not on the connected wallet.`);
        paint("Confirm in Phantom…");
        phantom.signAndSend(Uint8Array.from(atob(b.tx_base64), (c) => c.charCodeAt(0)), { op: "swap", symbol: ctx.e?.symbol ?? "" });
        return;
      }
      paint("Confirm in Phantom…");
      const web3 = await loadWeb3();
      const tx = web3.VersionedTransaction.deserialize(Uint8Array.from(atob(b.tx_base64), (c) => c.charCodeAt(0)));
      const { signature } = await sol.signAndSendTransaction(tx);
      paint(`Sent. <a href="https://solscan.io/tx/${escapeHtml(signature)}" target="_blank" rel="noopener">See it on Solscan ↗</a>`);
    }
    ctx.built = null;
    dlg.querySelector("[data-sign]")?.remove();
  } catch (err) {
    paint(escapeHtml(err?.code === 4001 ? "You cancelled it in the wallet." : err?.message ?? "The wallet refused."));
  }
}

function onClick(event) {
  const t = event.target;
  const s = t.closest("[data-side]");
  if (s) { read(); ctx.side = s.dataset.side; ctx.built = null; paint(); return; }
  const p = t.closest("[data-pct]");
  if (p) { ctx.pct = Number(p.dataset.pct); ctx.built = null; paint(); return; }
  if (t.closest("[data-review]")) { review(); return; }
  if (t.closest("[data-sign]")) { sign(); return; }
  if (t.closest("[data-close]")) dlg.close();
}
