# Handoff per Claude — ENGN motion / podium / responsive

## Richiesta di Lorenzo

"Prepara un pacchetto di animazioni su questa falsa riga del cubo adatte allo scopo", "da inserire in più contesti; funzionali e meno", "anche i modelli della leaderboard top 15 [...] vanno aggiornati con qualcosa di figo e animato", "sistema sia per desktop che per mobile", "per desktop poi visualizzalo versione desktop sennò non lo vedi". L'assemblaggio hero deve durare esattamente 3 secondi e fermarsi sul cubo completo.

Questo è un pacchetto di design e prototipi da integrare. Non è un'integrazione già eseguita nell'app. Leggi prima il CLAUDE.md alla radice della repository e HANDOVER.md; questo documento aggiunge le indicazioni specifiche del motion kit e non li sostituisce. Mantieni il workflow di sviluppo/delega richiesto dal progetto per l'implementazione futura.

## Repository e punti verificati

Repository: `snowcomingsoon/liquidity-analysis-engine`. Frontend vanilla JS, backend FastAPI. `main` attiva il deploy: lavorare su branch e PR, senza merge o deploy implicito per la sola consegna di questi asset.

| File esistente | Ruolo e integrazione |
| --- | --- |
| `frontend/engn.html` | Landing getengn.xyz: mantenere copy, CTA, struttura e tokenomics; usare l'hero 3D solo come sostituzione del visual del cubo |
| `frontend/onchain-app.html` | Shell, import map e mount dei componenti dell'app |
| `frontend/static/onchain/podium.js` | Contratto `renderPodium(container, items, { still = false })` |
| `frontend/static/onchain/top.js` | Top 15/25/50, polling a 30 s, filtri narrative, token nascosti, ordine persistito e animazioni dei cambi classifica |
| `frontend/static/onchain/leaderboard.js` | Leaderboard delle strategie: contesto diverso dalle Gems; non introdurre il podio dove la richiesta esistente lo esclude |
| `frontend/static/onchain/app.css` | `.pod-cy`, `.pc-*`, breakpoints desktop 1100/1360 px e layout a pannelli |
| `frontend/static/onchain/format.js` | `tile` e `tokenRow`: mantenere loghi reali, market cap, 24h, età e backtest |
| `frontend/static/onchain/detail.js` | Apertura del dettaglio via id registrato e `data-open` |
| `frontend/static/onchain/agent.js`, `radar.js`, `live.js` | Possibili destinatari degli stati scan/loading/reconnect; collegare a eventi reali |
| `frontend/static/fonts/` | Geist, Geist Mono, Instrument Serif: riusare i font locali già presenti |

Gli esempi nel kit usano fallback di sistema per restare autonomi. In produzione adottare le variabili e i font della repository.

## Priorità di integrazione

1. **Gems / Top 3**: usare `podium-adapter.mjs` + `.css` come candidato al nuovo renderer mantenendo il contratto pubblico. Il file viene consegnato separato; non è già importato da `top.js`. Esempio di re-export da `podium.js`, adattando il percorso alla cartella scelta:

   ```js
   export { renderPodium } from '../engn-motion-kit/podium-adapter.mjs';
   ```

   Prima di applicarlo verificare tutti i chiamanti. I nomi naturali delle `.pc-slot` devono restare nell'ordine 1,2,3 nel DOM: il layout visuale 2,1,3 è ottenuto con CSS `order`. `top.js` accede agli slot per indice. Conservare `data-open`, `pc-taken`, `pc-prev` e il parametro `still`. `logoHtml` va prodotto esclusivamente dal helper `format.tile()` esistente; non passare HTML remoto non verificato.

2. **Top 15/25/50**: la galleria `engn-leaderboard` mostra gerarchia, ritmo, selezione, filtri e ricerca. Non sostituire `top.js` con i dati demo. Integrare lo stile sulle righe `tokenRow` conservando cap, cambio 24h, età, backtest, collegamento al dettaglio e filtri. Non convertire i punteggi illustrativi del prototipo in dati live.

3. **Cambi di classifica**: mantenere `lae:top`, `lae:top-seen`, l'ordine di `/api/onchain/top`, narrativa, hidden tokens e `still` quando il podio non cambia. Il sistema corrente rinvia le animazioni fino alla visibilità: preservarlo. Animare solo righe cambiate; non rigiocare tutte le entrate ogni 30 secondi. Non segnare un nuovo ordine come visto prima che l'utente lo abbia realmente visto.

