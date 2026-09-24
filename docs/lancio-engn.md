# Lancio $ENGN — piano

Stato: **bozza, niente e' stato lanciato o pubblicato fuori dal sito.** Ogni
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

## Cose da decidere con Lorenzo

1. **Pagina alla radice?** Oggi e' su `/engn`; `/` resta l'app. Proposta:
   dominio separato o `/` solo per chi non ha fatto login.
2. **Modalita' di lancio.** Consiglio: pool Raydium CPMM o Meteora con LP
   bruciato, non pump.fun — la nostra stessa regola dice "niente memecoin" e
   pump.fun lo fa sembrare tale.
3. **Liquidita' iniziale** in SOL: decide quanto vale il token al minuto zero.
   Esempio: 45% dell'offerta + 50 SOL -> cap iniziale ~111 SOL.
4. **Commissione di swap nell'app** (serve a dare senso ai livelli).

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
