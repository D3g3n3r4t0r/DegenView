# DeepSeek: il nostro aiutante

Lorenzo, 27/09: "da oggi considera deep seek un tuo aiutante costante; dagli
task che è in grado di svolgere e in base alla sua abilità aumenta il carico
di lavoro; obbiettivo risparmiare token qui". E: "crea un ambiente di scambio
per informazioni".

Questo file è lo scambio fra Claude e DeepSeek: cosa fa DeepSeek, come gli si
passa il lavoro, come sta andando. Claude lo aggiorna dopo ogni lavoro
rivisto; le revisioni delle PR lo leggono insieme a CLAUDE.md.

## Cosa fa oggi

| lavoro | dove | stato |
|---|---|---|
| revisione di ogni PR | `.github/workflows/deepseek-review.yml` | attivo, secondo parere |
| revisione dei token (sistema) | `app/trading/onchain/ai_review.py` | attivo |
| chat su Telegram, con i dati del sito | `app/notify/deepseek_desk.py` | attivo |
| riepilogo giornaliero dei token, alle 21 | `app/notify/deepseek_desk.py` | attivo |
| rischio rug su ogni meme segnalata, a gruppi di 10 | `app/trading/onchain/ai_scan.py` | in ombra: si misura |
| lettura del sito delle gemme | `app/trading/onchain/legit.py` | in ombra (`LEGIT_AI_GATE` per farlo bloccare) |
| voto delle gemme: meta' del pilastro ricerca sui finalisti | `app/trading/onchain/research.py` | attivo (80/giorno) |
| lettura approfondita a pagamento | `research.ai_dossier`, `plans.py` | attiva |
| database completo in chat (progetti, gemme, alert, sistema, scartati, memoria) | `main._deepseek_tools` | attivo, sola lettura |
| segnalazioni di bug sulla bacheca (autore "DeepSeek (Telegram)") | `main._deepseek_report` | attivo, 10/giorno; Claude verifica |
| memoria dei rug: casi simili nel giudizio, strumenti in chat | `app/trading/onchain/rug_memory.py` | attivo (legge il diario di `outcomes.py`) |

Lavoro affidabile = conta i token che fa. Il riepilogo li confronta con quello
che sarebbero costati su Claude, a prezzi di listino.

## Il piano (27/09)

Lorenzo: "studia un bel piano per incastonare alla perfezione deep seek,
esaminando tutto quello che abbiamo fatto".

### Cinque regole, prese da quello che abbiamo già misurato

1. **DeepSeek produce dati e testo, non decisioni di prezzo.** Su KASUSDT
   daily nessuna strategia ha edge e la ricerca casuale è una lotteria
   (CLAUDE.md): un modello che "sente" quando comprare sarebbe la stessa
   lotteria. Ingressi, uscite, autotrader, importi, chiavi e firme restano
   codice deterministico.
2. **Ogni suo giudizio entra nella memoria che già c'è.** `outcomes.py`
   misura per ogni controllo se separa i rug dagli altri (AUC) e lo fa
   entrare nel filtro solo se regge *fuori campione*. Il voto di DeepSeek
   diventa una colonna in più di quella memoria: niente soglie scelte a mano,
   stesso cancello di tutto il resto.
3. **Poco testo, a gruppi, una volta sola.** Fatti in una riga invece di
   pagine; dieci token per richiesta sotto istruzioni identiche (DeepSeek fa
   pagare un decimo la parte ripetuta); cache per token e per pagina; tetto
   giornaliero per ogni tipo di lavoro. Tutto passa da
   `deepseek_desk.ask`, che conta i token e alimenta il riepilogo delle 21.
4. **Dove basta un modello di testo fisso, niente IA.** Le uscite del
   sistema hanno già il motivo (segnale, crollo, 48h, rug) e il riepilogo
   settimanale ha già la riga italiana nei commit: lì un modello di frase
   costa zero ed è sempre giusto.
5. **Se DeepSeek non risponde, l'app funziona uguale.** Ogni suo pezzo è un
   di più: senza chiave, senza credito o col servizio giù si torna a oggi.

### La mappa: dove entra e dove no

