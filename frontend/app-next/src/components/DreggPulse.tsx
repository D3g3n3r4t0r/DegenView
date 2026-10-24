import { useEffect, useState } from "react";
import * as api from "../lib/api";

function relIso(iso?: string): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso.slice(0, 10);
  const diffS = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffS < 60) return "ora";
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m fa`;
  if (diffS < 86400) return `${Math.floor(diffS / 3600)}h fa`;
  const days = Math.floor(diffS / 86400);
  return `${days}g fa`;
}

function tierBadge(tier: string): { label: string; cls: string } {
  if (tier === "active-core") return { label: "ATTIVO ORA · CORE", cls: "bg-up/15 text-up border border-up/30" };
  if (tier === "core-spec") return { label: "SPEC & DEMOLAND", cls: "bg-sage/30 text-on-sage border border-sage" };
  if (tier === "monolith-paused") return { label: "MONOLITE (PAUSA)", cls: "bg-pill text-text-2 border border-line" };
  return { label: "R&D / INFRA", cls: "bg-pill text-text-3 border border-line" };
}

export function DreggPulseBanner({ onOpenTab }: { onOpenTab: () => void }) {
  const [data, setData] = useState<api.DreggPulseData | null>(null);
  useEffect(() => {
    let alive = true;
    api.getDreggPulse(false).then((d) => { if (alive) setData(d); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const pct = data?.mainnet_roadmap.overall_readiness_pct ?? 65.2;
  const commitsAll = data?.github_summary.total_commits_all_repos ?? 16297;
  const c24 = data?.github_summary.commits_24h ?? 23;
  const c7d = data?.github_summary.commits_7d ?? 159;
  const thm = data?.nanodregg_ratchet.lean_theorems ?? 6305;

  return (
    <div className="mt-3 rounded-[16px] border border-line bg-card p-3.5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-up animate-pulse" />
          <b className="text-[13px] font-semibold tracking-tight">DREGG Mainnet & GitHub Observatory</b>
          <span className="rounded-full bg-pill px-2 py-0.5 text-[11px] font-mono text-text-2">
            8 repo · {commitsAll.toLocaleString()} commit
          </span>
        </div>
        <button
          type="button"
          onClick={onOpenTab}
          className="rounded-full bg-ink px-3 py-1 text-[12px] font-semibold text-on-ink transition-opacity hover:opacity-90"
        >
          Apri Dossier DREGG ↗
        </button>
      </div>

      <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-[11px] bg-bg px-2.5 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.06em] text-text-3">Progresso Mainnet</div>
          <div className="num text-[15px] font-bold text-up">{pct.toFixed(1)}%</div>
          <div className="text-[10.5px] text-text-3">Devnet ~3–4m · Mainnet ~6–9m</div>
        </div>
        <div className="rounded-[11px] bg-bg px-2.5 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.06em] text-text-3">Push 24h / 7g</div>
          <div className="num text-[15px] font-bold">+{c24} <span className="text-[12px] font-normal text-text-3">/ +{c7d}</span></div>
          <div className="text-[10.5px] text-text-3">attivo su nanodregg & dragons-net</div>
        </div>
        <div className="rounded-[11px] bg-bg px-2.5 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.06em] text-text-3">Teoremi Lean 4</div>
          <div className="num text-[15px] font-bold">{thm.toLocaleString()}</div>
          <div className="text-[10.5px] text-up">0 sorry · 0 partial</div>
        </div>
        <div className="rounded-[11px] bg-bg px-2.5 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.06em] text-text-3">Team & Swarm</div>
          <div className="num text-[15px] font-bold">6 dev <span className="text-[12px] font-normal text-text-3">+ 9 lane AI</span></div>
          <div className="text-[10.5px] text-text-3">Ember + Wisper + akapug</div>
        </div>
      </div>
    </div>
  );
}

export function DreggPulseView() {
  const [data, setData] = useState<api.DreggPulseData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [subView, setSubView] = useState<"roadmap" | "repos" | "team" | "techtree">("roadmap");

  const load = (force = false) => {
    if (force) setRefreshing(true);
    else setLoading(true);
    api.getDreggPulse(force)
      .then((d) => setData(d))
      .catch(() => {})
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    load(false);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load(false);
    }, 120_000);
    return () => clearInterval(timer);
  }, []);

  if (loading && !data) {
    return (
      <div className="py-8 text-center text-[13.5px] text-text-3">
        Caricamento telemetria multi-repo DREGG (8 repository + Tech Tree + Horizon Map)…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="py-6 text-center text-[13.5px] text-text-3">
        Impossibile caricare i dati DREGG in questo momento.
        <button type="button" onClick={() => load(true)} className="ml-2 underline">Riprova</button>
      </div>
    );
  }

  const { github_summary: gs, mainnet_roadmap: mr, nanodregg_ratchet: nr, tech_tree: tt, horizon_map: hm } = data;

  return (
    <div className="space-y-4 pb-8 text-[13.5px] leading-snug">
      {/* HERO: Mainnet Readiness & Live Refresh */}
      <section className="rounded-[18px] border border-line bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-up animate-pulse" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
                Dragon&apos;s Egg · Live Multi-Repo Telemetry
              </span>
            </div>
            <h3 className="mt-1 text-[17px] font-bold tracking-tight">
              Progresso verso Mainnet: <span className="num text-up">{mr.overall_readiness_pct.toFixed(1)}%</span>
              <span className="ml-2 text-[12px] font-normal text-text-3">
                ({mr.strict_built_pct.toFixed(1)}% già chiuso e verificato · resto in costruzione)
              </span>
            </h3>
          </div>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => load(true)}
            className="h-8 rounded-full bg-pill px-3 text-[12px] font-semibold text-text transition-colors hover:bg-line disabled:opacity-50"
          >
            {refreshing ? "Aggiornamento…" : `↻ Aggiorna live (${relIso(new Date(data.updated_at * 1000).toISOString())})`}
          </button>
        </div>

        {/* Multi-segment progress bar */}
        <div className="mt-3">
          <div className="h-3 w-full overflow-hidden rounded-full bg-bg p-0.5">
            <div
              className="h-full rounded-full bg-up transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(8, mr.overall_readiness_pct))}%` }}
            />
          </div>
          <div className="mt-1.5 flex justify-between text-[11px] text-text-3">
            <span>Spec J0–J8 &amp; Kernel Lean 4 (45.8% Holds Today)</span>
            <span>In lavorazione (30.0% Being Fought)</span>
            <span>Mainnet ZK + Audit</span>
          </div>
        </div>

        <p className="mt-3 rounded-[12px] bg-bg p-3 text-[12.5px] text-text-2">
          <b className="text-text">Verdetto Distanza Mainnet:</b> {mr.verdict_short}.{" "}
          <span className="text-text-3">{mr.verdict_detail}</span>
        </p>

        {/* Top 6 KPIs */}
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div className="rounded-[12px] bg-bg p-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-text-3">Commit Ecosistema (8 Repo)</div>
            <div className="num mt-0.5 text-[17px] font-bold">{gs.total_commits_all_repos.toLocaleString()}</div>
            <div className="text-[11px] text-up">+{gs.commits_24h} in 24h · +{gs.commits_7d} in 7g</div>
          </div>
          <div className="rounded-[12px] bg-bg p-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-text-3">Ultimo Push Reale</div>
            <div className="num mt-0.5 text-[17px] font-bold">{relIso(gs.latest_push_at)}</div>
            <div className=" truncate text-[11px] text-text-3">su {gs.primary_active_repo}</div>
          </div>
          <div className="rounded-[12px] bg-bg p-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-text-3">Sviluppatori &amp; Agenti</div>
            <div className="num mt-0.5 text-[17px] font-bold">
              {gs.human_contributors_count} umani + {gs.agent_lanes_count} lane
            </div>
            <div className="text-[11px] text-text-3">Ember + Wisper + akapug</div>
          </div>
          <div className="rounded-[12px] bg-bg p-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-text-3">Teoremi Lean 4 (Nano)</div>
            <div className="num mt-0.5 text-[17px] font-bold">{nr.lean_theorems.toLocaleString()}</div>
            <div className="text-[11px] text-up">{nr.lean_sorry} sorry · {nr.lean_partial} partial</div>
          </div>
          <div className="rounded-[12px] bg-bg p-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-text-3">Tech Tree (dregg.net)</div>
            <div className="num mt-0.5 text-[17px] font-bold">{tt.weighted_pct}%</div>
            <div className="text-[11px] text-text-3">{tt.built} chiusi · {tt.in_progress} WIP / {tt.active_nodes}</div>
          </div>
          <div className="rounded-[12px] bg-bg p-2.5">
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-text-3">Horizon Map (17 linee)</div>
            <div className="num mt-0.5 text-[17px] font-bold">{hm.weighted_pct}%</div>
            <div className="text-[11px] text-text-3">{hm.holds_today} Holds Today · {hm.being_fought} WIP</div>
          </div>
        </div>
      </section>

      {/* SUB-NAVIGATION PILLS */}
      <div className="flex flex-wrap gap-1.5 rounded-full bg-pill p-1">
        {([
          ["roadmap", "1. Countdown Mainnet (3 Fasi)"],
          ["repos", `2. GitHub (${data.repos.length} Repo & Push)`],
          ["team", "3. Chi ci lavora & Swarm"],
          ["techtree", `4. Tech Tree (${tt.goals.length} Goal)`],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setSubView(key)}
            className={`flex-1 rounded-full px-3 py-1.5 text-[12px] font-semibold transition-colors ${
              subView === key ? "bg-card text-text shadow-sm" : "text-text-2 hover:text-text"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* SUBVIEW 1: 3-PHASE MAINNET ROADMAP & NANODREGG RATCHET */}
      {subView === "roadmap" && (
        <div className="space-y-3">
          {mr.phases.map((p) => (
            <article key={p.id} className="rounded-[16px] border border-line bg-card p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="rounded-full bg-pill px-2.5 py-0.5 text-[11px] font-semibold text-text-2">
                    {p.phase} · ETA: {p.eta_months} ({p.eta_window})
                  </span>
                  <h4 className="mt-1 text-[15px] font-bold">{p.title}</h4>
                  <p className="text-[12px] text-text-3">{p.subtitle}</p>
                </div>
                <div className="text-right">
                  <div className="num text-[20px] font-bold text-up">{p.progress_pct}%</div>
                  <div className="text-[11px] text-text-3">completamento stimato</div>
                </div>
              </div>

              <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-bg">
                <div className="h-full rounded-full bg-up" style={{ width: `${p.progress_pct}%` }} />
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-[12px] bg-bg p-2.5">
                  <div className="text-[11px] font-semibold text-up">✓ Già costruito e verificato</div>
                  <ul className="mt-1.5 space-y-1 text-[12px] text-text-2">
                    {p.completed_items.map((item, idx) => (
                      <li key={idx} className="flex gap-1.5">
                        <span className="text-up">•</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-[12px] bg-bg p-2.5">
                  <div className="text-[11px] font-semibold text-down">⏳ Cosa manca per chiudere la fase</div>
                  <ul className="mt-1.5 space-y-1 text-[12px] text-text-2">
                    {p.remaining_blockers.map((item, idx) => (
                      <li key={idx} className="flex gap-1.5">
                        <span className="text-down">•</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </article>
          ))}

          {/* Live SIZE.md Ratchet Card */}
          <section className="rounded-[16px] border border-line bg-card p-4">
            <div className="flex items-center justify-between">
              <h4 className="text-[14px] font-bold">
                Telemetria Formale Live — <code className="font-mono text-[12.5px]">nanodregg/SIZE.md</code>
              </h4>
              <a
                href="https://github.com/emberian/nanodregg/blob/main/SIZE.md"
                target="_blank"
                rel="noopener"
                className="text-[12px] font-medium text-text-2 underline"
              >
                Verifica su GitHub ↗
              </a>
            </div>
            <p className="mt-1 text-[12px] text-text-3">
              Ogni singolo commit su <code className="font-mono">nanodregg</code> deve superare{" "}
              <code className="font-mono">gates/size.py</code> e <code className="font-mono">gates/census.py</code>:
              zero <code className="font-mono">sorry</code>, zero <code className="font-mono">partial def</code> e parità bit-a-bit Lean ↔ Rust.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div className="rounded-[10px] bg-bg p-2.5">
                <div className="text-[10.5px] text-text-3">Righe Lean 4.30</div>
                <div className="num text-[15px] font-bold">{nr.lean_lines.toLocaleString()}</div>
                <div className="text-[11px] text-text-3">{nr.lean_modules} moduli</div>
              </div>
              <div className="rounded-[10px] bg-bg p-2.5">
                <div className="text-[10.5px] text-text-3">Righe Rust Shell</div>
                <div className="num text-[15px] font-bold">{nr.rust_lines.toLocaleString()}</div>
                <div className="text-[11px] text-text-3">rapporto {nr.proof_ratio}:1</div>
              </div>
              <div className="rounded-[10px] bg-bg p-2.5">
                <div className="text-[10.5px] text-text-3">Conformance Rows</div>
                <div className="num text-[15px] font-bold text-up">{nr.conformance_rows} / 45</div>
                <div className="text-[11px] text-text-3">Lean ↔ Rust bit-exact</div>
              </div>
              <div className="rounded-[10px] bg-bg p-2.5">
                <div className="text-[10.5px] text-text-3">Defect Ledger (D1–D9)</div>
                <div className="num text-[15px] font-bold text-up">
                  {nr.defect_ledger_closed} / {nr.defect_ledger_total}
                </div>
                <div className="text-[11px] text-text-3">difetti strutturali chiusi</div>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* SUBVIEW 2: ALL 8 REPOSITORIES & LIVE COMMIT FEED */}
      {subView === "repos" && (
        <div className="space-y-3">
          <div className="rounded-[14px] bg-bg p-3 text-[12px] text-text-2">
            <b>Perché sembrava fermo guardando solo <code className="font-mono">emberian/dregg</code>?</b>{" "}
            Il monolite originale (<code className="font-mono">dregg</code>, 10.359 commit) è in pausa dal 2 ottobre perché Ember ha spostato lo sviluppo attivo su{" "}
            <b><code className="font-mono">nanodregg</code></b> (706 commit in 8 giorni = ~88 commit/giorno!),{" "}
            <b><code className="font-mono">minidregg</code></b> (4.141 commit) e{" "}
            <b><code className="font-mono">dragons-net</code></b> (136 commit, compilatore verificato Lean→CakeML con Alan Wisper).
          </div>

          <div className="grid gap-2.5">
            {data.repos.map((r) => {
              const badge = tierBadge(r.tier);
              return (
                <article key={r.repo} className="rounded-[14px] border border-line bg-card p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noopener"
                        className="font-mono text-[14px] font-bold hover:underline"
                      >
                        {r.repo} ↗
                      </a>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge.cls}`}>
                        {badge.label}
                      </span>
                      <span className="rounded-full bg-pill px-2 py-0.5 text-[10.5px] text-text-3">
                        {r.codename} · {r.language}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-[12px]">
                      <span className="num font-semibold">{r.total_commits.toLocaleString()} commit</span>
                      <span className="text-text-3">push {relIso(r.pushed_at)}</span>
                    </div>
                  </div>
                  <p className="mt-1 text-[12px] text-text-2">{r.role}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-text-3">
                    <span className="rounded-md bg-bg px-2 py-0.5">
                      24h: <b className={r.commits_24h > 0 ? "text-up" : "text-text"}>{r.commits_24h} commit</b>
                    </span>
                    <span className="rounded-md bg-bg px-2 py-0.5">
                      7g: <b className={r.commits_7d > 0 ? "text-up" : "text-text"}>{r.commits_7d} commit</b>
                    </span>
                    <span className="rounded-md bg-bg px-2 py-0.5">★ {r.stars}</span>
                    {r.open_issues > 0 && (
                      <span className="rounded-md bg-bg px-2 py-0.5">{r.open_issues} issue/PR aperte</span>
                    )}
                    <span className="rounded-md bg-bg px-2 py-0.5">
                      Autori: {r.authors_recent.join(", ")}
                    </span>
                  </div>
                </article>
              );
            })}
          </div>

          {/* Live Commit Stream */}
          <section className="rounded-[16px] border border-line bg-card p-4">
            <h4 className="text-[14px] font-bold">Ultimi Commit Verificati sull&apos;Ecosistema DREGG</h4>
            <div className="mt-2.5 divide-y divide-line">
              {data.recent_commits.slice(0, 12).map((c) => (
                <div key={`${c.repo}-${c.sha}`} className="py-2 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-2 text-[11.5px]">
                    <span className="font-mono font-semibold text-text">
                      {c.repo.replace("emberian/", "")}{" "}
                      <span className="text-text-3">#{c.sha}</span> · <span className="text-up">{c.author}</span>
                    </span>
                    <span className="text-text-3">{relIso(c.date)}</span>
                  </div>
                  <p className="mt-0.5 truncate text-[12px] text-text-2">{c.message}</p>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* SUBVIEW 3: WHO IS WORKING ON IT (HUMANS + AGENTIC SWARM) */}
      {subView === "team" && (
        <div className="space-y-3">
          <section className="rounded-[16px] border border-line bg-card p-4">
            <h4 className="text-[14px] font-bold">
              Contributori Umani Attivi ({data.contributors.length} rilevati nei repository)
            </h4>
            <p className="mt-1 text-[12px] text-text-3">
              Guidato da <b>{data.lead_developer.name}</b> ({data.lead_developer.organization}, {data.lead_developer.location}) — {data.lead_developer.background}.
            </p>
            <div className="mt-3 grid gap-2.5">
              {data.contributors.map((c) => (
                <div key={c.handle} className="rounded-[12px] bg-bg p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${c.active_now ? "bg-up" : "bg-text-3"}`} />
                      <a
                        href={`https://github.com/${c.handle}`}
                        target="_blank"
                        rel="noopener"
                        className="font-semibold hover:underline"
                      >
                        {c.name} (@{c.handle}) ↗
                      </a>
                      <span className="rounded-full bg-card px-2 py-0.5 text-[11px] text-text-2">{c.role}</span>
                    </div>
                    <span className="num text-[12px] font-bold">{c.commits_total.toLocaleString()}+ commit</span>
                  </div>
                  <p className="mt-1 text-[12px] text-text-2">{c.recent_focus}</p>
                  <div className="mt-1 text-[11px] text-text-3">Repo: {c.repos.join(", ")}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-[16px] border border-line bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-[14px] font-bold">
                Architettura Multi-Agente ({data.agent_swarm.model})
              </h4>
              <span className="rounded-full bg-pill px-2.5 py-0.5 text-[11px] font-semibold">
                {data.agent_swarm.active_agents_estimate}
              </span>
            </div>
            <p className="mt-1 text-[12px] text-text-2">{data.agent_swarm.gate_discipline}</p>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {data.agent_swarm.lanes.map((l) => (
                <div key={l.lane} className="rounded-[10px] bg-bg p-2.5">
                  <div className="font-mono text-[11.5px] font-bold text-up">LANE: {l.lane}</div>
                  <div className="mt-0.5 text-[11.5px] text-text-2">{l.scope}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* SUBVIEW 4: TECH TREE GOALS & HORIZON MAP */}
      {subView === "techtree" && (
        <div className="space-y-3">
          <section className="rounded-[16px] border border-line bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className="text-[14px] font-bold">
                  18 Strategic Goals dal Tech Tree (<code className="font-mono text-[12px]">dregg.net/tech-tree</code>)
                </h4>
                <p className="text-[12px] text-text-3">
                  {tt.built} nodi completati (Built), {tt.in_progress} in costruzione (WIP), {tt.planned} pianificati su {tt.active_nodes} nodi attivi.
                </p>
              </div>
              <div className="flex gap-2">
                <a
                  href={data.lead_developer.tech_tree_url}
                  target="_blank"
                  rel="noopener"
                  className="rounded-full bg-pill px-3 py-1 text-[11.5px] font-semibold hover:bg-line"
                >
                  Tech Tree ↗
                </a>
                <a
                  href={data.lead_developer.horizon_url}
                  target="_blank"
                  rel="noopener"
                  className="rounded-full bg-pill px-3 py-1 text-[11.5px] font-semibold hover:bg-line"
                >
                  Horizon Map ↗
                </a>
              </div>
            </div>

            <div className="mt-3 space-y-2.5">
              {tt.goals.map((g) => (
                <div key={g.id} className="rounded-[12px] bg-bg p-3">
                  <div className="flex items-center justify-between gap-2">
                    <b className="text-[13px] font-semibold">{g.title}</b>
                    <span className="num text-[12.5px] font-bold text-up">
                      {g.pct}% <span className="font-normal text-text-3">({g.done}✓ · {g.wip}⚙ · {g.planned}⏳ / {g.total})</span>
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-card">
                    <div className="h-full rounded-full bg-up" style={{ width: `${g.pct}%` }} />
                  </div>
                  {g.remaining.length > 0 && (
                    <div className="mt-1.5 text-[11px] text-text-3">
                      <b>Manca:</b> {g.remaining.join(" · ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-[14px] border border-line bg-card p-3.5 text-[12px] text-text-3">
            <b className="text-text">Consumo Token &amp; Capacità Settimanale:</b> {data.cost_and_capacity.note}
          </section>
        </div>
      )}
    </div>
  );
}
