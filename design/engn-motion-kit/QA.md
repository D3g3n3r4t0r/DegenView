# Verifica del pacchetto

## Controlli eseguiti

- Sintassi Node dei sei moduli JavaScript: valida.
- Galleria aperta nel browser a **1440×1000** (dimensioni lette dalla pagina).
- Galleria aperta a **390×844**; larghezza del documento 375 px, senza overflow orizzontale.
- Top 25: mostrati 25 di 50 progetti demo.
- Top 50: mostrati 50 di 50 progetti demo.
- Ricerca `Paraloom`: mostrato 1 di 50 progetti.
- Selezione della prima riga: evento `engn-select` con simbolo PARALOOM.
- Simulatore: stato progress, modifica a 82%, stato error e relativo testo.
- Rendering WebGL del podio: modello caricato e visualizzato nel browser.
- Assemblaggio originale: stop a 3.00 s verificato nell'anteprima; timeline GLB controllata a 3 secondi.
- GLB web: 27 mesh/moduli; texture originali ridotte a 1024 px; buffer inutilizzati rimossi.

## Limiti della verifica

Il pacchetto è autonomo e non è stato collegato al backend o al wallet. Le metriche demo non sono risultati finanziari. L'adattatore del podio rispetta il contratto sorgente osservato ma richiede la verifica integrata con `top.js` e il CSS del progetto. Reduced motion e sospensione fuori schermo sono implementati; prima del rilascio verificare anche con preferenze di sistema e dispositivi fisici. Non è stata eseguita una misura di frame rate su smartphone.

Durante le interazioni il browser ha riportato un errore MutationObserver privo di URL sorgente; i controlli descritti sopra hanno funzionato e il pacchetto non usa direttamente MutationObserver. Non attribuito a una causa verificata: ricontrollare nella console del browser di destinazione.
