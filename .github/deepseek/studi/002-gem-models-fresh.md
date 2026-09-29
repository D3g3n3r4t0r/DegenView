# Study 002 — model gems with fresh data

## Claude's review (read before using anything below)

Verdict: **usable in part.** Much better than 001: it uses today's data,
admits what it cannot verify (it correctly says BV7X's "working repos" are
not shown: both linked repos are private; the account has one public repo,
`Mischa0x/bv7x-memory`, fixed in #341), and fits the token limit.

Checked against the dossiers and GeckoTerminal:
- Holder counts (AUREON 2149, PFWA 1801, GRID 1791) are real: GeckoTerminal.
- AUREON, PFWA, GRID have no tokenomics pillar because GoPlus has no data
  for them. GeckoTerminal has a distribution (top 10: AUREON 48.6%, PFWA
  35.2%, GRID 70.9%) but it counts pools and contracts, so it cannot drive
  the concentration limits as is.
- GRID's top1/top10 "per judge" are unverified, as DeepSeek says.

Adopted:
1. **Named, checkable primitives** (x402, ERC-8004, EAS, MCP, A2A,
   LayerZero, Turnkey, Umbra, MPC, TEE, FHE, Lean, STARK, zkVM, Polymarket
   as a data source) as a strong **bonus** and as a search pattern. Not
   must-have: AUREON names none in any text we can read.
2. **Some product surface** (app, docs, or public code). A project with no
   app, no docs and no code stays out (its §4 point 7).
3. Its search list (§5): GitHub topic/keyword queries and text patterns
   become discovery queries.
4. Its keep-list in §3 matches the current rules; nothing to change there.

Rejected:
- "holders >= 400" and "liquidity/cap >= 0.09" as must-haves: each is set
  just under the lowest of six examples (BV7X 405, DREGG 0.094). That is
  fitting the sample, not a rule. Holders already score on a log scale.
- "LP lock < 10% and liquidity < $150k: -20": three of five have 0%
  locked; on Robinhood (Uniswap v4) liquidity is not locked the usual way.
- Excluding PFWA as a memecoin with the regex `meme|fun|coin`: it matches
  the domain `pfwa.fun` and every "Bitcoin". PFWA is a launch platform for
  prediction-market-backed tokens (Credence), i.e. a product, not a meme.
- Changes 1, 4 and 6 of its §3 were already fixed (#339, #341). Change 7
  (age penalty) no longer exists (#337).

Next: GeckoTerminal fallback for tokenomics when GoPlus has nothing
(holders count, distribution as informational), named-primitives bonus in
the reader, and the §5 queries in discovery.

---

## Request

# Model gems, second pass: fresh data and the reviewer's corrections
tokens: robinhood:0xd293291060334D42E5DBEa6fb854C231AF527777, solana:G5W6LwkLeoj6rZqBP1y3KT8k6Cz6rXGJmMNU3TArXtXw, robinhood:0xa934bA4F59070149d37A93F8A002Af79BAe35563, robinhood:0x727701F88f09Fed71eb217Bcea88b3F314CF7079, robinhood:0x459476869aF797Eb9061B41fA04dE46A60FBeDBD, solana:XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump
follow_up: 001-gem-models
max_tokens: 8000

Your study 001 was reviewed line by line and is NOT usable yet. Reasons:
- It was built on stale pillar scores. PFWA's "empty page", GRID 29% and BV7X 41% "single wallet" (those were contracts: pools, vesting), BV7X "GitHub link without a repository" (it links working repos) were all bugs in our pipeline, now fixed. The dossiers below are recomputed today, every pillar fresh, with the top 10 holders labelled contract or wallet.
- "Domain registered before the token" is NOT a red flag: serious projects exist before their token. Do not use it.
- Thresholds like "holders >= 1500" or "LP locked >= 90%" were not derived from these projects' data; several of the five would fail them. Every number you propose must be satisfied by at least four of the five, and you must show the values.
- AUREON's SDK (github.com/buildaureon/aureon-sdk) was ignored, and a site we cannot read (JavaScript) is unknown, not weak.
- Your answer was cut at the token limit. Be dense: no repetition, no preamble.

Kept from 001 (confirm or refute with today's data): named, verifiable technical primitives (x402, LayerZero, ERC-8004, EAS, Turnkey, Umbra, Lean/STARK proofs) are the common thread; missing public code lowers confidence but does not exclude; the judge's "avoid" on STEALF was too harsh.

Answer in this order, compactly:
1. One table row per project (six, DREGG included): cap, liquidity/cap, age, wallet top1 and top10 (contracts excluded), contracts %, code (repo, last commit, stars or "private"), product live (evidence), named primitives found, our current verdict, right or wrong in one phrase.
2. The profile of a serious gem as 5-10 measurable signals. For each: the exact dossier field or text pattern, the threshold, the values of the six projects, must-have or bonus.
3. Which current checks to change and how (current rule -> new rule, with numbers), and which checks are right and must stay.
4. What must still exclude a project (memecoins, copies, rugs, parody names, wrappers), stated as checks, so that the changes in 3 do not let them in.
5. Search: 10-20 concrete search queries or sources (keywords, launchpads, chains, GitHub topics) that would surface more projects with this profile.
Mark every claim the dossiers do not support as "unverified".


## DeepSeek answer

# Study 001 — corrected with today's fresh dossiers

## 1. Project table (fresh pillars; contracts excluded from wallet top1/top10)

| Project | Cap | Liq/Cap | Age | Wallet top1 / top10 | Contracts % | Code | Product live | Named primitives | Current verdict | Right/wrong |
|---|---|---|---|---|---|---|---|---|---|---|
| AUREON | $107,378 | 0.54 | 73d | n/a (tokenomics pillar empty; GoPlus has no token) | n/a | `buildaureon/aureon-sdk`, last commit 0.5d, 252 commits/90d, 2 stars, MIT, tests true, ci false, 1 author | No app; site JS-unreadable; SDK is the only artefact | "Financial Compass", "capital health", "verified restore plans" (SDK description) | pending: GoPlus no token | **Wrong** — pending should be "code verified, tokenomics missing", not a block |
| STEALF | $691,871 | 0.30 | 14d | 10.1% / 31.4% | not given (insiders 4) | private (no public GitHub) | No app (`app: false`); docs live, 4 pages, 3 OK | **Turnkey, Umbra, MPC, TEE** | qualifies: DeepSeek "unverifiable marketing" | **Wrong** — judge's "avoid" too harsh (confirmed); named primitives are real |
| PFWA | $281,535 | 0.23 | 58d | n/a (tokenomics pillar empty) | n/a | private | Site live (`credence.pfwa.fun`), docs OK, 47 words, 1 page | **Polymarket** (data source), "Credence" | pending: GoPlus no token | **Wrong** — pending masks a real red flag: it is a **memecoin** ("Launch a meme token backed by a Polymarket prediction") |
| GRID | $1,899,198 | 0.10 | 75d | 18.9% / 30.7% (per judge; contracts 35.1%) | 35.1% | private | App responds (`app_ok: true`), 632 words, 0 pages OK, no docs | **LayerZero** | pending: GoPlus no token | **Wrong** — pending should be "thin site + 0% LP lock", not a tokenomics block |
| BV7X | $1,421,495 | 0.17 | 12d | 2.4% / 7.4% | 77.7% | private (GitHub link now resolves to working repos — pipeline bug fixed) | App responds, docs live, 1,431 words, 27 pages (2 OK), audit+roadmap+tokenomics sections | **MCP, A2A, ERC-8004, x402, EAS** | fatal: "GitHub link without a repository" | **Wrong** — fatal must be removed; the repo link is valid |
| DREGG | $1,959,007 | 0.094 | 94d | 3.4% / 23.9% | not given (insiders 807) | `emberian/dregg`, last commit 2.1d, 6,945 commits/90d, 34 stars, 8 forks, AGPL-3.0, tests+CI, 7 contributors | No app (`app: false`); docs live, 11 pages, 3 OK | **Lean 4, STARK, Mina/Pickles, zkVM, MPC/FHE** | passes | **Right** — benchmark holds |

**Confirmations from 001:** named, verifiable technical primitives are the common thread (Turnkey/Umbra, Polymarket, LayerZero, MCP/A2A/ERC-8004/x402/EAS, Lean/STARK) — **confirmed**. Missing public code lowers confidence but does not exclude — **confirmed** (STEALF, PFWA, GRID, BV7X all lack public code yet are hand-picked). STEALF's "avoid" was too harsh — **confirmed**.

**Refutations:** "domain registered before token" is not a red flag — **accepted, dropped**. "holders ≥ 1500" and "LP locked ≥ 90%" as must-haves — **refuted**: BV7X has 405 holders and 0% LP lock; PFWA/GRID/BV7X all have 0% LP lock. AUREON's SDK was ignored — **corrected** (252 commits/90d, tests true). Unreadable JS site is unknown, not weak — **accepted**.

---

## 2. Profile of a serious gem — measurable signals

Thresholds below are satisfied by **at least 4 of the 5** hand-picked projects (DREGG shown for reference). Values in parentheses.

| # | Signal | Field / pattern | Threshold | AUREON | STEALF | PFWA | GRID | BV7X | DREGG | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Named third-party primitive | regex over `site.tech_terms` + `<project_text>` for {Turnkey, Umbra, LayerZero, Polymarket, MCP, A2A, ERC-8004, x402, EAS, Lean, STARK, Mina, Pickles, MPC, TEE, FHE} | ≥ 1 match | 0 (only "Financial Compass") | 4 (Turnkey, Umbra, MPC, TEE) | 1 (Polymarket) | 1 (LayerZero) | 5 (MCP, A2A, ERC-8004, x402, EAS) | 5 | **must-have** |
| 2 | Product surface exists | `site.app_ok == true` OR `site.docs_ok == true` | at least one true | docs false, app false → **fails** | docs true | docs true | app true | app true + docs true | docs true | **must-have** (AUREON fails → pending) |
| 3 | Docs depth | `site.words` AND `site.internal_pages` | words ≥ 400 OR internal_pages ≥ 3 | 97 words, 1 page → fails | 451 words, 4 pages | 47 words, 1 page → fails | 632 words, 1 page | 1,431 words, 27 pages | 1,061 words, 11 pages | **bonus** (3/5 pass) |
| 4 | Holder base | `tokenomics.holders` | ≥ 400 | 2,149 (site pillar) | 4,349 | 1,801 | 1,791 | 405 | 7,634 | **must-have** (all 5 pass at ≥400) |
| 5 | Wallet top10 (contracts excluded) | `tokenomics.top10_pct` | ≤ 35% | n/a | 31.4% | n/a | 30.7% | 7.4% | 23.9% | **must-have** (all measured pass) |
| 6 | Wallet top1 (contracts excluded) | `tokenomics.top1_pct` | ≤ 20% | n/a | 10.1% | n/a | 18.9% | 2.4% | 3.4% | **must-have** (all measured pass) |
| 7 | Mint/freeze/tax | `tokenomics.mint`, `freeze`, `tax_pct` | mint=false, freeze=false, tax ≤ 5% | n/a | 0/0/0 | n/a | 0/0/0 | 0/0/0 | 0/0/0 | **must-have** (all measured pass) |
| 8 | Liquidity ratio | `liquidity / cap` | ≥ 0.09 | 0.54 | 0.30 | 0.23 | 0.10 | 0.17 | 0.094 | **must-have** (all 6 pass at ≥0.09) |
| 9 | Volume ratio | `volume_24h / cap` | ≥ 0.01 | 0.14 | 0.12 | 0.12 | 0.019 | 0.015 | 0.096 | **bonus** (all pass) |
| 10 | Code evidence | `github.commits_90d` AND `github.tests` | ≥ 100 commits/90d AND tests=true | 252, tests true | private | private | private | private | 6,945, tests true | **bonus** (2/6 have public code) |
| 11 | Self-stated limits | `site.tech_terms.candor` non-empty | ≥ 1 term | 0 | 0 | 0 | 0 | 0 | 4 | **bonus** (DREGG only) |
| 12 | Creator share | `tokenomics.creator_pct` | ≤ 5% | n/a | 0.0 | n/a | 0.0 | 0.0 | 0.0 | **must-have** (all measured pass) |

**Must-haves (all 5 hand-picked satisfy, or fail only on a pipeline gap):** #1 named primitive, #2 product surface, #4 holders ≥ 400, #5 top10 ≤ 35%, #6 top1 ≤ 20%, #7 mint/freeze/tax clean, #8 liq/cap ≥ 0.09, #12 creator ≤ 5%. AUREON fails #2 only because its site is JS-unreadable — that is a **pending**, not a fail. PFWA fails #3 but passes #1/#2/#4/#8.

---

## 3. Checks to change, and checks to keep

**Change:**

1. **`github: "link without a repository"` → fatal.** *New:* resolve the link; if it returns a repo with ≥1 commit, score normally; only fatal if the URL 404s **and** no other code evidence exists. (BV7X's link resolves — fatal removed.)
2. **`tokenomics: "GoPlus does not have the token yet"` → pending.** *New:* if GoPlus has no record, fall back to on-chain holder read; if that also fails, mark `pending: "tokenomics unmeasured"` and **do not** block the project. (AUREON, PFWA, GRID all hit this.)
3. **`site: "empty page"` → fatal.** *New:* if `site.words == 0` but `pages_ok ≥ 1` on any subdomain (PFWA's `credence.pfwa.fun` has 1 page OK), score the subdomain; fatal only if all subdomains return 0 words.
4. **`single wallet holds 29%/41%` → fatal.** *New:* fatal only if the wallet is an **EOA** (not labelled contract). GRID's 29% and BV7X's 41% were contracts (pools/vesting) — pipeline bug. *New rule:* `top1_pct > 25% AND holder_type == "wallet"` → fatal; `holder_type == "contract"` → informational.
5. **`lp_locked_pct == 0` → under-penalised.** *New:* `lp_locked_pct < 10` AND `liquidity < $150,000` → −20 score + red flag (PFWA $64,530, GRID $189,773, BV7X $247,479 — only PFWA/GRID fall under $150k). Not fatal alone.
6. **"token has no stated role" applied to everything.** *New:* apply only if `site.sections` contains `tokenomics` AND `utility` is empty. (AUREON, BV7X, DREGG currently hit this spuriously.)
7. **Age penalty.** *New:* remove standalone age penalty; use `domain_days / market.age` only as a **bonus** when ratio ≤ 3× (DREGG 1.1, PFWA 1.03, GRID 2.3). Do not penalise ratio > 3× (STEALF 27×, BV7X 20×) — refuted as a red flag.

**Keep (right, must stay):**

- `top1_pct > 25%` on a **wallet** → fatal.
- `top10_pct > 50%` on **wallets** → fatal.
- `mint == true` OR `freeze == true` → fatal.
- `tax_pct > 10` → fatal.
- `site.twin_similarity > 0.6` OR `site.original == false` → fatal (copy detection).
- `site.red_flags` containing "guaranteed returns", "risk-free", "presale" → fatal.
- `volume_24h < $5,000` AND `holders < 300` → fatal (dead token).
- `site.free_host == true` AND `site.domain_days < 30` → fatal.

---

## 4. What must still exclude a project

State as checks so the loosening in §3 cannot admit junk:

1. **Memecoin / parody name:** `project_text` matches `\b(meme|memecoin|parody|fun|coin)\b` AND `site.utility` empty AND no named primitive → exclude. (PFWA's own text: "Launch a meme token backed by a Polymarket prediction" — **PFWA should be excluded on this rule**, despite passing §2 #1/#2/#4/#8.)
2. **Copy / wrapper:** `site.twin_similarity > 0.6` OR `site.original == false` OR repo `fork_of != null` with no original commits → exclude.
3. **Rug mechanics:** `mint == true` OR `freeze == true` OR `tax_pct > 10` OR (`lp_locked_pct < 10` AND `liquidity < $150,000`) → exclude.
4. **Concentration:** wallet `top1_pct > 25%` OR wallet `top10_pct > 50%` → exclude.
5. **Dead / fake liquidity:** `volume_24h < $5,000` AND `holders < 300` → exclude.
6. **Throwaway deployment:** `site.free_host == true` AND `domain_days < 30` → exclude.
7. **No product and no code:** `site.app_ok == false` AND `site.docs_ok == false` AND `github.missing == true` → exclude (AUREON survives only because its SDK is public and verified).
8. **Hype-only text:** `site.red_flags` contains hype language AND `site.evidence.concrete` empty AND `site.tech_terms` empty → exclude.

---

## 5. Search strategy — 15 concrete queries / sources

**Chains / launchpads:** Robinhood Chain (Uniswap pools), Solana (Meteora, pumpswap), Base/Arbitrum/Polygon (LayerZero bridges), Virtuals launchpad, pump.fun.

**GitHub topics / queries:**
1. `topic:lean4 topic:zkvm` OR `topic:formal-verification` → DREGG-like.
2. `"object-capability" "STARK"` OR `"machine-checked" "Lean 4"` → DREGG-like.
3. `"MCP server" "x402"` OR `"ERC-8004" "agent"` → BV7X-like.
4. `"A2A protocol" "EAS attestation"` → BV7X-like.
5. `"Turnkey" "Umbra"` OR `"MPC" "TEE" "private transfers"` → STEALF-like.
6. `"LayerZero" "prediction market"` OR `"tokenized stocks" "onchain"` → GRID-like.
7. `"Polymarket" "prediction" "vault"` → PFWA-like (but filter out memecoin text).
8. `"financial intelligence" "treasury" "agents"` → AUREON-like.

**DexScreener / market filters:**
9. `chain in {robinhood, solana}` AND `liquidity/cap ≥ 0.09` AND `holders ≥ 400` AND wallet `top10 ≤ 35%` AND `mint == false` AND `freeze == false`.
10. `age ≤ 120d` AND `volume_24h/cap ≥ 0.01` AND `creator_pct ≤ 5%`.

**Site text patterns (regex over crawled docs):**
11. `(Turnkey|Umbra|LayerZero|Polymarket|MCP|A2A|ERC-8004|x402|EAS|Lean|STARK|Mina|Pickles|MPC|TEE|FHE)`.
12. `(audit|roadmap|tokenomics)` in `site.sections` AND `docs_ok == true`.
13. `(active research|named limit|no independent external audit|not ready for)` → candor bonus (DREGG only so far).

**Sources to add to the pipeline:**
14. GitHub search API filtered by `commits_90d ≥ 100`, `tests == true`, `created_at within 180d`, languages in {Lean, Rust, TypeScript, Solidity}.
15. Docs subdomain crawler: `docs.*`, `*.fun/docs`, `credence.*` — PFWA's real content was on `credence.pfwa.fun`, not the root domain.

**Unverified / missing in today's dossiers:** AUREON and PFWA tokenomics pillars are empty (`facts: {}`) — wallet top1/top10, contracts %, LP lock are **unverified** for both. GRID's wallet top1/top10 (18.9%/30.7%) come from the DeepSeek judge text, not a tokenomics pillar — **unverified**. BV7X's GitHub repo URL is not given in the dossier, so "links working repos" is **unverified** from the data shown. STEALF's contracts % is not given. DREGG's contracts % is not given.
