# ENGN Motion Kit

Pacchetto di animazioni e componenti per Liquidity Engine, preparato dal cubo Meshy dell'utente e dal sito getengn.xyz. Include un prototipo navigabile, asset riutilizzabili e istruzioni per Claude. Non modifica il sito pubblico, i dati, il wallet o il trading.

## Avvio

Servire questa cartella tramite HTTP, ad esempio `python -m http.server 8765`, poi aprire `http://localhost:8765/`. Gli SVG funzionano anche come normali immagini. I moduli JavaScript e le scene 3D richiedono un server HTTP/HTTPS.

## Contenuto

| File | Uso |
| --- | --- |
| `index.html` | Galleria interattiva desktop e mobile |
| `engn-motion.mjs` | Web component leggero con 12 stati animati |
| `svg/*.svg` | 12 versioni autonome senza JavaScript |
| `engn-leaderboard.mjs` | Proposta di classifica con podio, ricerca e Top 15/25/50 |
| `podium-adapter.mjs` / `.css` | Adattatore del contratto `renderPodium` già presente nel repository |
| `hero-3d.html` / `.js` | Assemblaggio del modello originale in esattamente 3 secondi |
| `podium-3d.html` / `.js` | Tre istanze del modello originale, caricato una volta |
| `neon-cube-assembly-3s.glb` | Modello originale suddiviso in 27 moduli; texture web a 1024 px |
| `motion-manifest.json` | Catalogo, durate e palette |
| `CLAUDE.md` | Handoff con file e contratti verificati nella repository |

Il GLB web pesa circa **2 MB**, contro 20,7 MB della versione iniziale. Sono state eliminate le porzioni di buffer non utilizzate e ridotte le texture originali, senza sostituirle con nuove immagini. La base del modello è stata rimossa; i tagli interni hanno nuove facce metalliche. Gli SVG sono interpretazioni vettoriali leggere del cubo, non rendering del GLB.

## Uso del componente

```html
<script type="module" src="/motion/engn-motion.mjs"></script>
<engn-motion id="engine-status" state="scan"
  label="Scansione in corso" style="width:80px"></engn-motion>
```

```js
const motion = document.querySelector('#engine-status');
motion.state = 'loading';     // attesa indeterminata
motion.state = 'progress';
motion.progress = 64;         // percentuale reale ricevuta dal processo
motion.state = 'success';     // solo dopo conferma reale dell'operazione
motion.play('assemble');      // ripete la clip di 3 secondi
motion.setAttribute('paused', '');
motion.removeAttribute('paused');
```

Attributi: `state`, `progress` (0–100), `label`, `paused`, `decorative`. Con `decorative` l'icona non viene annunciata ai lettori di schermo. Per comunicare aggiornamenti usare un messaggio testuale esterno `role="status"`; non annunciare ogni fotogramma.

Colori configurabili: `--engn-accent`, `--engn-muted`, `--engn-warning`, `--engn-error`. Il cambio stato è controllato dall'app; non esistono timer che trasformano automaticamente un'attesa in successo. `success` conferma un processo, non la sicurezza o redditività di un token.

Gli stati continui sono `idle`, `scan`, `loading` e `reconnect`. Le animazioni si fermano fuori schermo e con la scheda nascosta. `prefers-reduced-motion` mostra stati statici. Le scene 3D usano Three.js 0.180.0 da jsDelivr; nessuna dipendenza esterna per gli SVG o i due web component.

## Classifica

```html
<script type="module" src="/motion/engn-leaderboard.mjs"></script>
<engn-leaderboard id="ranking"></engn-leaderboard>
```

```js
const ranking = document.querySelector('#ranking');
ranking.items = [{ id: 'gem:solana:ADDRESS', name: 'Project',
  symbol: 'TOKEN', score: 84, chain: 'Solana', rankDelta: 2 }];
ranking.addEventListener('engn-select', ({detail}) => {
  // Collegare detail.item.id al router dettaglio già presente.
});
ranking.addEventListener('engn-limit-change', ({detail}) => {
  // detail.limit = 15, 25 oppure 50.
});
```

Il componente demo ordina i dati per score e non riproduce tutte le metriche dell'app live. È una proposta visiva: per l'integrazione conservare `top.js`, i filtri, gli id e le righe reali, come descritto in CLAUDE.md. Gli score della galleria sono illustrativi, anche quando il nome del progetto è tratto dall'interfaccia osservata.

## Scena 3D

```html
<iframe src="/motion/hero-3d.html?embed=1"
  title="Assemblaggio del cubo ENGN"
  style="width:100%;height:420px;border:0" loading="lazy"></iframe>
```

`embed=1` nasconde le scritte della scena hero. Il GLB contiene i movimenti; bagliori, scie e impulsi luminosi sono effetti JavaScript del renderer. La posa finale viene mantenuta dopo 3 secondi. Non è un video MP4.

## Responsive e accessibilità

- Verificare viewport reali a 1440×1000 e 390×844; non basta ridimensionare una card nella stessa pagina.
- La classifica usa container query: funziona anche nella colonna da 420 px del terminale desktop.
- La repository passa al desktop a 1100 px e aggiunge il rail di trading a 1360 px: preservare entrambi.
- Usare SVG negli elenchi; non caricare un renderer 3D per ogni riga.
- Mantenere pulsanti nativi, focus visibile, etichette e testo di stato.

## Provenienza

Riferimenti: [sito ENGN](https://getengn.xyz/), [GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html), [UnrealBloomPass](https://threejs.org/docs/pages/UnrealBloomPass.html). Repository analizzata: `snowcomingsoon/liquidity-analysis-engine`, `main`, al momento della preparazione. Nessuna credenziale inclusa.
