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
- **Dove gira**: server proprio Hetzner CX23 a Norimberga (2 core, 4 GB,
  6,70 EUR/mese), dominio **liquidityengine.app**. Deploy automatico a ogni
  push su `main`: lint + **test** + deploy (vedi `deploy/README.md`).
  **Fly e' spento** (`flyctl scale count 0`) ma resta come via di ritorno:
  `scale count 1` e si sposta il DNS.
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

### Modalita' semplificata — **implementata, non ancora verificata su backend vero**

Lorenzo, con le sue parole: «voglio anche che ci sia una modalita'
semplificata [...] una persona possa con un grafico [...] scegliere la
strategia piu' adeguata, visualizzare gli ingressi e le uscite in modo
chiaro, con un backtest magari che appare [...] in un click impostare [...]
con una modalita' guidata le API per l'exchange [...] arrivare al punto in
cui uno puo' con pochi passaggi abilitare l'allarme alle operazioni in
automatico [...] Voglio un UI estremamente semplificata, pero' non per
questo povera di dettagli grafici [...] bella». Poi, rivisto un primo
prototipo: «tutte le funzioni di backtesting siano comunque attive anche
nella modalita' semplificata [...] voglio poter comunque ottimizzare la
strategia secondo la logica gia' attuale, con tutte le modalita' di
ottimizzazione che abbiamo [...] sia chiaro quanti minuti restano al
termine». Poi ancora: se un ticker ha gia' strategie approvate in
archivio, mostrarle prima di proporre un nuovo backtest.

Fatta tre giri di prototipo (Artifact, approvati uno alla volta) prima di
toccare il codice — link nel log delle conversazioni sotto. Implementazione
vera in `frontend/static/simple-mode.js` (nuovo file, ~890 righe, CSS
scoped sotto `#simple-mode-root`, zero id/classi di `app.js` toccate) +
4 righe in `index.html` (bottone toggle + contenitore). **Nessun endpoint
backend nuovo**: ogni passo del wizard chiama API gia' esistenti e vere —
`/api/symbols`, `/api/analyze`, `/api/archive` (filtrato client-side per
ticker), `/api/strategies`, `/api/optimize/start` + polling `/api/jobs/{id}`,
`/api/auth/trading`, e per l'attivazione `/api/archive/{id}/apply-to-alert`
(ramo archivio) oppure `POST /api/watchlist` + `PATCH .../strategy_params`
+ `PATCH .../strategy` (ramo nuova strategia) — quest'ultima PATCH e' quella
che fa scattare l'esecuzione automatica reale, tramite lo stesso watcher
in background che gia' esisteva.

Scelte fatte in autonomia durante l'implementazione: solo spot (coerente
con leva 1x server-wide, vedi sotto); exchange nel wizard Binance/KuCoin/
Kraken invece di Binance/Bybit/Kraken del prototipo (il backend supporta
questi tre per lo spot, non Bybit); per i ticker azionari niente step
exchange, l'attivazione diventa solo avviso Telegram (dichiarato in UI,
l'esecuzione automatica esiste solo per crypto spot); countdown
dell'ottimizzazione onesto — stima client-side su `elapsed_s` reale contro
le soglie gia' note (10-25s/1-5min), con "quasi fatto" invece di un
countdown che sbaglia oltre soglia; uscita sempre permessa durante
l'ottimizzazione, il lavoro continua server-side comunque.

Verificato dall'agente contro mock fedeli agli schemi Pydantic reali (il
Python 3.12 non e' disponibile in questo ambiente, niente backend vero da
avviare) — poi ri-verificato da Claude leggendo il diff a mano: ogni
endpoint, payload e campo di risposta citato esiste davvero nel backend
con lo stesso nome (controllato uno per uno prima del merge).

