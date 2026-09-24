# Lancio $ENGN — piano

Stato: **pronto, in attesa del via di Lorenzo. Niente e' stato lanciato.** Ogni
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

## Tokenomics (pump.fun)

Lorenzo, 24/09: "noi utilizzeremo pump fun per lanciare la cripto e non
andremo a fare nessun tipo di attivita' di MiCA compliant". Poi: "aspetta a
lanciare i token ovviamente". Il white paper MiCA e' stato tolto.

Pump.fun decide l'offerta: 1 000 000 000 token, mint e freeze revocati,
nessuna tassa. Circa 79,3% si vende sulla curva; alla laurea circa 20,7% va
in liquidita' su PumpSwap con LP bruciato. Nessuna prevendita, nessuna quota
al team.

- **Team: 0%.** Lorenzo: "per la liquidita' come facciamo? Io non voglio
  mettere soldi". Su pump.fun non serve: la liquidita' la fanno i compratori
  sulla curva e alla laurea passa da sola su PumpSwap. Nessun dev buy.
- **Fondi di sviluppo:** le creator fee di pump.fun.
- **Utilita' (fase 2):** livelli per saldo del wallet collegato — Scout
  gratis (radar con 15 min di ritardo), Sniper 250k (tempo reale, classifica
  completa), Engine 1M (strategie automatiche, accesso anticipato). Nessuna
  commissione di swap nell'app.

## Kit per il form di pump.fun

File in `/mnt/project-files/lancio/pumpfun/`.

| campo | valore |
|---|---|
| Name | Liquidity Engine |
| Ticker | ENGN |
| Image | `engn-logo-1000.png` |
| Banner | `engn-banner-1500x500.png` |
| Website | https://liquidityengine.app/engn |
| X / Telegram | da creare prima del lancio |

Description:

> On-chain wallet that snipes new launches, ranks serious microcaps and
> trades them with trend-following. Long spot only. Live before the token:
> liquidityengine.app/engn

## Sequenza di lancio (solo col via di Lorenzo)

1. Creare X e Telegram del progetto, metterli nel footer di `/engn`.
2. Wallet di deploy nuovo, con pochi centesimi di SOL per la creazione.
3. Creare il token su pump.fun con il kit sopra, senza dev buy.
4. Pubblicare l'indirizzo su `/engn` (riquadro "CA") e sui social.
5. Dopo la laurea: profilo DexScreener (logo, banner, sito, social),
   RugCheck, domanda a CoinGecko.

## Rischi da sapere

- Pump.fun fa sembrare il token un memecoin, e il nostro radar scarta i
  memecoin: la pagina e il prodotto live sono cio' che lo distingue.
- Niente MiCA e' una scelta di Lorenzo: la pagina non ne parla piu'.
- Nessuna strategia ha un edge dimostrato (vedi `CLAUDE.md`): la pagina non
  promette numeri e lo dice.
- Ticker falsi: l'unico indirizzo valido e' quello pubblicato su `/engn`.
