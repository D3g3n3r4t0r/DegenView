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