**Da fare**: verifica manuale end-to-end contro il backend vero in
produzione (nessuna sessione ha ancora potuto testarlo con un account e
un'ottimizzazione reali) — bloccante prima di considerarla pronta per
davvero, stessa cautela gia' vista per i futures multi-exchange.

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

### Trasloco da Fly a un server proprio — **fatto**

Il motivo non era la velocita': era che su 512 MB una ricerca aveva gia'
saturato la memoria e ucciso il processo, e un processo morto sono avvisi che
non arrivano. Lorenzo: *"non mi interessa velocizzare la strategia del cazzo,
basta che gestisca gli allarmi e i vari segnali"*.

Misurato prima di decidere (`/api/analyze` BTCUSDT 1d, a caldo): Fly **1,69 s**,
oggi **0,19 s**.

Come e' andata la scelta della macchina: le CX erano esaurite, e la prima
alternativa mostrata dalla console (CPX22, 23,78 EUR) costava tre volte
troppo. L'API di Hetzner ha poi rivelato il **CX23 a 6,70 EUR**, che
l'interfaccia non proponeva. Da qui una regola utile: **per la
disponibilita' e i prezzi chiedere all'API, non leggere la console**.

Due difetti dello script di setup trovati sul campo, entrambi corretti:
`sshd` tiene il **primo** valore che legge e i frammenti si leggono in ordine
alfabetico, quindi il file `99-` non disattivava niente contro il
`50-cloud-init.conf` di Ubuntu (ora e' `00-`); e da Ubuntu 25.10 SSH e'
attivato dal socket, quindi `reload ssh` fallisce e con `set -e` fermava tutto
il resto dello script senza che si notasse.

**Da fare**: la chiave TwelveData non e' stata portata (le azioni sono spente,
vedi sotto). Se un giorno servissero, va rimessa in `deploy/.env`.

### Azioni disattivate — **fatto**

`settings.stocks_enabled = False`. Una voce `BTC/USD` in watchlist, marcata
come azione, mandava avvisi di errore su una chiave TwelveData mancante.
Lorenzo opera solo in USDT/USDC. Spegnendole sparisce anche la dipendenza da
TwelveData, che col suo limite di 7 richieste al minuto era il collo di
bottiglia piu' stretto del prodotto. E' un interruttore, non una rimozione.

---

### Sicurezza del sito pubblico — `seed-0031` — **fatto**

Con `liquidityengine.app` in chiaro su internet, l'audit ha trovato **33
endpoint senza autenticazione**. I due che contano: `/api/optimize`, che
occupa un core per minuti — due richieste anonime bastavano a mettere giu' il
sito su due core e ad affamare il ciclo che manda gli avvisi — e
`DELETE /api/pinescript/{id}`, che cancellava gli script di chiunque.

Chiusi con **un cancello unico** (middleware) invece di 33 firme: un endpoint
nuovo nasce protetto. Il cancello si fa da parte quando `dependency_overrides`
e' popolato, perche' un test che ha iniettato un utente ha gia' dichiarato chi
e'; in produzione quel dizionario resta vuoto.

Aggiunti anche: registrazione ristretta a un elenco, una ricerca pesante per
utente alla volta, CSP e Permissions-Policy, container non-root.

**Trappola da ricordare**: il Caddyfile e' un volume montato, quindi
`docker compose up -d` **non** ricarica Caddy quando cambia. Le intestazioni
nuove sono rimaste ferme in produzione finche' non l'ho riavviato a mano; ora
il workflow fa `restart caddy` a ogni deploy.

---

### Kraken come provider dati spot — fatto

Lorenzo aveva chiesto una ricerca su cosa offrono le API pubbliche Kraken;
proposte 5 opzioni, scelta la piu' semplice: Kraken come quarto exchange
dati (accanto a MEXC/Binance/KuCoin). Implementato in `backend/app/providers/
kraken.py`: OHLC pubblico + ricerca simboli via AssetPairs, BTC->XBT gestito
in automatico. Limite reale e dichiarato: Kraken non pagina all'indietro,
max 720 candele per intervallo. Board: seed-0056, risolto.

### Opera "troppi exchange" / trading automatico poco chiaro — in corso

Lorenzo: «quando faccio ordine su spot o margine vorrei che prima mi
chiedesse il sistema quale exchange» (poi, per il sito desktop non mobile) —
e subito dopo, mentre lavoravo al mockup: «per abilitare automaticamente
una strategia ad eseguire ordini reali non e' molto chiaro attualmente; si
deve partire dalla watchlist? imposta un sistema semplice che interconnetta
tutto invece di visualizzare cento exchange nella tab opera [...] una volta
aggiunto li il ticker; selezionare la strategia; a quel punto dalla
strategia l'opzione di ottenere solo alert o attivare il trading
automatico». Confermato con lui: Opera va sostituita da questo flusso
(non coesistenza), e l'exchange per l'auto-trading e' sempre quello gia'
associato al ticker in watchlist — nessun picker aggiuntivo.

Primo passo fatto: ogni strategia attiva su un ticker in Sorveglia ha ora
un interruttore proprio "Solo alert" / "Trading automatico" (default:
alert), al posto del vecchio interruttore unico per exchange in Opera che
valeva per ogni strategia attiva li' sopra. Backend: `WatchlistEntry.
auto_trade` (dict strategia->bool), endpoint PATCH `/api/watchlist/{id}/
auto_trade`, gate nel loop di alert. Board: seed-0057, **"in corso"
apposta**, non "risolto": manca ancora il pezzo grosso.

**Secondo giro, stessa sessione**: Lorenzo ha ripreso subito dopo,
correggendo — «i futures devono essere agganciati alla watchlist perche'
tutti parte da li', ogni ticker da watchlist deve permettere di diramarsi,
se attivare solo o alert o anche operazioni automatiche, dopodiche'
selezionare la strategia (da archivio)». Fatto: ogni strategia con
"Trading automatico" acceso, se l'exchange del ticker ha un adattatore
futures registrato (Binance, Kraken, MEXC — intersezione fra i provider
dati spot e il registro futures, la stessa di `FUTURES_PAIR_EXCHANGES`),
mostra anche la scelta Spot/Futures; il loop esegue l'ordine futures con
`place_futures_order_for_signal` usando le credenziali futures gia'
configurate in Opera (leva compresa). KuCoin/Bybit/OKX/Bitget non possono
comparire qui: o non hanno adattatore futures o non sono provider dati
spot nostri, quindi non possono essere l'exchange di un ticker in
watchlist.

**Bug trovato e corretto nello stesso giro**: il gate per-strategia
(seed-0057, primo passo) rompeva silenziosamente la Modalita' Semplice —
quel wizard accende l'esecuzione tramite il vecchio meccanismo
(interruttore per-exchange in `owner.trading_credentials`), che il nuovo
`entry.auto_trade[strategy]` di default `False` avrebbe azzerato senza
errori visibili: chi avesse attivato una strategia dal wizard *credendo*
di aver acceso l'esecuzione reale, in realta' avrebbe ricevuto solo alert.
Corretto prima del deploy: `apply-to-alert` accetta ora un body
`{auto_trade: bool}` e il wizard lo manda `true` solo dopo aver
effettivamente collegato un exchange nel suo passo dedicato.

"Selezionare la strategia da archivio" **esiste gia'** in Modalita'
Semplice (`/api/archive/{id}/apply-to-alert`, passo 1.5 del wizard) — non
duplicato nella scheda classica di Sorveglia, che tiene invece la lista
strategie con parametri modificabili a mano (uso diverso, non lo stesso
percorso).

**Terzo giro, stesso filo**: Lorenzo, secco: «opera sparisce». Fatto per
davvero: la tab Opera non esiste piu' (sidenav, tab-bar, menu mobile
"Altro" ripuliti). Il suo contenuto — credenziali exchange (spot e
futures), posizioni aperte, diario ordini, ordine manuale one-off — vive
ora dentro Sorveglia, sotto le strategie della watchlist, come un secondo
blocco della stessa tab invece che una tab a se'. Tecnica usata apposta per
il rischio basso: il div che prima aveva `data-tab-content="opera"` ha
semplicemente cambiato quell'attributo in `"alert"` — restano due `<div>`
fratelli con lo stesso `data-tab-content`, entrambi si accendono insieme
quando si apre Sorveglia. Nessun id toccato (`trading-credentials-list`,
`positions-list`, `journal-list`, `manual-*`, `futures-*`...), quindi zero
righe di logica di rendering/salvataggio/esecuzione in `app.js` riscritte —
solo dove il blocco appare nel DOM e' cambiato. Le regole CSS a colonne
che erano `[data-area="opera"]` sono ora `[data-area="sorveglia"]`.

**Quarto giro — quello che ha risolto davvero**: spostare Opera dentro
Sorveglia non bastava. Lorenzo, guardando uno screenshot: «ma che stai
facendo? sta roba avevo chiesto di eliminarla e di passare tutto da
watchlist» — la griglia con Binance/MEXC/KuCoin/Kraken e una spunta
"Attivo" su ciascuno era rimasta li', solo in un indirizzo diverso: era
quello il "cento exchange" da eliminare, non la tab in se'. Poi, alla
domanda di chiarimento: «ti avevo chiesto che tutto doveva passare da
watchlist, con l'ordine funzionale che ti avevo chiesto» — cioe' l'ordine
gia' dato nel secondo giro (ticker -> alert o anche automatico -> strategia
da archivio), che nel terzo giro non avevo ancora costruito per davvero.

Fatto ora: quella griglia e' un `<details>` chiuso di default in fondo a
Sorveglia (chiavi, posizioni, diario, ordine manuale — stessa
funzionalita', ma non piu' la prima cosa che si vede). Ogni ticker in
watchlist ha un pulsante "+ Attiva strategia da archivio" che apre la
diramazione vera: solo alert o anche operazioni automatiche -> (se
automatiche) spot o futures, solo dove l'exchange ha un adattatore futures
-> la chiave API si chiede in linea, un exchange alla volta, solo se manca
in quel momento -> scelta della strategia fra le voci d'archivio di quel
ticker (stesso `/api/archive/{id}/apply-to-alert` gia' esteso nel giro
precedente). Se l'archivio e' vuoto per quel ticker, il messaggio guida a
usare prima la lista strategie sotto (esistente, coi parametri di default)
e tornare poi qui.

**Lezione per la prossima volta**: uno spostamento fisico di markup non e'
la stessa cosa di risolvere il problema che quel markup rappresentava —
"cento exchange sempre in vista" era la lamentela originale fin dal primo
giro, ed e' sopravvissuta due giri interi sotto un indirizzo diverso prima
che qualcuno (giustamente) se ne accorgesse guardando lo schermo vero.

**Quinto giro — l'indirizzo sbagliato, di nuovo**: il quarto giro aveva
costruito la diramazione giusta (alert/automatico -> spot/futures ->
strategia da archivio) ma dentro la tab **Sorveglia**. Lorenzo, guardando
l'app vera: «si però se clicco sul ticker che ho in watchlist non mi
permette di fare niente». Alla domanda diretta se intendesse la tab
"Watchlist" (lista rapida) o "Sorveglia" (le card con le strategie):
«ti sto dicendo da mezzora che voglio che tutto sia attivato nella
watchlist (lista rapida) tutto deve originarsi da li». Era la tab
sbagliata fin dal quarto giro — la diramazione c'era, ma non dove doveva
essere cliccabile.

Fatto: ogni riga della tab Watchlist (quella con `#favorite-rows`,
backend `FavoriteEntry`/`/api/favorites` — un modello dati diverso da
`WatchlistEntry`/`/api/watchlist` che alimenta Sorveglia, cosa che ha
richiesto un ponte invece di un semplice riuso) ha ora una freccetta
separata dal clic-sulla-riga (che continua a caricare il grafico, comportamento
di sempre). La freccetta apre un pannello con le strategie gia' attive su
quel ticker (se un `WatchlistEntry` corrispondente esiste gia', letto da
`state.alertEntries` — lo stesso dato che gia' pilotava il pallino
"alert attivo") e sempre `buildActivationFlow()`, la stessa funzione del
giro precedente, generica abbastanza da funzionare sia su un
`WatchlistEntry` sia su un `FavoriteEntry` perche' legge solo
symbol/exchange/asset_type. Nessun endpoint nuovo: attivare da qui crea o
riusa il `WatchlistEntry` esattamente come da Sorveglia.