| parte dell'app | oggi | con DeepSeek |
|---|---|---|
| Meme (listing → alert) | controlli automatici + memoria | voto di rischio per ogni alert (fatto, in ombra) → colonna della memoria |
| Gem Finder: sito (`legit.py`) | Claude Opus, spento senza chiave | DeepSeek su 4000 caratteri, in cache (fatto, in ombra) |
| Gem Finder: ricercatore (`research.ai_dossier`) | Claude, spento senza chiave | DeepSeek legge descrizione e documenti del progetto |
| Piano "deep" a pagamento (`plans.py`) | disponibile solo con chiave Anthropic | disponibile con DeepSeek, a costo quasi zero |
| Narrative (`narratives.json`) | mappa scritta a mano | ogni settimana DeepSeek propone temi nuovi dai temi raccolti; approva Lorenzo |
| Revisore giornaliero (`ai_review.py`) | già su DeepSeek | uguale; in più legge le statistiche in ombra |
| Alert su Telegram | numeri | una riga "perché", presa dallo stesso giudizio (nessuna chiamata in più) |
| Scanner | filtri a pulsanti | ricerca a parole → filtri (una chiamata per frase, in cache) |
| Telegram | avvisi | chat (fatto), brief del mattino |
| Sviluppo | Claude | revisione di ogni PR (fatto); DeepSeek che scrive PR da issue: in attesa del permesso di Lorenzo |
| Autotrader, swap, wallet, depositi | codice | **niente IA**: ci sono soldi veri |

### Le fasi

**Fase 1 — Allacciare alla memoria.** È il pezzo che rende tutto il resto
misurabile.
- `outcomes.features` legge `alert["ai"]["risk"]` e il voto del sito come
  colonne; l'AUC fuori campione decide se entrano nel modello.
- `research.ai_dossier` ripiega su DeepSeek quando manca la chiave
  Anthropic, con il suo tetto giornaliero.
- Il piano "deep" diventa disponibile con DeepSeek.
- Costo: meno di 1 $ al mese.

**Fase 2 — Spiegare.**
- Il giudizio delle meme restituisce anche una frase "perché" (+15 token
  per token), che finisce nell'alert Telegram e nella scheda del token.
- Le uscite del sistema restano a modello fisso (regola 4).
- Costo: centesimi.

**Fase 3 — Narrative.**
- I temi di ogni giudizio (`alert["ai"]["theme"]`, dossier delle gemme)
  vengono contati: lo Scanner mostra "temi caldi" senza chiamare nessuno.
- Una volta a settimana DeepSeek legge i conteggi e propone voci nuove per
  `narratives.json`. Arrivano su Telegram, Lorenzo approva, Claude le mette.
- Costo: centesimi.

**Fase 4 — Scanner a parole.**
- "Meme su Solana, liquidità sopra 50k, holder in crescita" → filtri JSON
  dello Scanner.
- Cache per frase, tetto per utente.
- Costo: dipende dall'uso, ~0,0001 $ a ricerca.

**Fase 5 — Brief del mattino.**
- Una chiamata al giorno sui numeri che il sito ha già: sistema, alert
  della notte, rug evitati, temi.
- Costo: ~0,15 $ al mese.

**Fase 6 — Aiutante di sviluppo.**
- Le revisioni delle PR crescono di peso secondo il loro storico (tabella
  sotto).
- Il lavoratore che apre PR da issue parte solo se Lorenzo lo autorizza.

### Quando un giudizio in ombra diventa un filtro

- Almeno 300 alert giudicati con almeno 30 rug.
- La memoria lo fa entrare (AUC fuori campione sopra la sua soglia).
- Nel riepilogo, i rug fra "rischio alto" sono almeno il doppio che fra
  "rischio basso".
- Allora si accende il cancello (`LEGIT_AI_GATE` per i siti; per le meme il
  modello della memoria), e si scrive qui sotto com'è andata.

### Budget

Fasi 1–5 insieme, all'uso di oggi: **2–4 $ al mese**, più la chat quanto la
usate. Il tetto giornaliero per tipo di lavoro impedisce le sorprese; il
riepilogo delle 21 dice ogni sera la spesa vera.

## Come Claude gli passa lavoro

Per ora solo per le strade qui sopra: DeepSeek gira sul server e su GitHub,
Claude no (la sua sandbox non raggiunge internet). Un DeepSeek che scrive
codice e apre PR da solo è stato proposto ed è in attesa della decisione di
Lorenzo: vedi HANDOVER.