4. **Landing / hero**: usare `hero-3d.html?embed=1` come prototipo o trasferire il renderer nel sistema di asset. Timeline: 0–0,3 s esploso; 0,3–1,8 s assemblaggio; 1,8–2,3 s impulso; 2,3–3 s presentazione e stop. Il file GLB viene dall'asset Meshy fornito dall'utente, tagliato in 27 moduli, con texture originali ridotte a 1024 px. Pedana rimossa, interni aggiunti. Non sostituirlo con una forma generica.

5. **Podio 3D**: `podium-3d.html` è la variante ricca con tre istanze dello stesso GLB, una sola richiesta dell'asset. Le etichette sono dimostrative e devono essere collegate ai primi tre progetti reali. Usarlo in un contesto ampio, caricandolo pigramente; preferire il renderer SVG nella lista compatta.

6. **Stati funzionali**: `engn-motion.mjs` è indipendente e non richiede Three.js. Mappare eventi reali: scan durante scansione; loading per attesa indeterminata; progress soltanto se il backend fornisce una percentuale; success solo dopo conferma; error per errore recuperabile; empty se la lista è vuota; reconnect durante la riconnessione. Nessun finto successo di trading, saldo, connessione o controllo di sicurezza. Usare testi del prodotto, non i titoli della galleria.

## Desktop e mobile: vincoli reali

Il CSS esistente ha un terminale desktop **a partire da 1100 px**. Sotto tale soglia il layout resta compatto. Nel desktop `--desk-list` vale 420 px; a 1360 px appare il rail di trading da 320 px. Una finestra da 1049 px NON verifica la versione desktop.

- Aprire davvero la pagina a **1440×1000** e **390×844** e misurare `window.innerWidth` nel browser.
- A 1440 px conservare header con sezioni, lista a sinistra e dettaglio a destra. Non trasformare il terminale in una leaderboard gigante perché la galleria è a tutta larghezza.
- A 390 px conservare dock, safe area, loghi reali e aperture del dettaglio. Nessuno scroll orizzontale, testo troncato solo dove già previsto.
- Il prototipo usa **container query** per adattarsi anche alla lista da 420 px dentro il desktop.
- Controllare anche 1099/1100 e 1359/1360 px per i due cambi di layout.

## Prestazioni e accessibilità

- SVG/CSS per icone, stati e righe; un solo WebGL canvas visibile dove serve.
- Il GLB web è circa 2 MB. Mantenere il file binario fuori dal bundle JS. Riutilizzare geometrie e texture per i tre cubi.
- Limite pixel ratio, caricamento lazy, animazioni in pausa fuori schermo e a documento nascosto.
- Tutte le clip rispettano `prefers-reduced-motion`; l'hero mostra direttamente la posa finale.
- Stato comunicato anche da testo; focus da tastiera visibile; `decorative` sulle icone ridondanti.
- La galleria usa CDN Three.js 0.180.0. Per produzione verificare CSP e politiche del progetto; ospitare le dipendenze localmente se necessario.
- Nessun MP4 incluso: il pacchetto contiene animazioni web, SVG e GLB.

## Verifica prima della PR di integrazione

1. Sintassi dei moduli modificati e import map `@onchain` valida.
2. Top 15,25,50; filtri narrativa; token nascosti; click su podio e righe; dettaglio corretto.
3. Confronto ordine precedente/nuovo, nuovo #1, scheda nascosta, ritorno alla pagina: nessun replay spurio o stato segnato come visto troppo presto.
4. Metriche vere invariate, incluse backtest negativi e assenza di entry.
5. Screenshot desktop 1440 e mobile 390, nessun overflow; tastiera e reduced motion.
6. Errori WebGL/rete: fallback statico o SVG leggibile, nessun pannello vuoto.
7. Eseguire le verifiche richieste da CLAUDE.md radice per il codice effettivamente toccato; aggiornare HANDOVER.md con ciò che è stato integrato e ciò che resta.

## Stato della consegna

Consegna di asset, prototipi e istruzioni; gli import e i renderer di produzione non sono stati modificati. La galleria include dati esplicitamente dimostrativi. La successiva implementazione deve avvenire nella repository, preservando i flussi reali.
