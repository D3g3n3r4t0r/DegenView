# Liquidity Analysis Engine — Handover

## Repo & Deploy

- **Repo**: `lorenzocorazzi-wq/liquidity-analysis-engine`
- **Feature branch**: `claude/interface-design-m6q27s`
- **Main branch tip**: `e26027e` (Minimal Ink design, PR #66)
- **Deploy**: FastAPI su Fly.io, auto-deploy da `main`, ~2–3 min
- **PR aperta (pronta per merge)**: PR #68 (branch sopra, 4 commit oltre main)

---

## Architettura

```
liquidity-analysis-engine/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI app (1635 righe) — tutti gli endpoint
│       ├── models.py            # Pydantic models
│       ├── config.py            # Settings (backtest_candles, ecc.)
│       ├── auth.py              # JWT auth
│       ├── cache.py             # In-memory cache OHLCV
│       ├── analysis/
│       │   ├── strategies.py    # 3 strategie + registry + build_strategy_state
│       │   ├── backtest.py      # run_backtest() — motore backtest
│       │   ├── optimize.py      # optimize_strategy() — random + grid search
│       │   ├── indicators.py    # RSI, MACD, Stoch, BB, ecc.
│       │   ├── smc_engine.py    # SMC: OB, FVG, BOS/CHoCH, EQL
│       │   ├── confluence.py    # Zone di confluenza
│       │   ├── fibonacci.py     # Auto-Fibonacci
│       │   └── summary.py       # Analisi testuale AI-style
│       ├── providers/           # MEXC, Yahoo, TwelveData (OHLCV fetchers)
│       ├── live/                # WebSocket stream MEXC real-time
│       ├── sniper/              # Token sniper su DexScreener
│       ├── trading/             # Order executor (MEXC API)
│       └── notify/              # Telegram notifications
└── frontend/
    ├── index.html               # SPA principale (691 righe)
    ├── static/
    │   ├── app.js               # Frontend IIFE (4644 righe)
    │   └── style.css            # CSS Minimal Ink (3025 righe)
    └── sniper.html              # UI dedicata token sniper
```

---

## API Endpoints Chiave

| Endpoint | Descrizione |
|---|---|
| `GET /api/analyze` | OHLCV + SMC layers + strategia + backtest multi-TF |
| `GET /api/backtest/deep` | Backtest long-history su intervallo derivato |
| `GET /api/optimize` | Ottimizzazione parametri (random o grid search) |
| `GET /api/strategies` | Lista strategie disponibili |
| `GET /api/symbols` | Autocomplete ticker |
| `POST /api/pinescript` | Salva script Pine personalizzato |
| `POST /api/pinescript/{id}/run` | Esegui script Pine → segnali |
| `GET /api/watchlist` | Watchlist utente |
| `GET /api/favorites/quotes` | Quote real-time per favoriti |
| `GET /api/sniper/candidates` | Token sniper — candidati filtrati |
| `POST /api/sniper/scan` | Avvia scan DexScreener |
| `WebSocket /api/sniper/scan-stream` | Stream live scan progress |

---

## 3 Strategie

| Nome | Funzione | Default Params |
|---|---|---|
| `Lorenzo (trend-follower)` | `compute_signals()` | `DEFAULT_PARAMS` (EMA/SMA slope, trend filter, vol filter) |
| `Accumulo / Distribuzione (long-term)` | `compute_exhaustion_signals()` | `EXHAUSTION_DEFAULT_PARAMS` (RSI divergence, contraction, range bounce) |
| `Gabriele (RSI+BB reversal)` | `compute_lki_signals()` | `LKI_DEFAULT_PARAMS` (RSI + Bollinger Bands) |

---

## Ottimizzatore (`analysis/optimize.py`)

- **Random search**: 200 trial, seed opzionale, funziona per tutte e 3 le strategie
- **Grid search** (nuovo, branch corrente):
  - `Gabriele`: griglia 5×5×5×5×5 = 3125 combinazioni
  - `Accumulo`: griglia 3^5×2^3 = 1944 combinazioni
  - `Lorenzo`: fallback a random (troppi parametri)
- **Walk-forward**: 70% in-sample → ottimizza, 30% out-of-sample → valida
- **Scoring**: Calmar ratio × profit factor bonus × trade confidence
- **Filtri**: min 8 trade, max drawdown 35%, return > 0
- **Overfitting flag**: degradazione OOS > 50% relativa

---

## Modello Pydantic chiave

```python
class OptimizeResult(BaseModel):
    params: dict
    backtest: BacktestResult
    trials_evaluated: int
    out_of_sample_return_pct: float | None = None
    overfitted: bool = False
    mode: str = "random"  # "random" | "grid"

class BacktestResult(BaseModel):
    num_trades: int
    win_rate: float
    profit_factor: float | None
    total_return_pct: float
    max_drawdown_pct: float
    avg_trade_duration_bars: float | None
    interval: str
    # ... altri campi
```

---

## Frontend (`app.js`) — Funzioni Principali

| Funzione | Scopo |
|---|---|
| `analyzeSymbol()` | Chiama `/api/analyze`, popola grafico + livelli |
| `renderChart(data)` | TradingView Lightweight Charts v4 — candele |
| `renderSubCharts()` | RSI / MACD / Stoch in sub-chart separati |
| `resizeAllCharts()` | Ridimensiona tutti i chart (chiamata in RAF dopo toggle) |
| `runLabOptimize()` | Chiama `/api/optimize`, mostra risultati nel Lab |
| `renderLabParamFields()` | Genera UI parametri nel Lab per strategia corrente |
| `updateMobileChartStrip()` | Aggiorna pill strategia + info nella strip mobile |
| `bindMobileNav()` | Gestisce navigazione mobile (tab: chart/levels/lab) |
| `showMobileScreen(name)` | Switcha tra schermate mobile |

**Pattern critico**: `COLORS_DARK` / `COLORS_LIGHT` selezionati a module-init via `window.matchMedia`.

---

## CSS (`style.css`) — Struttura

- **Tema**: Minimal Ink — bianco/nero, font Inter + JetBrains Mono
- **Layout desktop**: `.cockpit` (flex-row) → `.rail` (46px) + `.levels-panel` (drawer) + `.chart-area` (flex:1)
- **Layout mobile**: `.mobile-chart-strip` + tab navigation + `.mobile-screen-*`
- **Componenti chiave**: `.toolbar`, `.rail-btn`, `.layer-toggle`, `.lab-*`, `.mobile-strategy-pill`
- **Dark mode**: `@media (prefers-color-scheme: dark)` + `[data-theme]` su `:root`

---

## Bug Risolti (questa sessione)

| Bug | Causa | Fix |
|---|---|---|
| Trade 2018 non visibili sul chart | `_MAX_ALERTS_RETURNED = 30` tagliava segnali storici | Portato a 500 |
| Sub-chart RSI/MACD/Stoch non si ridimensionavano dopo toggle | `ResizeObserver` async dopo `display:none→visible` | `requestAnimationFrame(() => resizeAllCharts())` nel checkbox handler |
| Candles appuntite (high/low estremi) | Bug nel mapping OHLCV — già fixato in commit precedente | Fix nel commit `aaa48f2` |
| Colori segnali Gabriele/Lorenzo non sincronizzati | Preso colore sbagliato per strategia attiva | Fix in `aaa48f2` |

---

## Funzionalità Completate

- [x] **3 strategie** con backtest, ottimizzazione e walk-forward validation
- [x] **SMC layers**: Order Blocks, FVG, Equal H/L, BOS/CHoCH, Confluenza, Fibonacci
- [x] **Indicatori sub-chart**: RSI, MACD, Stocastico (chart separati con resize fix)
- [x] **Lab ottimizzazione**: UI con param fields per strategia, random search
- [x] **Grid search**: implementato e pushato (branch corrente, in PR #68)
- [x] **Grid mode toggle**: checkbox nel Lab, visibile solo per strategie compatibili
- [x] **Mobile strategy pill**: pill nel chart strip mobile, tap → apre pannello Livelli
- [x] **Design Minimal Ink**: tema bianco/nero, font Inter + JetBrains Mono
- [x] **Token Sniper** (`sniper.html`): scan DexScreener, scoring, import watchlist
- [x] **Watchlist + Favoriti**: CRUD, quote real-time, on_close alerts
- [x] **Auth JWT**: register/login/logout, profilo utente
- [x] **Trading executor**: place_order via MEXC API
- [x] **Telegram notify**: notifiche segnali su canale Telegram
- [x] **Pine Script custom**: salva/esegui script personalizzati, segnali su chart
- [x] **Multi-timeframe backtest**: backtest su TF derivato + confluenza HTF

---

## Attività Aperte

### Immediate (pronto per essere fatto)
- [ ] **Merge PR #68** — contiene tutti i fix + grid search + mobile pill
- [ ] **Desktop redesign** — scegliere una delle 10 proposte (artifact generato ma non ancora pubblicato in questo session — file in scratchpad: `design-proposals.html`)
- [ ] **Implementare il layout mobile scelto** — proposta da selezionare e codificare

### Feature backlog
- [ ] **Mobile layout** — UI mobile più consultabile (proposte generate: 10 concept)
- [ ] **Prompt consultation mobile** — documento brief per UX mobile
- [ ] **Grid search progress bar** — mostrare avanzamento durante grid search (~40s)
- [ ] **Salva parametri ottimizzati** — applica best params alla strategia in watchlist
- [ ] **Confronto A/B strategie** — visualizza due strategie sullo stesso chart
- [ ] **Export backtest** — CSV dei trade, equity curve scaricabile

### Tecnico
- [ ] **Test suite** — nessun test automatico presente al momento
- [ ] **Rate limiting** per `/api/optimize` (grid search è CPU-heavy ~40s)

---

## Decisioni Tecniche

| Decisione | Scelta | Motivazione |
|---|---|---|
| Frontend framework | Vanilla JS (IIFE) | Zero build step, deploy istantaneo |
| Charting | TradingView Lightweight Charts v4 | Performance, API semplice |
| Grid search | `itertools.product` su spazi discreti | Tracciabile, riproducibile, ~1000-3000 combinazioni |
| Backtest interval | Derivato da LTF: 1H→1D, 4H→1W, 1D→1M | Più storia = più significatività statistica |
| Auth | JWT + SQLite locale | Nessun servizio esterno, self-hosted |
| Cache OHLCV | In-memory dict con TTL | Evita re-fetch tra optimize/analyze sullo stesso ticker |
| Scoring optimizer | Calmar ratio × PF bonus × trade confidence | Premia return/drawdown, non solo PF su pochi trade |

---

## Variabili Critiche

```python
# backend/app/analysis/strategies.py
_MAX_ALERTS_RETURNED = 500  # era 30 — non abbassare

# backend/app/analysis/optimize.py
_TRIALS = 200          # random search trials
_MIN_TRADES = 8        # min trade per essere qualificato
_MAX_DRAWDOWN_PCT = 35.0  # hard cap drawdown
```

```javascript
// frontend/static/app.js
const GRID_STRATEGIES = new Set([
  "Gabriele (RSI+BB reversal)",
  "Accumulo / Distribuzione (long-term)",
]);
// COLORS_DARK / COLORS_LIGHT — selezionati a module-init, NON in runtime
```

---

## Note per la Prossima Sessione

1. **PR #68** è pronta — ha 4 commit oltre `main`, merge diretto senza conflitti.
2. **Design proposals artifact** (`design-proposals.html`) è nel scratchpad della sessione corrente ma NON ancora pubblicato. Nella nuova sessione: leggere il file e pubblicarlo come Artifact, poi scegliere un design da implementare.
3. Il file di design è a: `/tmp/claude-0/-home-user-liquidity-analysis-engine/864e68f5-2bb9-5c11-b50f-c2ec9f858450/scratchpad/design-proposals.html` — ma questo path è specifico della sessione e potrebbe non esistere. Rigenerare l'artifact se necessario.
4. Per il grid search è già tutto implementato e pushato — nessuna azione tecnica residua.
