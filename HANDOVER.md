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
│   ├── binance_futures_exec.py                # implementazione Binance futures (avvolta da futures/binance.py)
│   └── futures/                # un adattatore per exchange, dietro un'interfaccia comune
│       ├── base.py             # FuturesAdapter (interfaccia), Position, FuturesCreds
│       ├── registry.py         # unico posto che decide quali exchange esistono — perimetro UE qui
│       ├── binance.py, bybit.py, okx.py, bitget.py, kraken.py
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

### Modalita' semplificata — **da iniziare, non ancora pianificata**

Lorenzo, con le sue parole: «voglio anche che ci sia una modalita'
semplificata, sia del sito web che dell'applicazione [...] una persona
possa con un grafico [...] scegliere la strategia piu' adeguata,
visualizzare gli ingressi e le uscite in modo chiaro, con un backtest
magari che appare [...] in un click impostare [...] con una modalita'
guidata le API per l'exchange [...] arrivare al punto in cui uno puo' con
pochi passaggi abilitare l'allarme alle operazioni in automatico per quella
determinata strategia [...] un bottone che uno preme e il sito entra in
modalita' semplificata sia su telefono che sul sito web [...] Voglio un UI
estremamente semplificata, pero' non per questo povera di dettagli
grafici [...] bella».

Flusso richiesto, in ordine: grafico ben visibile → scegliere la strategia
→ vedere ingressi/uscite chiari sul grafico → backtest che appare
→ wizard guidato per le API dell'exchange → un click per abilitare
alert+esecuzione automatica di quella strategia su quel ticker. Un
interruttore ("modalita' semplificata") accende questo percorso al posto
dell'interfaccia normale, su desktop e mobile.

Non ancora iniziato: nessun prototipo, nessuna decisione su come convive
con l'interfaccia esistente (schermata separata? overlay sopra Analizza?).
Stesso metodo usato per il restyling (`seed-0028` sotto) va seguito anche
qui: prima un Artifact di riferimento da fare approvare, poi implementare
nel codice vero — non saltare il passaggio anche se la richiesta e' gia'
molto dettagliata.

---

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

Piano originale (fasi 0-4, solo Binance) approvato e scritto in una sessione
precedente — vedi sotto per dov'e' finito. Principio guida invariato: leva e
margine sono l'estensione piu' pericolosa possibile per questo sistema —
isolamento totale dal codice spot, mai una modifica in-place a un modulo
spot esistente, sempre un modulo nuovo affiancato.

**Cambio di perimetro (questa sessione)**: Lorenzo ha chiesto futures per
"tutti gli exchange dove si puo' operare in leva in Europa", non solo
MEXC/KuCoin come previsto dal piano originale. MiCA/ESMA limitano i derivati
al retail UE, e non tutti gli exchange gia' collegati per lo spot li offrono
li': **Coinbase e Bitstamp restano fuori** (niente derivati a leva per il
retail UE), **MEXC e KuCoin restano fuori** (hanno i futures ma non la
licenza UE), aggiunti invece **Bybit, OKX, Bitget, Kraken** — tutti con
licenza per offrire derivati a leva in Europa, insieme a Binance che c'era
gia'. Deciso senza chiedere conferma esplicita nel corso della sessione:
Lorenzo ha detto "procedi" dopo aver visto il perimetro proposto.

**Fatto**:
- Fasi 0-4 del piano originale, solo Binance (sessione precedente): modello
  dati (`FuturesCredential`, `MAX_FUTURES_LEVERAGE`), `futures_backtest.py`
  (leva/margine isolated/liquidazione intrabar/funding), `binance_futures_exec.py`
  (`/fapi/v1/...`), guardrail lato server (cap di leva, `confirm:true`
  obbligatorio, kill switch, controllo margine pre-trade), endpoint
  `/api/trading/futures/quote` per l'anteprima.
- **Multi-exchange (questa sessione)**: `app/trading/futures/` — pacchetto
  nuovo con un'interfaccia comune (`base.py`, classe `FuturesAdapter`, sei
  metodi) e un registro (`registry.py`) che e' l'unico posto che decide
  quali exchange esistono. `binance.py` avvolge il modulo esistente senza
  riscriverlo (zero rischio su cio' che gia' funzionava); `bybit.py`,
  `okx.py`, `bitget.py`, `kraken.py` sono adattatori nuovi, ciascuno con le
  sue trappole documentate nel proprio file (firma diversa, quantita' in
  contratti vs monete su OKX, Kraken senza isolated margin). `executor.py` e
  `main.py` non nominano piu' un exchange specifico: chiedono l'adattatore
  al registro. Frontend: select exchange, tetto di leva e avviso
  isolated/condiviso pilotati da `/api/auth/futures` (non piu' scritti a
  mano nell'HTML), piu' la UI di configurazione credenziali per i quattro
  exchange nuovi (prima non esisteva — solo il form d'ordine c'era).
  Dettaglio tecnico completo in `resolutions.json` sotto `seed-0027`.
- Fix nello stesso giro: la sezione **Livelli & Indicatori** era diventata
  irraggiungibile su desktop dopo il ridisegno `seed-0028` (il rail che la
  apriva e' nascosto, e nessuna voce della sidebar la sostituiva) —
  segnalazione `e599667e`, ora una voce sidebar propria. Vedi
  `resolutions.json`.

**Da fare, in quest'ordine**:
1. **Verifica manuale in testnet (o importi minimi) su ciascun exchange** —
   richiede chiavi API vere, anche solo di test. Bloccante prima di fidarsi
   dell'esecuzione reale: nessun ordine e' mai stato mandato a un server
   vero su nessuno dei cinque, solo a trasporti finti nei test.
2. **Non verificato in questa sessione**: niente ambiente Python 3.12
   disponibile sulla macchina per lanciare `pytest`/`ruff` per davvero — solo
   controllo sintattico (`py_compile`) e revisione a mano. Da lanciare la
   suite completa alla prima occasione con l'ambiente giusto.
3. MEXC e KuCoin restano fuori per perimetro normativo, non per limite
   tecnico: il registro accoglie un nuovo adattatore con un file piu' una
   riga in `registry.py`, se la decisione cambiasse.

File coinvolti: vedi l'elenco completo in `resolutions.json` sotto `seed-0027`
(troppo lungo per ripeterlo qui — include tutto `app/trading/futures/`,
`executor.py`, `main.py`, `auth.py`, i tre file frontend, i test).

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
- **Futures multi-exchange** (`seed-0027`, continuazione): "i futures devono
  essere realizzati non per binance, ma per tutti gli exchange dove si puo'
  effettuare operazioni in leva in europa, procedi" — segnalato che
  MiCA/ESMA limitano i derivati al retail UE e che non tutti gli exchange
  gia' collegati li offrono li' (Coinbase/Bitstamp niente derivati UE,
  MEXC/KuCoin hanno i futures ma non la licenza UE), poi proceduto con
  Bybit/OKX/Bitget/Kraken accanto a Binance. Nello stesso giro, chiesto
  anche di guardare i punti aperti in bacheca: trovato e risolto
  `e599667e` (Livelli & Indicatori irraggiungibile dopo il ridisegno). Poi
  chiesto di strutturare la repo perche' una chat diversa non debba
  rileggere tutto — risposta: questo file esisteva gia' per quello, qui
  aggiornato con lo stato del lavoro invece di ricostruito da zero. Ambiente
  locale senza Python 3.12: verificata solo la sintassi
  (`py_compile`), non lanciata la suite pytest/ruff — segnalato sopra come
  da fare.