**Lezione, di nuovo**: nell'app ci sono DUE liste che si chiamano
"watchlist" in punti diversi — quella vera in codice (`WatchlistEntry`,
tab UI "Sorveglia") e quella che l'utente chiama cosi' (tab UI
"Watchlist", modello `FavoriteEntry`). Quando Lorenzo dice "watchlist"
intende quello che vede scritto in UI, non il nome della entita' nel
codice — un'ambiguita' che e' costata due giri di lavoro nella direzione
sbagliata. Se emerge di nuovo un'istruzione su "watchlist", verificare
SUBITO quale delle due tab prima di scrivere codice, non dopo.

**Sesto e settimo giro — rifiniture, stessa sera**: provato il flusso dal
vivo, Lorenzo ha chiesto tre correzioni in rapida successione:
1. «quando aggiungo il ticker sulla watchlist pero' poi non mi chiedi
   quale strategia applicarci» — aggiungere un ticker ora apre da solo il
   pannello e salta dritto alla prima domanda (alert/automatico), senza
   dover aprire la riga a mano e cliccare "+ Attiva" in piu'.
2. «perche' nel caso non ci sia in archivio voglio poterla testare
   direttamente in questa tab» — nuovo stepFresh(): se l'archivio e' vuoto
   per quel ticker (o l'utente lo preferisce comunque, link sempre
   presente), si sceglie una strategia con i parametri di default e parte
   da li', stessa sequenza di chiamate gia' usata da Modalita' Semplice per
   il suo ramo "strategia nuova".
3. «quando seleziono la strategia dall'elenco voglio visualizzare i
   dettagli delle strategie che si trovano nell'archivio in modo chiaro
   non soltanto la percentuale.. ma diocane abbiamo i dati.. usali» +
   «e comunque dopo che la seleziono non la memorizza come scelta» — le
   card dell'archivio ora mostrano trade/win rate/drawdown/profit
   factor/Sharpe/intervallo, non solo il rendimento. E trovata la causa
   piu' probabile del secondo problema: il click ignorava una risposta di
   errore del server trattandola come successo (fetch non rifiuta la
   promise sui codici 4xx/5xx, solo su errori di rete veri) — ora ogni
   card ha un pulsante "Usa questa" con uno stato proprio che mostra
   l'errore reale se il server rifiuta, invece di ricaricare in silenzio
   come se fosse andato tutto bene.

**Ottavo giro — Kraken: dati mensili e feed live**: dopo aver corretto il
flusso di attivazione, due segnalazioni puntuali su Kraken, sempre nella
stessa serata:
- «ma dio cane ti avevo chiesto di implementare tutto da kraken.. usare
  tutte le sue API» — Kraken era rimasto REST-only (60s di polling, come
  Binance/KuCoin), mentre MEXC ha un feed live via websocket. Aggiunto
  `backend/app/live/kraken_stream.py`, che collega il feed pubblico OHLC
  v2 di Kraken (`wss://ws.kraken.com/v2`, JSON — piu' semplice del
  protobuf di MEXC), con la stessa architettura di `mexc_stream.py` (un
  manager, un websocket a monte per (simbolo, intervalli) attivo). Il
  simbolo per il feed v2 non e' quello REST (vuole "BTC/USD" con slash,
  non "XBTUSD") — nuovo `KrakenProvider.get_ws_symbol()` che lo ricava
  dalla stessa lista AssetPairs gia' usata per la ricerca. `/ws/live` ora
  prende un parametro `exchange` e sceglie il manager giusto.
- Trovato scrivendo il test per `get_ws_symbol`: `"XXBT".lstrip("XZ")`
  toglie TUTTE le X/Z iniziali, non solo una — un base a 4 lettere come
  "XXBT" (bitcoin) diventava "BT" invece di "XBT". Bug vero, presente fin
  dal primo giro Kraken (seed-0056), mai notato perche' nessun test
  controllava il valore esatto del base, solo che l'exchange contenesse
  "USD". Corretto estraendo `_strip_kraken_prefix()`, riusata sia dal
  nuovo codice sia da `search_symbols()`.
- Prima ancora, un'altra segnalazione Kraken nello stesso filo: «se
  seleziono 1d voglio 1d» dopo un errore "Timeframe 1M non supportato".
  Non era un bug del selettore — scegliere 1d come intervallo principale
  deriva automaticamente un HTF di 1M per il contesto di lungo periodo
  (comportamento esistente, uguale su tutti gli exchange), e Kraken non ha
  un intervallo mensile nativo. Corretto sintetizzando 1M da 30 candele
  giornaliere (`resample_by_count`), stesso meccanismo gia' usato per
  2D/3D/5D. Lorenzo ha poi chiesto separatamente di eliminare ogni traccia
  dei vecchi tasti HTF/MTF/LTF (sostituiti dal menu a tendina) — trovata e
  rimossa `TF_LABELS`, una costante morta mai referenziata, unico residuo
  rimasto in `app.js`.

Non ancora fatto, per scelta (segnalato, non dimenticato):
- l'ordine manuale one-off dentro il pannello richiudibile (avanzate, in
  fondo a Sorveglia) resta un form con la sua scelta exchange, non una
  card per-ticker — rimandato perche' tocca molto piu' codice per un
  guadagno cosmetico, e nessuno l'ha chiesto esplicitamente;
