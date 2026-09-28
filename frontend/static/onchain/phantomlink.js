/**
 * Phantom from Safari on a phone, without moving into Phantom's own browser.
 *
 * Lorenzo, 28/09: "una connessione di un wallet esterno deve permettere di
 * aprirlo senza cambiare finestra di Safari [...] cambiare il pannello su
 * Safari e' una cosa ingestibile". Until now a phone without an injected
 * wallet was sent to Phantom's in-app browser: another window, another
 * login, and the rest of the session stuck there.
 *
 * Phantom's deeplink protocol (phantom.app/ul/v1/...): we open Phantom with
 * the request, the user approves with Face ID, Phantom sends them back to
 * this page with the answer. Keys never leave Phantom. Requests and answers
 * are encrypted with a key pair made here (tweetnacl box): only this browser
 * can read what comes back. The session and that key live in localStorage,
 * so the answer is read even if iOS brings the user back in a new tab.
 *
 * iOS opens Phantom only from a tap: every call that navigates to Phantom
 * must run synchronously inside the click, so `preload()` loads tweetnacl
 * beforehand and the builders below never await.
 */
const NACL = "https://unpkg.com/tweetnacl@1.0.3/nacl-fast.min.js";
const KEY = "lae:phantom";
const BASE = "https://phantom.app/ul/v1/";
const PARAMS = ["phantom", "phantom_encryption_public_key", "nonce", "data", "errorCode", "errorMessage"];

/* ------------------------------------------------------------ base58 */
const ALPHA = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

export function b58enc(bytes) {
  let zeros = 0;
  while (zeros < bytes.length && bytes[zeros] === 0) zeros++;
  const digits = [];
  for (let k = zeros; k < bytes.length; k++) {
    let carry = bytes[k];
    for (let i = 0; i < digits.length; i++) {
      carry += digits[i] << 8;
      digits[i] = carry % 58;
      carry = (carry / 58) | 0;
    }
    while (carry) { digits.push(carry % 58); carry = (carry / 58) | 0; }
  }
  let out = "1".repeat(zeros);
  for (let i = digits.length - 1; i >= 0; i--) out += ALPHA[digits[i]];
  return out;
}

export function b58dec(text) {
  let zeros = 0;
  while (zeros < text.length && text[zeros] === "1") zeros++;
  const bytes = [];
  for (let k = zeros; k < text.length; k++) {
    let carry = ALPHA.indexOf(text[k]);
    if (carry < 0) throw new Error("Not base58.");
    for (let i = 0; i < bytes.length; i++) {
      carry += bytes[i] * 58;
      bytes[i] = carry & 0xff;
      carry >>= 8;
    }
    while (carry) { bytes.push(carry & 0xff); carry >>= 8; }
  }
  const out = new Uint8Array(zeros + bytes.length);
  for (let i = 0; i < bytes.length; i++) out[zeros + i] = bytes[bytes.length - 1 - i];
  return out;
}

/* ------------------------------------------------------------ state */
const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } };
const write = (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ } };

/** True where Phantom is not injected in the page (Safari on a phone). */
export const needed = () => !(window.phantom?.solana ?? (window.solana?.isPhantom ? window.solana : null));

/** The wallet connected through deeplinks, if any: {publicKey}. */
export function session() {
  const s = read();
  return s.session && s.publicKey && s.shared ? { publicKey: s.publicKey } : null;
}

export function forget() { write({}); }

let nacl = window.nacl ?? null;
export function preload() {
  if (nacl) return Promise.resolve(nacl);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = NACL;
    s.onload = () => { nacl = window.nacl; resolve(nacl); };
    s.onerror = () => reject(new Error("Couldn't load the encryption library."));
    document.head.append(s);
  });
}

function need() {
  if (!nacl) throw new Error("Still loading, tap again.");
  return nacl;
}

function back(op) {
  const u = new URL(location.href);
  for (const k of PARAMS) u.searchParams.delete(k);
  u.searchParams.set("phantom", op);
  return u.toString();
}

/* ------------------------------------------------------------ requests */

/** Open Phantom to connect. `pending` comes back with the answer. */
export function connect(pending = null) {
  const n = need();
  const kp = n.box.keyPair();
  write({ secret: b58enc(kp.secretKey), dappPublic: b58enc(kp.publicKey), pending });
  const q = new URLSearchParams({
    app_url: location.origin, dapp_encryption_public_key: b58enc(kp.publicKey),
    redirect_link: back("connect"), cluster: "mainnet-beta",
  });
  location.href = `${BASE}connect?${q}`;
}

function request(method, payload, pending) {
  const n = need();
  const s = read();
  if (!s.session || !s.shared) throw new Error("Connect Phantom first.");
  const nonce = n.randomBytes(24);
  const box = n.box.after(new TextEncoder().encode(JSON.stringify({ ...payload, session: s.session })), nonce, b58dec(s.shared));
  write({ ...s, pending });
  const q = new URLSearchParams({
    dapp_encryption_public_key: s.dappPublic, nonce: b58enc(nonce),
    redirect_link: back(method), payload: b58enc(box),
  });
  location.href = `${BASE}${method}?${q}`;
}

/** Sign a text message (free, not a transaction). Answer: {signature}. */
export const signMessage = (text, pending) =>
  request("signMessage", { message: b58enc(new TextEncoder().encode(text)), display: "utf8" }, pending);

/** Sign and send a serialized transaction. Answer: {signature}. */
export const signAndSend = (txBytes, pending) =>
  request("signAndSendTransaction", { transaction: b58enc(txBytes) }, pending);

/* ------------------------------------------------------------ answers */

/** On page load: Phantom's answer, if this page was opened by it, as
 *  {op, pending, data} or {op, pending, error}. The URL is cleaned. */
export async function takeAnswer() {
  const u = new URL(location.href);
  const op = u.searchParams.get("phantom");
  if (!op) return null;
  const p = Object.fromEntries(u.searchParams);
  for (const k of PARAMS) u.searchParams.delete(k);
  history.replaceState(history.state, "", u.toString());
  const s = read();
  const pending = s.pending ?? null;
  write({ ...s, pending: null });
  if (p.errorCode) {
    return { op, pending, error: p.errorCode === "4001" ? "You cancelled it in Phantom." : p.errorMessage || `Phantom error ${p.errorCode}` };
  }
  try {
    const n = await preload();
    let shared = s.shared ? b58dec(s.shared) : null;
    if (op === "connect") {
      if (!s.secret) throw new Error("This browser didn't start the connection: try again.");
      shared = n.box.before(b58dec(p.phantom_encryption_public_key), b58dec(s.secret));
    }
    const plain = shared && n.box.open.after(b58dec(p.data), b58dec(p.nonce), shared);
    if (!plain) throw new Error("Phantom's answer couldn't be read: try again.");
    const data = JSON.parse(new TextDecoder().decode(plain));
    if (op === "connect") {
      write({ secret: s.secret, dappPublic: s.dappPublic, shared: b58enc(shared),
              session: data.session, publicKey: data.public_key, pending: null });
    }
    return { op, pending, data };
  } catch (err) {
    return { op, pending, error: err?.message ?? "Phantom's answer couldn't be read." };
  }
}
