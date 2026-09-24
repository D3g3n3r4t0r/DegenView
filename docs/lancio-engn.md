# Lancio $ENGN — piano

Stato: **decisioni prese, niente e' stato lanciato o pubblicato fuori dal sito.** Ogni
passo irreversibile (creazione del token, liquidita', annunci) aspetta il si'
esplicito di Lorenzo.

## Identita'

| | |
|---|---|
| Nome | Liquidity Engine (dominio liquidityengine.app gia' nostro) |
| Ticker | **$ENGN** — su DexScreener nessun token con questo simbolo (24/09/2026). $LQE esiste gia' su BSC (morto), scartato. $DEGEN e $SNIPE sono presi. |
| Slogan | **Find them first. Ride them right.** |
| Chiusura | The chain never sleeps. Neither does the engine. |
| Pagina | `/engn` (pubblica, senza login), tasto centrale ENTER THE APP -> `/onchain-app.html` |
| Stile | Cubo nero con fessura verde, griglia e candele (immagine scelta da Lorenzo), stesso verde menta dell'app, Instrument Serif + Geist Mono |

Le regole mostrate sulla pagina (Sniper e Microcaps) sono lette dalle costanti
di `radar.py` all'avvio: se cambia una soglia cambia anche la pagina.

## Tokenomics

Offerta fissa 1 000 000 000, Solana (SPL), 0% tasse, nessuna prevendita.

| Quota | % | Sblocco |
|---|---|---|
| Liquidita' fair launch | 45 | tutta al lancio, LP bruciato |
| Community e primi utenti dell'app | 15 | airdrop, 6 mesi lineare |
| Ecosistema e ricompense strategie | 15 | 36 mesi lineare, stream on-chain |
| Tesoreria (multisig Squads) | 10 | cliff 6 mesi, poi 24 mesi lineare |
| Team | 10 | cliff 12 mesi, poi 24 mesi lineare |
| Listing e market making | 5 | bloccato fino al primo listing |

Pensata per **passare i nostri stessi filtri** (`depth.py`): creatore sotto
15%, nessun wallet sbloccato sopra 20%, top 10 sotto 60% (le quote in vesting
stanno nel contratto di lock, che il filtro esclude), mint e freeze revocati,
tassa 0.

Utilita' (da costruire, fase 2): accesso a livelli in base al saldo del
wallet collegato — Scout gratis (radar con 15 min di ritardo), Sniper 250k
$ENGN (tempo reale, classifica completa, meta' commissione), Engine 1M $ENGN
(strategie automatiche, nessuna commissione). Soglie da rivedere col prezzo
di lancio.

## Decisioni prese (Lorenzo: "decidi tutto tu, voglio fare un progetto legit")

1. **Pagina:** resta su `/engn`. La home `/` non cambia (chi usa l'app
   classica non perde l'accesso). Al lancio, un dominio dedicato punta a
   `/engn`.
2. **Modalita' di lancio:** pool Raydium CPMM SOL/ENGN con LP bruciato, apertura
   a orario annunciato. Niente pump.fun, niente prevendita, niente round privati.
3. **Liquidita' iniziale:** 450 000 000 ENGN + 40 SOL. Nessuno riceve token
   prima del pool, quindi nessuno compra "sotto" il prezzo pubblico.
4. **Nessuna commissione di swap nell'app al lancio.** I livelli danno
   funzioni, non sconti: il token non promette flussi di denaro.
5. **MiCA: si va con il white paper, non con le esenzioni.** Bozza in
   `docs/whitepaper-engn.md`. Il token non si offre prima della notifica a
   CONSOB e della revisione di un legale.
6. **Onesta' in pagina:** tolto tutto cio' che non esiste ancora (sorgente
   X, social, GitHub pubblico, sconti di commissione); detto chiaro che il
   pilota non ha ancora un edge dimostrato e che le chiavi sono cifrate sul
   server ed esportabili.

## Cosa blocca il lancio (serve Lorenzo, non si puo' fare da qui)

- **Una societa'.** Per MiCA (art. 4) chi offre un cripto-asset al pubblico
  deve essere una persona giuridica: serve una SRL (o altra entita') come
  offerente, con LEI.
- **Legale** che rivede e firma il white paper, poi notifica a CONSOB
  (almeno 20 giorni lavorativi prima dell'offerta).
- **40 SOL** e un wallet di deploy nuovo.
- **Account social** a nome del progetto (X, Telegram).
- Scelta se metterci la faccia: un team riconoscibile e' il segnale di
  legittimita' piu' forte, ma e' una scelta personale.

Sequenza: societa' -> white paper firmato e notificato -> social e dominio
-> creazione del token (mint e freeze revocati, metadati immutabili) ->
stream di vesting -> pool con LP bruciato -> indirizzo pubblicato su `/engn`
-> profilo DexScreener, RugCheck, CoinGecko.

## Cose che non hai chiesto ma servono

- **MiCA (UE).** Offrire un cripto-asset al pubblico dall'Italia richiede un
  white paper notificato a CONSOB, salvo esenzioni (offerta sotto 1 M EUR in
  12 mesi, meno di 150 persone per Stato, o token gratuiti). Da verificare con
  un legale **prima** del lancio. La pagina gia' dice che il white paper
  uscira' prima dell'offerta.
- **Disclaimer** gia' in pagina: token di utilita', nessuna promessa di
  rendimento ne' quota di ricavi, niente persone USA. Niente "buyback" o
  "revenue share": renderebbero il token simile a uno strumento finanziario.
- **Chiavi.** Wallet del deploy nuovo, usato una volta; mint e freeze
  revocati subito; metadati immutabili; tesoreria su multisig 2-su-3.
- **Vesting on-chain** (Streamflow o simile) con link pubblici agli stream.
- **Indirizzo del contratto** pubblicato solo su `/engn` e sui social
  ufficiali: la pagina ha gia' il riquadro "CA not launched yet".
- **Social da registrare prima dell'annuncio:** X @liquidityengine (o
  @engn_app), Telegram, GitHub pubblico. I link in fondo alla pagina sono
  segnaposto.
- **Dopo il lancio:** profilo DexScreener (logo, sito, social), domanda a
  CoinGecko / CoinMarketCap, RugCheck pulito, Jupiter strict list.
- **Track record pubblico** del pilota: e' l'argomento piu' forte, e oggi
  nessuna strategia ha un edge dimostrato (vedi `CLAUDE.md`) — la pagina non
  promette numeri.
- **Tasse:** plusvalenze cripto in Italia al 26% (33% dal 2026): sentire un
  commercialista per le quote team/tesoreria.

## Roadmap mostrata

LIVE l'app · Fase 1 lancio · Fase 2 livelli per chi detiene · Fase 3 nuove
strategie trend-following, nuove chain, track record pubblico.