- nessuna verifica dal vivo con chiavi vere dell'esecuzione futures
  automatica da watchlist (stessa cautela gia' segnata sotto "Operazioni
  futures" — nessun ordine futures e' mai partito verso un server vero);
- il feed live Kraken non e' stato verificato con una sessione reale nel
  browser (solo test unitari con trasporto finto, come tutto il resto di
  questo provider) — se il canale "ohlc" v2 si comporta diversamente da
  come documentato, va vista dal vivo.

---

### Layout: il grafico "si sposta" cambiando tab — `seed-0060` — **in corso, riaperto**

Lorenzo, subito dopo il giro Kraken: «il passaggio dalle varie tab
"analizza" "livelli" "lab" e "watchlist" e sorveglia, deve dare l'effetto
che il grafico non si sposti mai, ma che si adeguino le interfacce
lateralmente non modificando la posizione del grafico... sennò il layout
si scompiglia sempre».

**Primo tentativo (sbagliato, rivertito nello stesso giro)**: `.chart-area`
aveva due comportamenti opposti — in Analizza `flex:1 1 auto` (tutto lo
spazio libero, pannello fisso a 320px), altrove `flex:0 0
clamp(300px,32%,520px)` (larghezza fissa, pannello che assorbe il resto).
Ho reso `.chart-area` sempre alla larghezza fissa stretta, in ogni area.
Risultato: il salto fra tab e' sparito, ma il grafico in Analizza — lo
schermo dedicato a guardarlo — e' diventato piccolo. Screenshot del Lab
alla mano, Lorenzo: «si ma ora il grafico ha poco spazio; sei cosi
stupido?», poi «il sito usa malissimo gli spazi.. fa schifo», poi «il
layout di tutte le tab fa cacare, il passaggio da ogni tab ancora peggio.
fai studiare il layout ad un team di esperti e usa tutte le skill di
design che ti avevo dato per ottimizzare lo spazio nel migliore dei modi».
Rivertito subito (`git revert`) — il grafico e' tornato come prima di
questo giro: grande in Analizza, stretto altrove.

**La tensione di fondo, non ancora risolta**: Analizza e' uno schermo
*guarda il grafico* (chart grande, pannello di lettura stretto); Lab e
Sorveglia sono schermi *lavora sul form* (form/griglia larghi, chart di
riferimento stretto). Dare a `.chart-area` UNA sola larghezza fissa serve
bene uno dei due bisogni e male l'altro, in entrambe le direzioni. Il vero
problema che Lorenzo segnala nel Lab — la fetta destra vuota finche' non
c'e' un risultato di backtest, dentro `.lab-panel { grid-template-columns:
minmax(280px,380px) 1fr }` — e' un difetto di quello schermo specifico
(un placeholder/empty-state che manca), non necessariamente qualcosa che
una larghezza-fissa del grafico risolverebbe.

**Chiuso cosi'**: fatto il mockup (Artifact, link sotto) e sottoposto a tre
revisori indipendenti su richiesta esplicita di Lorenzo ("sottoponi questo
studio ad un team di agent esperti; usa le skill che ti ho installato
anche") — un Agent per il layout/gerarchia (`ui-design-principles` +
`component-gallery`), uno per l'accessibilita' (`wcag-2.2`), uno per
l'animazione (`transitions-dev` + `transitions-polish`), ciascuno con
istruzione esplicita di caricare la propria skill prima di giudicare e di
non modificare nessun file.

Verdetto: il modello a due famiglie (Analizza grafico grande/pannello
stretto; Lab-Watchlist-Sorveglia grafico stretto/pannello largo) era
*gia'* quello vero nel codice — non andava unificato, il primo tentativo
di questo giro era la mossa sbagliata. L'unico bug reale confermato: nel
Lab, `.lab-results-col` teneva sempre riservata la sua colonna di griglia
anche prima di un backtest, lasciando meta' schermo vuota. **Fatto**: una
sola regola CSS con `:has()` che nasconde quella colonna e restringe
`.lab-panel` a una colonna finche' nessuno dei suoi figli (gia' tutti
`.hidden` di default) diventa visibile — si riapre da sola quando parte
una ricerca, zero JS nuovo toccato.

**Deciso di NON implementare**: l'animazione proposta nel mockup per il
salto Analizza↔resto (`transition: flex-basis`). Il revisore
transitions-dev/polish ha trovato la tecnica tecnicamente rotta (`auto`
non interpola in una transizione) e un rischio concreto — il grafico live
(Lightweight Charts, si ridisegna via `ResizeObserver`) puo' scattare o
deformarsi durante un resize animato, cosa verificabile solo con un test
dal vivo che questo ambiente non permette. Restera' uno scatto secco fra
Analizza e le altre aree, come e' sempre stato — non e' un compromesso
nascosto, e' scritto qui e nel mockup stesso.

Prima di pushare il fix, Lorenzo ha chiesto la preview («non dovevi farmi
vedere in anteprima il risultato?») — il mockup e' stato aggiornato con
l'esito reale (non solo la proposta iniziale) e ripubblicato sullo stesso
link prima del push in produzione. Mockup: `https://claude.ai/code/
artifact/66038881-c72c-406b-9ea0-4281c41bf438`.

---

### Cambio di metodo: dal ragionare sul codice al guardare un browser vero

