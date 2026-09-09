# Memoria di sessione

**A cosa serve questo file**: se apri una chat nuova con Claude su questo
repo, fagli leggere questo file (o linkalo — è il primo posto dove cercare
"da dove eravamo rimasti"). Claude lo aggiorna dopo ogni lavoro non banale,
cosi' che una conversazione diversa sappia esattamente lo stato delle cose
senza dover rileggere l'intera cronologia della chat precedente.

Per le segnalazioni puntuali (bug, richieste) la fonte di verita' resta la
bacheca (`/api/issues`, vedi `CLAUDE.md`) — questo file e' per il resto:
lavori pluri-sessione, decisioni prese, stato di piani approvati.

---

## Stato del repo

- **Repo**: `lorenzocorazzi-wq/liquidity-analysis-engine`
- **Branch di lavoro**: `claude/interface-design-m6q27s`
- **Deploy**: FastAPI su Fly.io, auto-deploy da `main` (~2-3 min) — **non**
  dal branch di lavoro, che va unito a `main` perche' vada in produzione
- **Auth**: cookie firmato (non JWT — vedi `backend/app/auth.py`), PBKDF2 per
  le password

## Architettura

```
backend/app/
├── main.py                    # FastAPI — tutti gli endpoint
├── models.py                  # Pydantic models (incluso MAX_FUTURES_LEVERAGE)
├── auth.py                    # cookie auth, credenziali cifrate (spot + futures)
├── issues.py                  # bacheca segnalazioni (_SEED + merge col volume Fly)
├── trading_log.py             # diario ordini (spot e futures)
├── watchlist.py, archive.py, price_alerts.py, favorites.py, jobs.py
├── analysis/
│   ├── strategies.py          # le 3 strategie + registry
│   ├── backtest.py            # motore backtest spot
│   ├── futures_backtest.py    # motore backtest futures (leva/margine/liquidazione/funding)
│   ├── futures_math.py        # formula di liquidazione condivisa
│   ├── optimize.py, pipeline.py, plateau.py   # ottimizzazione e ricerca stabile
│   ├── smc_engine.py, confluence.py, fibonacci.py, indicators.py, summary.py
├── providers/                 # mexc, binance, kucoin, twelvedata (dati OHLCV)
├── trading/
│   ├── executor.py            # dispatch spot (place_order_for_signal) e futures (place_futures_order_for_signal)
│   ├── binance_exec.py, kucoin_exec.py, kraken_exec.py, coinbase_exec.py, bitstamp_exec.py  # spot
│   └── binance_futures_exec.py                # futures — solo Binance per ora
├── pine/                      # interprete Pine Script custom
├── sniper/                    # token sniper DexScreener
├── live/                      # WebSocket stream MEXC
└── notify/                    # Telegram

frontend/
├── index.html
└── static/{app.js, style.css}
```

Le tre strategie e le cose misurate/pericolose sono in `CLAUDE.md`, non
ripetute qui apposta — un solo posto da tenere aggiornato.

## Workflow di lavoro (come procede Claude qui)

1. Bacheca prima di tutto (`CLAUDE.md`).
2. Ogni fix/feature discusso in chat finisce anche in `_SEED` +
   `resolutions.json`, non solo nella conversazione.
3. Verifiche prima di ogni commit: `pytest`, `ruff`, `node --check` (comandi
   esatti in `CLAUDE.md`).
4. Commit e push sul branch di lavoro sopra — mai forzati, mai su `main`
   senza che sia esplicitamente chiesto.
5. Questo file (`HANDOVER.md`) si aggiorna dopo lavori pluri-sessione o
   decisioni rilevanti, cosi' che una chat diversa possa riprendere.

---

## Filoni di lavoro aperti (pluri-sessione)

### Operazioni futures — `seed-0027` — **in corso**