## Per DeepSeek, quando rivedi una PR

- Segnala solo quello che hai verificato sul diff: file, riga, cosa succede.
- Leggi il codice prima di dire che un test "non testa" qualcosa: guarda
  quale funzione chiama.
- Le tre strategie non sono tutte trend-following (CLAUDE.md): un filtro di
  persistenza giusto per una è rovesciato per le altre.
- Soldi degli utenti, chiavi, firme: lì ogni dubbio vale la pena scriverlo.

## Com'è andata (Claude aggiorna)

| data | lavoro | esito |
|---|---|---|
| 27/09 | PR #155, prima revisione | 5 osservazioni, 0 valide: diceva che un test non isolava la chiave (la toglieva già) e che un altro chiamava `main()` (chiamava `ask()`). |

| 27/09 | issue #173, primo lavoro di codice (righe del Database cliccabili) | corretto al primo colpo: 2 file, diff pulito, nessuna correzione di Claude |
| 27/09 | issue #176 (pannello agente) | fallita due volte per un difetto del lavoratore (`path=` davanti al percorso), poi corretta al primo colpo |
| 27/09 | issue #177 (market cap globale) | prima fallita per un mio `Tests:` dentro il compito, poi una risposta vuota su `path/to/file` accettata dal lavoratore; al terzo giro corretta senza ritocchi |
| 27/09 | issue #178 (pagina token completa) | buona: corretti a mano sistema dei meme usato per le gemme, righe 'not ranked' sui meme, file segnaposto |
| 27/09 | issue #182 (memoria dei rug) | buona: corretto a mano il taglio a blocchi della classe maggiore, file segnaposto |
| 27/09 | report bug dalla chat Telegram (10 punti) | 1 bug vero (punti 1-2, con causa letta male), 4 non-bug, 3 domande di strategia |
| 27/09 | issue #188 (app centrata, zoom caselle) | fallita sul CSS (nessun punto unico dove inserire), poi importava `nozoom.js` senza crearlo: l'app sarebbe rimasta bianca. Modulo scritto da Claude |
| 27/09 | issue #189 (trend gia' in corso all'alert) | logica giusta al primo colpo; non ha lanciato il test vecchio che fissava il comportamento sbagliato, ne' ricalcolato gli alert |
| 27/09 | issue #190 (trade delle due strategie) | fallita sul CSS, poi buona; ricompariva lo 0% per chi non ha tradato |
| 27/09 | issue #191 (niente 0% in classifica) | giusta al primo colpo |
| 28/09 | issue #200 (backtest per alert) | primo giro fermato dal lavoratore (test su candele piatte: le contromisure hanno funzionato); secondo giro giusto |
| 28/09 | issue #201 (backtest nell'app) | buona; corretti ordine iniziale e 0% al posto di un dato mancante |
| 28/09 | issue #203 (link al grafico principale) | non funzionava: `setArea` fuori portata e BTC caricato sopra al link; finestra bloccata su iOS. Corretto da Claude, provato in browser |
| 28/09 | issue #204 (backtest migliore, niente selettori) | giusta al primo colpo |
| 28/09 | #210 contatore backtest | giusta al primo colpo |
| 28/09 | #211 icone barra/podio | coppa poco visibile, corretta |
| 28/09 | #214 profilo compatto | griglia della riga cash sbagliata, corretta |
| 28/09 | #216 niente nomi di strategie | tolto `NAMES` ancora usato, nome ancora stampato, import mancante dalla #190: corretti |
| 28/09 | #223 podio per punteggio | giusta al primo colpo |
| 28/09 | #226 nascondi token, parte 1 | primo giro: lavoratore in timeout (test di main); secondo: deadlock sul lock (compito mio ambiguo); terzo: import mancante di nuovo -> aggiunto ESLint no-undef al lavoratore |
| 28/09 | #231 nascondi token, parte 2 | giusta al primo colpo |

Regola per dargli più lavoro: tre revisioni di fila con almeno un'osservazione
giusta e nessuna inventata → gli si affida anche la prima stesura dei testi in
italiano (spiegazioni delle uscite, riepilogo settimanale).