Lorenzo, dopo l'ennesimo giro sbagliato sul layout: «comunque una volta
eri piu bravo, guardavi il tuo browser e facevi le cose bene». Aveva
ragione — questo ambiente HA Playwright e Chromium pre-installati
(`/opt/pw-browsers/chromium-1194`), utilizzabili con Python 3.11 di
sistema (`pip show playwright` → gia' presente, niente da installare).
Il proxy dell'agente non regge le connessioni websocket-based del browser
verso l'esterno (`ws_closed_mid_exchange` su qualunque host, non solo il
sito), ma **in locale funziona perfettamente**: avviare il backend vero
(`uvicorn app.main:app` dalla cartella `backend`, con
`REGISTRATION_ALLOWED_EMAILS` esteso via env var per potersi registrare
un utente di test) e puntarci Playwright su `127.0.0.1` bypassa il proxy
del tutto (localhost e' sempre escluso). Usato per verificare DAL VIVO,
prima di scrivere qualunque correzione basata solo su rilettura di CSS/JS.

**Cosa e' saltato fuori aprendo davvero un browser**, dopo due
segnalazioni fresche di un utente reale («non trova piu' i pair nel Lab»,
«i pair su ordini spot e futures continuano a non essere trovati») e una
vecchia mai chiusa («il riempimento automatico appare troppo a destra e
sparisce dallo schermo»):

1. **`LightweightCharts is not defined`** — se il CDN esterno (unpkg.com)
   da cui si caricavano il grafico e l'editor CodeMirror non risponde per
   qualunque motivo, la chiamata sincrona non protetta a
   `initCharts()`/`initPineEditor()` lanciava un'eccezione dentro la
   stessa sequenza async di avvio che poi chiama `bindUI`, `bindLabUI`,
   il caricamento watchlist — un errore li' interrompeva silenziosamente
   TUTTO quello che doveva agganciarsi dopo, ricerca ticker compresa,
   ovunque nel sito. Riprodotto bloccando lo script in Playwright:
   la ricerca smetteva di funzionare esattamente come nelle segnalazioni.
   Corretto due volte: entrambe le librerie ora vivono in
   `frontend/static/` (vendorizzate, MIT/Apache 2.0, nessun CDN di terze
   parti come singolo punto di guasto), e le due chiamate sono dentro un
   try/catch cosi' un fallimento futuro resta un problema suo.
2. **Un bug CSS reale, mai notato prima** — `.tab-content.active >
   .panel` aveva un'animazione d'entrata con `transform: translateY(...)`.
   Un transform su un antenato crea un nuovo containing block per ogni
   discendente `position:fixed` per tutta la durata in cui l'animazione
   resta "attached" (sempre, con `fill-mode: both`) — e i riquadri di
   suggerimento (`.suggestions`) sono `position:fixed`, calcolati in JS
   con coordinate assolute rispetto allo SCHERMO. Risultato misurato dal
   vivo: il riquadro del Lab diceva `left: 1171px` nel suo stile inline,
   ma `getBoundingClientRect()` lo piazzava a `left: 2330` su uno schermo
   largo 2000px — completamente fuori bordo, con un raddoppio
   dell'offset (posizione del pannello + posizione voluta). Corretto
   togliendo il `transform` dalle animazioni `lae-sali`/`lae-risultato`
   (resta solo la dissolvenza in opacita', stesso effetto percepito) —
   fix application-wide, non solo per il Lab: qualunque tab con un
   dropdown `position:fixed` dentro il proprio pannello di primo livello
   aveva la stessa falla latente (verificato anche sul campo Pair
   dell'ordine manuale in Sorveglia).
3. Aggiunto anche un timeout di 5s per provider dentro `_safe_search()`
   (backend): senza, un exchange lento o irraggiungibile (rilevante ora
   che Kraken e' stato aggiunto) avrebbe fatto aspettare — o fallire —
   la ricerca combinata su TUTTI gli exchange insieme a lui, perche'
   `asyncio.gather` aspetta ogni gamba fino in fondo.

Tutte e tre le correzioni verificate prima/dopo con lo stesso script
Playwright locale, non solo dedotte dal codice. Board: `8151937b`,
`2a7fd905`, `54cbf520` (segnalazioni vere, chiuse), `seed-0061` (la causa
di fondo, tracciata anche internamente).

**Lezione per la prossima volta**: quando questo ambiente lo permette
(localhost, non un sito esterno dietro il proxy websocket), guardare
davvero un browser prima di dichiarare un fix pronto costa pochi minuti
e trova bug che la sola lettura del codice non avrebbe mai fatto
emergere — vale la pena farlo sempre, non solo quando qualcuno lo chiede
esplicitamente dopo un giro sbagliato.

---

### Diagnosi (test di collegamento exchange) e Modalita' Semplice solo mobile — `seed-0062`, `seed-0063` — **fatto**

Lorenzo, in un unico messaggio con piu' richieste: «A modalita' semplice,
quindi da mobile, soprattutto perche' quella nasce solo da mobile e fa in
modo che da desktop non sia visibile e non ci sia insomma. Vorrei poter
anche eseguire delle prove [...] effettuare il test con una tab dedicata
di diagnosi [...] per effettuare dei test preliminari di collegamento
all'exchange. E vorrei anche che fosse visualizzato il saldo una volta
collegate le API. Prima di poter fare poi le vere operazioni. In ogni
caso vorrei poter fare anche operazioni manuali, quindi provare proprio a
fare il test. E questa sezione diagnosi deve servire proprio come debug.
Deve essere circoscritta e permettere poi a te nel caso in cui vengano
fuori dei problemi di poter rimettere a posto in poco tempo.»

**Modalita' Semplice**: tolto il bottone dalla toolbar desktop in
`index.html` — resta solo l'ingresso dal menu mobile "Altro", che gia'
esisteva (la toolbar desktop e' nascosta sotto i 760px, era per quello
che il bottone mobile era stato duplicato in origine). `simple-mode.js`
non ha avuto bisogno di nessun cambio: cercava gia' entrambi gli id e
scartava quelli assenti.

**Diagnosi**: sezione nuova, voce propria in sidebar (senza `data-area`:
non fa parte del sistema di tab del cockpit apposta, zero rischio di
interferire con quello), costruita come modulo isolato — esattamente
come richiesto, sullo stesso modello di `simple-mode.js`:
- `backend/app/diagnostics.py` (nuovo file): `test_spot_connection()`
  legge il saldo vero da mexc/binance/kucoin/kraken/coinbase/bitstamp
  riusando le firme HMAC gia' scritte nei moduli di esecuzione esistenti
  (import delle funzioni private di firma, non riscritte — niente
  duplicazione); `test_futures_connection()` usa `adapter.
  available_margin()` gia' esistente per ogni exchange futures nel
  registro. Aggiunte `get_all_balances()` a `kraken_exec.py` e
  `coinbase_exec.py` (prima esisteva solo un lookup per una singola
  valuta alla volta). Nuovo endpoint `POST /api/diagnostics/
  test-connection`, sola lettura — se non gli si passano chiavi esplicite
  usa quelle gia' salvate dall'utente, altrimenti prova quelle date senza
  salvarle (utile per provare una chiave nuova prima di sovrascrivere
  quella che magari funziona ancora). 10 test nuovi, tutti con trasporto
  di rete finto.
- `frontend/static/diagnostics.js` (nuovo file): pannello a comparsa,
  toggle spot/futures, test di connessione con esito (saldo o errore), e
  un ordine di prova minimo — solo spot, tramite l'endpoint gia'
  esistente e in uso altrove `POST /api/trading/order` (stessa richiesta
  di conferma esplicita, stesso diario ordini — nessuna logica d'ordine
  duplicata). I futures rimandano al form completo di Sorveglia: quello
  ha l'anteprima di liquidazione, che qui non avrebbe senso riprodurre in
  piccolo.
- **Verificato dal vivo con un browser vero** (Playwright, server
  locale, stesso metodo appena descritto sopra): apertura/chiusura del
  pannello, cambio spot/futures, l'elenco degli exchange futures letto
  per davvero dal registro (non hardcoded), e il messaggio corretto
  quando non c'e' ancora nessuna chiave salvata da provare. Screenshot
  presi e controllati, non solo il DOM.

Non fatto per scelta: nessun controllo esplicito "sei su desktop?" per
Modalita' Semplice (basta togliere l'unico bottone rimasto); l'ordine di
prova futures dentro Diagnosi (rimanda al form di Sorveglia invece di
duplicarlo).

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
- **Modalita' Semplice, seguito** (`seed-0064`): dopo Diagnosi (`seed-0062`)
  e il bottone nascosto da desktop (`seed-0063`), Lorenzo ha chiesto in un
  solo messaggio: dropdown archivio con tutti i dettagli e i trade
  esportabili in Excel "come sul sito", il grafico della Modalita' Semplice
  uguale a quello vero ("le nostre grafiche, non un altro grafico"), le
  chiavi API mai richieste due volte con data/modifica/cancellazione
  visibili, l'eliminazione della "tab piena di caselle da riempire", e
  tutti gli exchange configurati invece di tre. Fatto tutto tranne
  l'eliminazione totale del pannello Sorveglia (vedi sopra il perche' —
  decisione da confermare, non presa da solo). Il pezzo piu' delicato e'
  stato il grafico: invece di ridisegnarlo, spostato il vero nodo
  `.chart-area` dentro Modalita' Semplice con un piccolo ponte
  (`window.LiquidityChartBridge`) e restituito al suo posto ad ogni cambio
  di step — verificato dal vivo con Playwright che il nodo si sposta
  davvero e i marker sono quelli reali del backtest, non un disegno.
- **Modalita' Semplice, correzione** (`seed-0065`): Lorenzo ha respinto la
  prima idea di come collegare l'exchange ("Non ci siamo affatto") —
  chiarendo che non voleva un ciclo inserisci/prova/butta via, ma il
  processo ufficiale (chiave salvata per davvero) con un'opzione in piu'
  subito dopo per testarla senza reinserirla, vedere il saldo vero e
  provare un ordine manuale. Nello stesso messaggio ha ricordato che il
  timeframe va scelto prima e recapitolato alla fine — motivo per cui
  "tante volte" chiede di sistemare le incongruenze fra spot e futures:
  trovata e corretta una vera, la Modalita' Semplice usava tre timeframe
  diversi (backtest, grafico, ottimizzazione) senza dirlo.
- **Modalita' Semplice, ottimizzazione ereditata dal sito** (`seed-0067`):
  "eredita tutta la logica anche grafica che abbiamo creato nel sito per
  ottimizzazione stabile... permettimi anche di fermarla". Lo step
  Ottimizza ora apre la STESSA finestra del Laboratorio (stessa animazione,
  stesso log, stesso pulsante Ferma) tramite un nuovo ponte
  (`window.LiquidityOptBridge`), sullo stesso modello di
  `LiquidityChartBridge`. Trovati e corretti due bug veri per strada: la
  vecchia barra propria di Modalita' Semplice mostrava "[object Object]"
  (assegnava l'intera riga di log invece del solo testo), e — piu' serio,
  e non specifico di Modalita' Semplice — `pollOnce()` in app.js segnava
  un lavoro "fallito" al primo errore di rete qualsiasi (un 503 durante un
  deploy incluso), anche se la ricerca sul server proseguiva tranquilla;
  ora regge fino a 5 giri falliti di fila prima di arrendersi davvero.
- **Modalita' Semplice, grafico da archivio rotto + click sull'ingresso**
  (`seed-0068`): "se seleziono una strategia dall'archivio... non e' che
  devo riselezionare il ticker, vedi che mi chiede il ticker di nuovo?"
  Bug vero: `LiquidityChartBridge.show()` trattava un `backtest_params={}`
  (voce d'archivio senza costi mai registrati — comune, non un difetto)
  come un override reale invece che "nessuno" ({} e' truthy in JS), quindi
  ogni campo costo finiva 'undefined' nella query, il server rispondeva
  422 e il grafico restava vuoto senza dirlo — corretto con lo stesso
  controllo (`Object.keys(...).length`) che applyArchiveEntry() sul sito
  gia' usa. Aggiunta anche la richiesta esplicita: un tocco sul grafico
  reale (`onChartClick()`, nuovo, `mainChart.subscribeClick()`) apre ed
  evidenzia l'operazione piu' vicina in un elenco proprio sotto il
  grafico — stessi dati del pulsante "N trade" del Laboratorio, non quel
  pannello spostato (e' pensato per restare incollato ai suoi risultati).
- **Ordine futures disattivato + Sorveglia incasinata da mobile**
  (`6237708e`, segnalazione reale da whitekobra@icloud.com, non da
  Lorenzo): l'errore "Esecuzione futures disattivata per questo exchange"
  non diceva dove accenderla. Ora nomina l'exchange e, nel form d'ordine
  futures, aggiunge un pulsante "Attiva ora" accanto al rifiuto — un
  tocco accende il toggle senza tornare su alla card giusta. Lorenzo,
  guardando la stessa vista: "da mobile questa vista è veramente
  incasinata" — le quattro sotto-sezioni del pannello 'Chiavi exchange,
  posizioni, diario, ordine manuale' (Posizioni, Ordine futures, Trading
  automatico, Ordine manuale) erano tutte scaricate in un'unica colonna
  lunghissima; ognuna e' ora un dettaglio proprio, chiuso finche' non
  serve.
- **Modalita' Semplice, tocco senza risposta** (`seed-0066`): "quando
  seleziono il ticket il click non produce un'accettazione grafica...
  sembra che non carichi anche se in realta' e' stato selezionato". Aggiunto
  un effetto di pressione immediato + spinner sulla riga. Trovato un bug
  vero dietro il sintomo: `state.ticker` non salvava mai `provider`, quindi
  l'evidenziazione "selezionato" spariva sempre al primo ridisegno della
  lista — non era solo lentezza percepita, l'indicatore visivo era rotto.
- **Ordine futures: quantita' diretta in token** (`seed-0070`): Lorenzo,
  pensando ad alta voce su un rischio vero — "si rischia dei disastri se
  uno puo' [inserire] migliaia di dollari... e te li seleziona invece come
  dollari, come unita' di misura token diventa un delirio" — poi "procedi,
  in caso analizza con attenzione anche altre strade e rendi professionale
  questa cosa per i futures". Aggiunto un terzo modo di taglia
  all'ordine futures manuale, "Quantità" (base_qty), con un campo proprio
  (niente slider — non ha senso una scala percentuale per un numero di
  token che va da 0.0001 a milioni) etichettato con l'asset vero del pair.
  Il paracadute resta l'anteprima gia' obbligatoria: mostra sempre il
  nozionale/margine reali in USDT prima di confermare, qualunque modo si
  scelga. Trovato per strada un bug di sicurezza vero: il controllo di
  margine pre-ordine, senza il nuovo ramo, avrebbe letto una quantita' di
  token come percentuale del saldo (praticamente zero) e sarebbe passato
  sempre, indipendentemente dal nozionale reale — corretto nello stesso
  giro. Deliberatamente non toccato lo spot manuale (manca ancora
  un'anteprima li', ma costruirla per sei exchange e' un lavoro a se') —
  segnalato come seguito, non deciso da solo.

## Modalità Semplice (wizard guidato) — branch `claude/simple-mode`

Prototipo approvato via Artifact dopo tre giri di revisione, implementato in
`frontend/static/simple-mode.js` (nuovo file, non tocca `app.js`) + un
bottone/contenitore aggiunti a `frontend/index.html`. Zero endpoint nuovi:
ogni passo chiama API già esistenti (`/api/symbols`, `/api/archive`,
`/api/strategies`, `/api/analyze`, `/api/optimize/start` + polling
`/api/jobs`, `/api/auth/trading`, `/api/watchlist` + PATCH
strategy/strategy_params, `/api/archive/{id}/apply-to-alert` per lo
shortcut da archivio). Stato persistito in `localStorage` (`simpleModeActive`).

Scelte fatte in autonomia, da rivedere con Lorenzo se non vanno bene:
- **Solo spot**: niente `/api/auth/futures` — coerente con la leva limitata
  a 1x server-wide.
- **Exchange offerti nel wizard**: Binance, KuCoin, Kraken (il prototipo
  mockava "Bybit", che `auth.set_trading_credential` non supporta — sostituito
  con KuCoin per restare a 3 card).
- **Ticker azionari**: niente step exchange/esecuzione automatica (solo
  spot crypto ha `place_order_for_signal`); l'attivazione diventa "solo
  avviso Telegram", dichiarato onestamente nella UI.
- **Stima tempo ottimizzazione**: il backend non traccia una percentuale
  reale (solo `elapsed_s` in jobs.py). Stima lato client con le stesse
  soglie già comunicate altrove (Rapida 10-25s, Stabile 1-5min), che passa a
  "quasi fatto" oltre il range invece di un countdown che sbaglia in silenzio.
- **Uscita durante l'ottimizzazione**: permessa sempre — il job gira
  server-side e continua anche se si esce dal wizard (i risultati con
  `owner_id` finiscono comunque in archivio).
- Verificato in Browser pane con backend mockato via `fetch` (nessun Python
  3.12 in questo ambiente): tutti gli 8 passi (0-7), desktop e 375px. Non
  verificato contro il backend reale — da rifare a mano o in CI.

### Seguito — seed-0064 (archivio, grafico reale, exchange completi, chiavi)

Lorenzo, subito dopo seed-0062/63, ha chiesto sei cose insieme. Fatte (vedi
`resolutions.json` sotto `seed-0064` per il dettaglio tecnico completo):

1. Step archivio con metriche complete (rendimento/drawdown/operazioni/PF/
   candele/parametri) + pulsante Excel reale (`/api/export/backtest.xlsx`).
   Corretto anche un bug vero trovato per strada: `created_at` e' un epoch
   (int), uno `.slice()` sul valore ci interrompeva silenziosamente il
   rendering dell'intera lista se l'archivio aveva gia' voci per quel ticker.
2. Il grafico dello step Backtest e' ora il VERO `.chart-area` del sito
   (LightweightCharts, indicatori, marker), spostato nel DOM dentro
   Modalita' Semplice via un ponte minimo — `window.LiquidityChartBridge`
   in `app.js` (mount/restore + `applyConfigToChart`/`runAnalysis`, le
   stesse funzioni gia' usate da `applyArchiveEntry`) — non una copia.
   Verificato dal vivo (Playwright): il nodo si sposta davvero, i marker
   di ingresso/uscita sono quelli reali del backtest.
3. Chiavi gia' salvate non vengono piu' richieste due volte nel wizard
   (controllo `/api/auth/trading` prima di mostrare i campi).
4. `TRADING_EXCHANGES` esteso da 3 a tutti e 6 (mexc, binance, kucoin,
   kraken, coinbase, bitstamp).
5. Footer con la data di deploy (stesso `/api/version` della sidebar).
6. Lato desktop: le card credenziali di Sorveglia (trading e futures) ora
   mostrano, quando salvate, "🔒 Chiave salvata e cifrata — registrata il
   ..." con un pulsante Elimina sempre visibile (nuovo `created_at` su
   `ExchangeCredential`/`FuturesCredential`, nuovi `DELETE /api/auth/trading/
   {exchange}` e `/api/auth/futures/{exchange}`).

**Non fatto, deciso in autonomia**: NON ho rimosso il pannello
`.opera-advanced` di Sorveglia per intero. Lorenzo aveva scritto "non deve
esserci una tab piena di caselle da riempire... quella ti chiederei di
eliminarla" — ma quel pannello contiene anche Posizioni aperte, Diario
ordini e Ordine manuale, che non erano l'oggetto della lamentela (le
"caselle da riempire" erano i form di chiave, gia' risolti al punto 6 sopra
con lo stato "salvata"). Toglierlo del tutto avrebbe eliminato capacita'
vere (vedere le posizioni aperte, il diario, piazzare un ordine manuale da
desktop) senza che fosse stato chiesto esplicitamente — e sarebbe stato
difficile da tornare indietro una volta che l'abitudine di usarle da li'
fosse cambiata. Se Lorenzo intendeva davvero eliminare l'intero pannello
(non solo il fastidio delle chiavi), va confermato e poi si decide dove
spostare posizioni/diario/ordine manuale (Diagnosi? Sorveglia in altra
forma?) invece di farli sparire.

### Seguito — seed-0065 (testare la chiave subito, timeframe coerente)

Lorenzo ha corretto il punto piu' delicato di seed-0064: non voleva
"inserire, provare, buttare via" — voleva che il processo di salvataggio
restasse quello ufficiale (PATCH /api/auth/trading, invariato) ma con
un'opzione in piu' subito dopo: "vuoi testarle subito?". Aggiunto un passo
5.5 fra Exchange e Riepilogo che fa esattamente questo — chiama
`/api/diagnostics/test-connection` con chiavi vuote (usa quella appena
salvata, non la richiede mai di nuovo), mostra saldo vero o errore vero, e
offre un ordine manuale di prova (`/api/trading/order`, stesso endpoint di
Diagnosi — niente testnet in questa piattaforma, quindi denaro reale
dichiarato, mai finto).

Nello stesso giro ho trovato e sistemato la causa di fondo per cui Lorenzo
torna spesso su "la cosa dei ticket dello spot e del futures": la Modalita'
Semplice usava tre timeframe diversi in tre punti diversi senza dirlo (il
backtest non passava affatto l'intervallo al server, il grafico accanto
usava "1d" fisso, l'ottimizzazione un altro "1d" fisso ancora). Aggiunto un
selettore di timeframe allo step Strategia, un solo `state.interval` usato
ovunque dopo. Verificato dal vivo (log del server) che backtest e
ottimizzazione arrivano davvero con lo stesso intervallo.

### Seguito — seed-0071 (tetto per strategia, % saldo su MEXC)

Filone nato da una lunga spiegazione vocale di Lorenzo sul rischio di usare
importi fissi per il trading automatico ("se io devo fare ordini
frammentati non c'e' verso che funzioni [con importo fisso]... l'unico modo
e' fare con una percentuale del saldo"), ma con un problema vero quando piu'
strategie condividono lo stesso exchange: "io magari voglio fare 10 ordini
da 500 dollari l'uno con il bot, ma se lui pesca con la percentuale e'
finita". Soluzione concordata nel dialogo: tenere la % di saldo com'e' (mai
guardare la quantita' di token), ma lasciare impostare un **tetto massimo in
USDT** per singola strategia al momento di attivare l'operativa automatica —
non un importo fisso che sostituisce la percentuale, un limite sopra di
essa. Punto fermo ribadito piu' volte da Lorenzo: la chiusura di una
posizione (incluso un flip) deve sempre chiudere per intero, il tetto non
deve mai poterla toccare, e se un flip si riapre con meno saldo di prima
"non deve accadere l'errore" — il sistema deve riadattarsi da solo.

Implementato: `WatchlistEntry.size_cap_usdt` (dict per strategia) +
`PATCH /api/watchlist/{id}/size_cap`, propagato come `max_usdt` opzionale
attraverso `executor.py`, tutti i 5 moduli spot e tutti i 6 adattatori
futures — applicato SOLO lato ingresso/BUY, mai su `close_position` o sul
lato SELL (che su alcuni segnali e' una chiusura mascherata). UI: il tetto
si chiede nel flusso di attivazione ("Anche operazioni automatiche" →
tetto facoltativo prima di scegliere la strategia) e resta modificabile
sotto ogni strategia gia' attiva in Sorveglia.

Nello stesso giro, indagato anche un secondo report separato di Lorenzo: "%
saldo non funziona su MEXC". Prima diagnosi (permesso `SPOT_ACCOUNT_READ`
mancante) **sbagliata** — Lorenzo ha mostrato lo screenshot dell'API
Management di MEXC coi permessi tutti presenti, e ha lui stesso indicato la
causa vera: "erroneamente secondo me acquistavi 10 kaspa invece di 10
dollari di controvalore in kaspa (superando il balance)". Aveva ragione:
`quoteOrderQty` (il parametro con cui si dice "spendi X USDT", usato per
ogni ordine automatico) su MEXC viene trattato su piu' pair come una
QUANTITA' di moneta, non un importo — un ordine da 10 USDT diventava un
ordine da 10 monete, quasi sempre oltre il saldo disponibile. Bypassato
calcolando noi la quantita' dal prezzo corrente e mandando `quantity`
invece di `quoteOrderQty`, solo per MEXC (Binance resta sul parametro
originale, che li' funziona davvero come documentato). Non verificabile con
denaro reale in sandbox (rete bloccata verso gli exchange) — verificato che
il payload mandato all'ordine e' quello giusto (2 nuovi test in
`test_mexc_order.py`).

Verificato dal vivo: endpoint size_cap via curl (persistenza, azzeramento),
campo tetto su strategia gia' attiva via Playwright (valore iniziale letto
correttamente, modifica salvata e confermata rileggendo la watchlist). Non
riverificato dal vivo il tetto durante l'attivazione di un ticker nuovo
tramite browser (il resto della UI di attivazione — autocomplete pair — non
e' cambiato da questo lavoro), ma la stessa funzione `stepCap()` e la stessa
chiamata PATCH sono usate in entrambi i percorsi. 448 test totali passano,
ruff pulito.

Terzo giro sullo stesso filone: Lorenzo ha riportato l'ordine futures manuale
MEXC "sempre lo stesso errore" con la %, incollando il testo esatto ("la
dimensione richiesta vale 0.284 contratti, meno del minimo di 1... serve
almeno 35.20 USDT di margine con leva 1x"). Trovato e corretto un vero bug di
robustezza (il codice presumeva sempre minVol=1 contratto invece di leggerlo
dall'exchange — su KASUSDT valeva comunque 1, ma non e' garantito per ogni
pair), MA il messaggio d'errore era gia' corretto: con `MAX_FUTURES_LEVERAGE`
bloccato a 1x (voluto, "resta a 1x SEMPRE" — Lorenzo lo ha ribadito quando gli
ho chiesto se alzarlo), il margine coincide col nozionale intero, e MEXC
impone un minimo di 1 contratto = 1000 KAS = 35.20 USDT su quel pair a
qualunque leva. Su MEXC direttamente lo stesso ordine con 20 USDT passava
solo perche' la' la leva era 20x (margine 35.20/20 = 1.76 USDT), non 1x —
stesso pair, stessa formula, leva diversa. Lorenzo ha verificato di persona e
confermato: "hai ragione tu, serve 35.20 usdt". Nessun bug residuo: il tetto
di leva a 1x resta per scelta esplicita sua, quindi su pair a nozionale
minimo alto come KASUSDT serve piu' saldo/percentuale per aprire una
posizione, e il messaggio d'errore ora lo dice in modo chiaro (USDT, non solo
contratti). Lezione per chi riprende questo filone: quando Lorenzo riporta
"stesso errore, sempre" non e' detto sia un bug — a volte e' l'exchange che
rifiuta correttamente, e il lavoro giusto e' rendere il messaggio azionabile,
non cercare un bug che non c'e'.

## Log delle conversazioni (continua)

- **Tetto per strategia + % saldo su MEXC** (`seed-0071`): Lorenzo, voce
  lunga: "io magari voglio fare 10 ordini da 500 dollari l'uno con il bot,
  ma se lui pesca con la percentuale e' finita... l'importo massimo...
  preinserito in fase di allestimento della strategia prima di attivare
  l'alert... per la chiusura ovviamente comando close position... senza
  stare a guardare controvalori, semplicemente la chiude". Poi, separato:
  "voglio usare la % del saldo per gli ordini automatici... pero' sembra
  non funzionare su mexc.. verifica se lo accetta". Chiuso con "sistema fai
  tutto tu, mi fido" — implementato tetto per strategia (mai sulle
  chiusure). Sul bug MEXC, prima diagnosi sbagliata (permesso mancante):
  Lorenzo ha corretto con lo screenshot dei permessi e la sua stessa
  intuizione — "erroneamente secondo me acquistavi 10 kaspa invece di 10
  dollari di controvalore" — che era la causa vera, poi confermata e
  corretta (quoteOrderQty trattato da MEXC come quantita', non importo).
  Terzo giro sul futures manuale: "e perche' dentro app mexc con il telefono
  riesco a operare con 20 usdt?" — spiegato che li' la leva era 20x contro
  1x qui (voluto, "in leva1x... resta a 1x SEMPRE"), stesso pair stessa
  formula. Lorenzo ha verificato di persona: "hai ragione tu, serve 35.20
  usdt" — nessun bug, il messaggio d'errore era gia' corretto.
- **Blocco di rete MEXC futures** (`seed-0072`): Lorenzo, dopo il tetto di
  leva: "abbiamo provato con 50 usdt e ottenuto questo errore" con incollata
  una pagina Akamai "Access Denied" che il codice leggeva come permesso
  mancante. Chiesto come procedere, Lorenzo ha scelto "instrada MEXC
  futures fuori UE" — aggiunta la env var `MEXC_FUTURES_PROXY`, non ancora
  configurata in produzione (serve un proxy vero, non procurabile da qui).

### Aperto — seed-0072 (blocco di rete MEXC futures, serve un proxy fuori UE)

Dopo aver chiarito il tetto di leva (sopra), Lorenzo ha provato un ordine
manuale da 50 USDT su MEXC futures e ha incollato l'errore esatto: una
pagina HTML "Access Denied" di Akamai/Edgesuite, non una risposta di MEXC.
Il codice leggeva "permission" dentro quel testo e lo traduceva (sbagliando
di nuovo) in "manca il permesso della chiave" — corretto: `explain()` in
`base.py` ora riconosce una pagina di blocco CDN (contiene "access denied" +
"edgesuite"/"akamai" dentro tag HTML) PRIMA di cercare le parole chiave
generiche, e dice esplicitamente che e' un blocco di rete, non un problema
di chiave.

Causa probabile della richiesta bloccata: coerente con quanto il codice
stesso dice da mesi (`registry.py`: "MEXC non ha licenza UE per i
derivati... aggiunto su richiesta esplicita di Lorenzo, che ha scelto
sapendolo"), l'IP europeo del server (Hetzner, Germania) viene negato da
MEXC specificamente su `/order/submit` — le chiamate di sola lettura
(prezzo, saldo) probabilmente passano, l'invio ordine no.

Chiesto a Lorenzo come procedere fra "prova comunque", "instrada fuori UE" e
"lascia perdere MEXC futures" — ha scelto **instradare fuori UE**. Aggiunta
la capacita' lato codice: `MEXC_FUTURES_PROXY` (env var, vuota di default =
comportamento invariato) instrada le sole chiamate a MEXC futures
attraverso un proxy/VPS scelto da lui — nessun altro exchange futures ne
risente. Documentata in `deploy/.env.example`.

**Non fatto, non posso farlo da qui**: procurare e configurare il proxy
vero. Serve un server/proxy fuori UE (Lorenzo decide dove — un VPS a
noleggio in una regione non-UE va bene) e il suo indirizzo va messo in
`deploy/.env` sul server di produzione. Finche' non e' impostato, gli
ordini futures MEXC restano bloccati come ora — il codice e' pronto a
usarlo appena c'e'.

### Chiuso — seed-0073 (design "AI slop", pulizia sistemica CSS)

Lorenzo: "tutto il sito sembra fatto da ai slop". Invece di ricontrollare a
occhio, diagnosticato con `impeccable` (github.com/pbakaus/impeccable, 67.5k
stelle — verificato prima di eseguirlo, dopo che un primo tentativo di
Lorenzo di farmelo installare via un link/comando sospetto era stato
correttamente rifiutato): 145 problemi deterministici su `index.html` e
`sniper.html`, concentrati in poche categorie sistemiche (testo troppo
piccolo, striscia colorata spessa su un lato delle card — il tell piu'
riconoscibile del design generato da AI — bordo sottile+ombra larga,
contrasto insufficiente nel tema scuro).

Corretto per categoria, non caso per caso: 241 dichiarazioni font-size
alzate (+ il token `--text-xs`), 14 punti con la striscia laterale rimossa
o assottigliata, 3 bordi ridondanti tolti dove c'era gia' un'ombra larga,
contrasto del testo piu' tenue nel tema scuro alzato al minimo WCAG AA
(calcolato con la formula di luminanza relativa, non a tentativi),
un'animazione di `width` (causa reflow) sostituita con `transform: scaleX()`
sulla barra di progresso della Modalita' Semplice. Da 145 a 15 problemi
residui — quelli rimasti sono scelte deliberate gia' documentate nel codice
(il serif per i numeri, gli indicatori "live" pulsanti, la voce a em-dash di
tutto il progetto) o richiedono un'analisi del DOM renderizzato che il tool
non espone abbastanza in dettaglio (4 istanze di testo lungo in maiuscolo,
non isolate). Non toccati senza conferma esplicita — sono scelte di stile
del progetto, non difetti di questa pagina.

Nello stesso filone, Lorenzo ha chiesto di installare "tutti" i repo di una
lista da un articolo Medium — rifiutato l'installazione cieca (12 progetti
ignoti, nessun bisogno preciso dichiarato), proposto di analizzarli prima
se ne indica uno specifico. Nessun repo installato da quella lista.

Verificato dal vivo con Playwright (desktop 1280px e mobile 390px, anonimo e
autenticato) che nessuna modifica ha rotto il layout. `node --check` su
tutti i JS toccati, 452 test backend passano (nessuno di questi cambi tocca
il backend), ruff pulito.

- **Design "AI slop"** (`seed-0073`): Lorenzo, secco: "tutto il sito sembra
  fatto da ai slop". Diagnosticato con lo strumento open source
  `impeccable` invece di ricontrollare a occhio (verificato su GitHub prima
  di usarlo, dopo aver rifiutato un primo tentativo di installazione via
  link/comando sospetto) — 145 problemi, risolti per categoria (font-size,
  striscia laterale colorata, bordo+ombra ridondante, contrasto) invece che
  uno per uno, su sua richiesta esplicita: "fixa tutto occhio ai token, fai
  efficienza". Sceso a 15 residui, tutti scelte deliberate o a bassa
  priorita'. Rifiutata anche una richiesta di installare "tutti" i repo di
  una lista da un articolo Medium — poi chiarita da Lorenzo come "analizza,
  mica installare alla cieca".
