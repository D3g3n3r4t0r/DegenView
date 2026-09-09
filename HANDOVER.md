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

### Ridisegno dell'interfaccia — `seed-0028` — **in corso**

Lorenzo: «voglio un overhaul generale del design di tutto il sito visto le
tante funzioni implementate serve occhio globale che inserisca ogni funzione
in modo moderno e visualizzato in modo efficace», poi «DEVI METTERE IN
DISCUSSIONE OGNI COSA», poi «voglio TUTTO UGUALE» rispetto al prototipo
navigabile che aveva approvato.

Principio: l'architettura si nomina per **intento**, non per oggetto. Le tab
erano nominate per oggetto e quella Alert era diventata una discarica di
sette funzioni, con dentro un ordine a denaro reale.

**Fatto**:
- Sistema di design «Instrument»: fondo nero-freddo con tinta verde, accento
  menta speso con parsimonia, colore semantico separato dall'accento, numeri
  hero in Instrument Serif (mai in colonna: non ha cifre tabellari).
- Una sola navigazione (sidebar) al posto di tre sovrapposte (rail + tab +
  menu Altro). Pilota il meccanismo delle tab esistente invece di duplicarlo,
  quindi resta un solo posto che decide quale contenuto e' vivo. Rail, tab e
  Altro restano nel DOM perche' `app.js` ci si aggancia.
- Aree: Analizza / Lab / Sorveglia / **Opera** / Scopri. Il trading e' uscito
  dalla tab Alert. Il Lab e' a due colonne a tutta larghezza.
- Il grafico non sparisce mai: largo in Analizza, a colonna altrove, fascia
  bassa sotto i 1250px.
- UI futures completa (era il punto 2 del piano `seed-0027`): leva a cursore,
  anteprima obbligatoria da `/api/trading/futures/quote`, conferma esplicita
  che nomina leva e prezzo di liquidazione. Ogni modifica invalida la
  conferma e azzera l'anteprima. Tetto UI allineato a `MAX_FUTURES_LEVERAGE`
  (10, non 20).
- Endpoint `GET /api/trading/futures/positions` (sola lettura, non tocca
  l'executor) + posizioni con la distanza dalla liquidazione disegnata come
  lancetta su nastro.
- Mappa dei candidati nel Lab: i dieci `top_candidates` che il backend
  restituiva da sempre e che nessuna schermata aveva mai mostrato.

**Da fare**:
1. **Riportare il Token Sniper dentro l'app.** E' ancora `sniper.html`, una
   pagina a se' con tema e font suoi. E' il pezzo piu' grosso che manca per
   dire che il ridisegno e' finito.
2. Sorveglia a tre colonne come nel prototipo (watchlist con sparkline,
   alert attivi, storico a timeline).
3. Analizza: striscia di statistiche sotto il grafico e barre di confluenza,
   che nel prototipo c'erano.

Prototipo navigabile di riferimento (Artifact): «Liquidity Instrument».

---

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
2. ~~**Frontend**: form leva/margine, anteprima, avviso di liquidazione.~~
   **Fatto** nel ridisegno (`seed-0028`), area Opera. Nota: e' stato
   disegnato prima della verifica su testnet, non dopo come previsto qui —
   Lorenzo ha scelto di procedere sapendolo. Il punto 1 resta bloccante
   prima di considerare l'esecuzione reale pronta.
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
- **Ridisegno + futures in produzione** (`seed-0028`, `0029`, `0030`):
  Lorenzo ha chiesto prima le proposte di design, poi ha bocciato il primo
  giro («stai facendo della roba di merda... voglio vedere ogni schermata non
  solo graficamente parlando») e ha chiesto un solo prototipo navigabile.
  Approvato quello, «OK PUBBLICA TUTTO»: i futures sono stati uniti a `main`
  e deployati sapendo che la verifica testnet non c'era ancora — scelta sua,
  dichiarata. Poi tre richieste puntuali durante il lavoro: il flag sulla
  candela di esecuzione (`seed-0029`), il grafico sempre visibile in ogni
  schermata, e la tracciatura di ogni operazione sul grafico (`seed-0030`).
  Trovato e corretto lungo la strada: la Bacheca non si apriva dalla sidebar
  (il gestore «click fuori» la richiudeva nello stesso click).
- **Questo file**: Lorenzo ha chiesto che ogni conversazione lasci memoria
  in GitHub, cosi' una chat diversa sappia da dove riprendere senza dover
  rileggere tutto. Riscritto `HANDOVER.md` (era rimasto fermo a una
  sessione molto piu' vecchia — auth JWT, PR #68, nessuna delle strutture
  attuali) e aggiunta la sua lettura al workflow obbligatorio in
  `CLAUDE.md`.
