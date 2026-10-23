import { useEffect, useState } from "react";
import * as api from "../lib/api";
import type { ClusterCheck, SellsReport } from "../lib/api";
import { t } from "../lib/i18n";

// Lorenzo, 22/10: "quando faccio partire un cluster check manuale voglio
// vederlo partire subito". The check is read every 2 s while it waits or
// runs, its phase drawn as four steps and a bar, never a still screen.
export const STEPS = [["transfers", "Transfers"], ["holders", "Holders"], ["clusters", "Clusters"], ["sells", "Sells"]] as const;
const active = (c: ClusterCheck) => c.state === "queued" || c.state === "running" || (c.state === "built" && !!c.clusters);

/** The token's report, or where its check stands (polled until the report lands). */
export function useClusterCheck(chain: string, token: string, starting = false, bump = 0) {
  const [rep, setRep] = useState<SellsReport | null>(null);
  const [check, setCheck] = useState<ClusterCheck | null>(null);
  useEffect(() => {
    let live = true, t = 0;
    const since = Date.now();
    setRep(null); setCheck(null);
    const n = token.startsWith("0x") ? token.toLowerCase() : token;
    // Reports only at the start and once clusters are built: the check alone is cheap.
    const tick = (reports: boolean) => (reports ? api.getCoordinatedSells() : Promise.resolve(null)).then((d) => {
      if (!live) return;
      const found = d && !d.sample ? (d.reports ?? []).find((r) => r.chain === chain && r.token === n) : null;
      if (found) { setRep(found); return; }
      return api.getClusterCheck(chain, token).then((c) => {
        if (!live) return;
        // Just tapped: the request may not be in line yet, so "none" is not an answer for 15 s.
        const early = (starting || bump > 0) && c.state === "none" && Date.now() - since < 15000;
        setCheck(early ? null : c);
        if (early || active(c)) t = window.setTimeout(() => tick(c.state === "built"), c.state === "built" ? 5000 : 2000);
      });
    }).catch(() => { if (live) t = window.setTimeout(() => tick(true), 10000); });
    tick(true);
    return () => { live = false; clearTimeout(t); };
  }, [chain, token, bump]);
  return { rep, check };
}

/** Which step is on (−1 = waiting in line) and how far into it, 0..1 (null = unknown). */
function where(c: ClusterCheck | null): [number, number | null] {
  if (!c) return [0, null];
  const i = STEPS.findIndex(([k]) => k === c.phase);
  if (i >= 0) return [i, c.progress ?? null];
  if (c.state === "queued") return [-1, null];
  if (c.state === "built") return [c.clusters ? 3 : 4, null];
  return [0, null];
}

/** A check in motion: what it is doing now, the four steps, a moving bar,
 *  and a custom link input when the chain is not covered automatically (Lorenzo, 23/10). */
export function CheckProgress({ check, title, chain, token, onStarted }: { check: ClusterCheck | null; title?: string; chain?: string; token?: string; onStarted?: () => void }) {
  const [step, part] = where(check);
  const busy = !check || active(check);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [url, setUrl] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [busy]);
  const secs = check?.started_at ? Math.max(0, Math.round(now - check.started_at)) : null;
  const head = !check ? t("Started")
    : check.state === "queued" ? (check.place ? t("Queued, place {n}: it starts when the checks ahead end", { n: check.place }) : t("Queued: it starts when the checks ahead end"))
    : check.state === "running" ? t("Reading {what}…", { what: t(STEPS[Math.max(0, step)][1]).toLowerCase() })
    : check.state === "built" && check.clusters ? t("{n} cluster(s) found. Reading their sells…", { n: check.clusters })
    : check.state === "built" ? t("Done: no wallet cluster among the top holders")
    : check.state === "failed" ? t("Failed on this token's data. Paste an explorer or DexScreener link below to analyze it.")
    : check.state === "unsupported" ? t("Not available automatically on this chain. Paste an explorer or DexScreener link below to analyze it.") : t("Not started yet");
  const fill = step < 0 ? 0 : Math.min(1, (step + (part ?? 0.5)) / STEPS.length);
  const bad = check?.state === "failed" || check?.state === "unsupported";
  const canLink = (bad || check?.state === "none") && !!chain && !!token;
  const validUrl = /^https?:\/\/\S+$/i.test(url.trim());

  const submitUrl = async () => {
    if (!canLink || !validUrl || sending) return;
    setSending(true); setErr("");
    try {
      await api.askClusterCheck(chain!, token!, url.trim());
      setUrl("");
      onStarted?.();
    } catch (e) {
      setErr((e as Error).message || t("Not started, try again."));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="rounded-[16px] bg-card p-4" role="status" aria-live="polite">
      {title && <b className="mb-1 block text-[14px] font-semibold">{title}</b>}
      <p className={`flex items-center gap-2 text-[13.5px] ${bad ? "text-down" : "text-text-2"}`}>
        {busy && <i className="cp-spin h-3.5 w-3.5 flex-none rounded-full border-2 border-amber border-t-transparent" aria-hidden="true" />}
        <span className="min-w-0 flex-1">{head}</span>
        {busy && secs != null && <span className="num text-[12px] text-text-3">{secs}s</span>}
      </p>
      {canLink && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row" onClick={(e) => e.stopPropagation()}>
          <input value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder={t("Paste an explorer, Blockscout, or DexScreener link (https://…)")}
            aria-label={t("Explorer or DexScreener link")}
            className="h-10 min-w-0 flex-1 rounded-full bg-pill px-3.5 text-[13.5px] text-ink outline-none placeholder:text-text-3" />
          <button type="button" disabled={!validUrl || sending} onClick={submitUrl}
            className="h-10 flex-none rounded-full bg-ink px-4 text-[13.5px] font-semibold text-on-ink transition-opacity disabled:opacity-40">
            {sending ? t("Starting…") : t("Analyze link")}
          </button>
        </div>
      )}
      {err && <p className="mt-1.5 text-[12.5px] text-down">{err}</p>}
      {busy && (
        <>
          <div className="relative mt-3 h-1.5 overflow-hidden rounded-full bg-pill">
            <i className="absolute inset-y-0 left-0 w-full origin-left rounded-full bg-ink transition-transform duration-500" style={{ transform: `scaleX(${fill})` }} aria-hidden="true" />
            {part == null && step < STEPS.length
              ? <i className="cp-slide absolute inset-y-0 left-0 w-1/3 rounded-full bg-amber/80" aria-hidden="true" />
              : null}
          </div>
          {check?.live?.counts && (
            <dl className="mt-3 grid grid-cols-4 gap-1">
              {([["holders", "holders"], ["transfers", "transfers"], ["clusters", "clusters"], ["waves", "waves"]] as const).map(([k, label]) => (
                <div key={k}><dt className="text-[11px] text-text-3">{t(label)}</dt><dd className="num text-[17px] font-semibold leading-tight">{check.live?.counts?.[k] ?? "—"}</dd></div>
              ))}
            </dl>
          )}
          <ol className="mt-2 grid grid-cols-4 gap-1 text-[11.5px]">
            {STEPS.map(([k, label], i) => (
              <li key={k} className={i < step ? "text-text-2" : i === step ? "font-semibold text-ink" : "text-text-3"}>{i < step ? "✓ " : ""}{t(label)}</li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