Piano completo approvato e scritto (era in
`/root/.claude/plans/warm-floating-quasar.md`, locale alla sessione che l'ha
scritto — **non versionato**, quindi il piano vero e proprio non e'
recuperabile da una chat diversa: quello che segue e' il riassunto che conta).

Principio guida: leva e margine sono l'estensione piu' pericolosa possibile
per questo sistema — isolamento totale dal codice spot, mai una modifica
in-place a un modulo spot esistente, sempre un modulo nuovo affiancato.

**Fatto** (fasi 0-4 del piano, solo Binance):
- Modello dati additivo: `FuturesCredential` (separato da
  `ExchangeCredential`), `MAX_FUTURES_LEVERAGE` come tetto lato server,
  campi opzionali su `BacktestTrade`/`BacktestResult` (nessun trade spot
  esistente cambia).
- `futures_backtest.py`: leva, margine isolated, liquidazione intrabar con
  la stessa precedenza dello stop/target esistente, funding ogni 8h.
- `binance_futures_exec.py`: `/fapi/v1/...`, isolated+leva dichiarate prima
  di ogni ordine, margine letto per davvero dall'exchange, chiusura solo
  con ordini `reduceOnly`.
- `executor.py`: `place_futures_order_for_signal()` separata dallo spot —
  qui `exit_short` ricompra (short vero, non un noop come nello spot), un
  flip chiude prima di riaprire.
- Guardrail lato server: cap di leva applicato al salvataggio credenziali E
  a ogni ordine, `/api/trading/futures/order` rifiuta senza `confirm:true`,
  kill switch (`FuturesCredential.enabled`) blocca anche a conferma data,
  controllo margine pre-trade contro il saldo vero, `/api/trading/futures/quote`
  per l'anteprima (margine, notional, liquidazione stimata).
- 24 test nuovi (`test_futures_backtest.py`, `test_binance_futures_exec.py`,
  `test_futures_trading_api.py`), tutti su trasporti finti — nessuno puo'
  spendere margine vero. Suite completa verde (388+), nessuna regressione.

**Da fare, in quest'ordine**:
1. **Verifica manuale in Binance Futures testnet** — richiede chiavi API
   testnet vere di Lorenzo. Bloccante prima di considerare l'esecuzione
   reale pronta: nessun ordine e' mai stato mandato a un server Binance
   vero, solo a trasporti finti nei test.
2. **Frontend**: form leva/margine, mostrare l'anteprima di
   `/api/trading/futures/quote` prima della conferma, avviso di
   liquidazione stimata sul grafico. Deliberatamente non ancora fatto: si
   disegna solo dopo che il motore e' verificato (punto 1).
3. **MEXC futures**, poi **KuCoin futures** — solo dopo che Binance e'
   stabile in produzione da tempo. Kraken/Coinbase/Bitstamp futures restano
   fuori perimetro (disponibilita'/complessita' non giustificano il rischio
   ora).

File coinvolti: `backend/app/models.py`, `backend/app/analysis/futures_backtest.py`,
`backend/app/analysis/futures_math.py`, `backend/app/trading/binance_futures_exec.py`,
`backend/app/trading/executor.py`, `backend/app/auth.py`, `backend/app/main.py`,
i tre file di test sopra, `backend/app/issues.py`, `backend/app/data/resolutions.json`.

---

## Log delle conversazioni

Ordine cronologico, piu' recenti in fondo. Scritto perche' una chat diversa
possa capire non solo *cosa* e' cambiato ma *perche'* e cosa Lorenzo ha
chiesto con le sue parole.

- **Ricerca stabile, animazione live** (`seed-0026`): Lorenzo ha chiesto una
  visualizzazione stilizzata di cosa fa la ricerca stabile mentre gira.
  Quattro round di feedback dal vivo — "quei blocchi neri sono proprio
  brutti" (tema chiaro rotto), "rimane fermo qui" (due volte, due fasi
  diverse: ricerca dei confini per asse, poi apertura delle celle — in
  entrambi i casi il log taceva per troppo tempo su una fase pesante),
  "rendi piu' moderno e animato... un'animazione che dia la sensazione di
  visualizzare cosa fa davvero l'algoritmo". Risolto con un canvas che legge
  le stesse righe di log gia' scritte dal backend (nessun canale nuovo),
  animato con `requestAnimationFrame`, tema-consapevole. Dettaglio completo
  in `resolutions.json` sotto `seed-0026`.
- **Operazioni futures** (`seed-0027`): "vorrei introdurre le operazioni
  futures. crea un sistema completo e accurato e soprattutto a prova di
  errore, crea un piano completo per crearlo" → piano scritto e approvato
  → "procedi" due volte, prima per le fasi 0-2 (motore di backtest a leva),
  poi per le fasi 3-4 (esecuzione reale Binance + guardrail). Vedi la
  sezione sopra per lo stato dettagliato.
- **Questo file**: Lorenzo ha chiesto che ogni conversazione lasci memoria
  in GitHub, cosi' una chat diversa sappia da dove riprendere senza dover
  rileggere tutto. Riscritto `HANDOVER.md` (era rimasto fermo a una
  sessione molto piu' vecchia — auth JWT, PR #68, nessuna delle strutture
  attuali) e aggiunta la sua lettura al workflow obbligatorio in
  `CLAUDE.md`.
