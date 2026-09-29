# Piano operativo per Claude
Audit del 29/09/2026 su ceef100a04a3a48dbef74137875ddd40ddc399ed.

## Mandato

Lorenzo ha chiesto un audit di sicurezza da pubblicare su GitHub per far correggere i problemi a Claude, un'analisi approfondita dei punti forti/deboli e una revisione critica dei pesi GitHub/sito/tokenomics. Questa consegna contiene la diagnosi e una proposta verificabile; **non applica patch al codice eseguibile e non modifica la produzione**.

Leggere AUDIT_SICUREZZA.md e ANALISI_E_PESI.md. Verificare se il ramo corrente ha già corretto ciascun problema rispetto allo snapshot; evitare patch duplicate. Gli ID sono stabili e ogni PR deve citarli.

Non attribuire a Claude l'avvio di un lavoro che non risulta effettivamente avviato. La presenza dell'issue è il passaggio di consegna, non un'esecuzione automatica. Le attività che toccano fondi, firme o chiavi richiedono revisione diretta del responsabile del codice; non farle partire tramite etichetta DeepSeek.

## P0 — Invarianti dei fondi (S01–S04)

### PR A: policy obbligatoria prima di ogni operazione

File: backend/app/main.py; backend/app/trading/onchain/{execute,send,risk,autotrader,twap_jobs}.py e chiamanti degli ordini limite.

- [ ] Controllo centralizzato di master/live/wallet enabled, owner, breaker, discrepanze e pending non risolti.
- [ ] Policy riletta prima del broadcast anche dopo attese di rete.
- [ ] Eliminare il bypass indistinto guards=False; mantenere separata l'eventuale scelta autorizzata di size percentuale.
- [ ] Identificare anche approve e trasferimenti intermedi come operazioni con fondi.
- [ ] Test matrice di tutti i percorsi, inclusi wallet spento durante quote/firma.

Done: nessun percorso può inviare dopo stop o con contabilità incerta.

### PR B: quantità attendibile e limiti atomici

File: main.py, execute.py, send.py, quotes.py, risk.py, ledger.py.

- [ ] Prezzi, quantità raw, decimali e token derivati/verificati lato server.
- [ ] Clamp seguito da nuovo quote/importo raw coerente oppure rifiuto.
- [ ] Validazione finitezza, positività, unità e bounds slippage.
- [ ] Intent ID stabile con payload hash e scope utente; non usare UUID nuovo per ogni retry.
- [ ] Riserva atomica del budget che includa pending/submitted e lock del nonce per wallet.
- [ ] Transizioni ledger idempotenti.
- [ ] Test retry paralleli, cambio payload stesso ID, tetto giornaliero concorrente e doppia conferma.

Done: una sola operazione economica per intento e nessun importo superiore al limite realmente autorizzato.

### PR C: stato chain e recovery

File: execute.py, send.py, execution.py, reconciliation.py, ledger.py, jito.py, autotrader.py.

- [ ] ACK → submitted, non confirmed; timeout ambiguo → unknown.
- [ ] Persistenza hash/signature prima dell'invio e recovery di tutte le fasi.
- [ ] Receipt, errori, livello di conferma e bundle Jito gestiti correttamente.
- [ ] Fill/fee/saldi effettivi prima di aggiornare posizione e P&L.
- [ ] Test crash nei punti di transizione, dropped/reverted/timeout/reorg secondo chain, double-callback.

Done: nessun successo dichiarato soltanto perché il broadcaster ha risposto.

## P1 — Auth e custodia (S05–S07)

### PR D: autenticazione sensibile e revoca

File: auth.py, main.py, passkey.py, reveal_requests.py, rate_limit.py, frontend relativo.

- [ ] Reautenticazione con fattore già fidato per aggiungere/rimuovere passkey.
- [ ] Grant breve vincolato ad azione, wallet e identità; decisione esplicita su recupero account.
- [ ] Rate limit login/approve coerente; nessuna apertura anonima accidentale per risolvere il QR.
- [ ] Logout/revoca server-side e possibilità di revocare tutte le sessioni.
- [ ] Test end-to-end con middleware attivo, sessione sottratta fittizia, utenti differenti e vere cerimonie WebAuthn in laboratorio.

### PR E: cifratura e persistenza

File: trading/crypto.py, auth.py, modelli e migrazioni dati.

- [ ] AEAD standard, chiave distinta da session signing, associated data e versione.
- [ ] Migrazione recuperabile dei ciphertext esistenti; verifica indirizzo wallet prima/dopo.
- [ ] Scritture utenti transazionali, segnalazione di corruzione, prova di restore da backup.
- [ ] Test tamper, wrong key, scambio fra utenti, migrazione ripetuta e interruzione durante migrazione.

Non cambiare SESSION_SECRET come scorciatoia per revocare sessioni: nello stato attuale è anche la radice della cifratura.

## P1 — Integrità delle valutazioni (M01–M07)

### PR F: fatti mancanti, concentrazione e policy unica

File: depth.py, leaderboard.py, main.py (_top_entries), projects_db.py, judge.py.

- [ ] Ogni osservazione distingue verified/claimed/unknown/stale/not_applicable.
- [ ] Contratto holder escluso solo con ruolo verificato; nessuna equazione “contratto = non balena”.
- [ ] Mancanza mint/freeze/tasse/holder/LP non può diventare controllo positivo.
- [ ] DREGG sottoposto agli stessi gate; menzione d'onore separata.
- [ ] Top/Gems/Database/notifiche usano la stessa idoneità; vista esplorativa distinta.
- [ ] AI non può derogare a gate di sicurezza; ammissioni non basate soltanto sul suo voto.
- [ ] TTL applicata all'uso del giudizio, invalidazione per nuovi fatti/prompt/modello.
- [ ] README GitHub decodificato, codice fissato a commit e campione per ruolo.
- [ ] Rivalutazione delle righe già salvate, version bump e migrazione; non basta correggere i nuovi candidati.

Done: i casi riprodotti M01/M02/M03/M05/M06 vengono respinti o mostrati esplicitamente non verificati; M04 espone il contributo effettivo; M07 invia testo decodificato.

## P2 — Spiegabilità e confronto dei modelli

### PR G: explain_score e snapshot riproducibile

- [ ] Funzione unica che restituisce score_version, input hash, qualità, idoneità, copertura e contributi.
- [ ] UI con formula effettiva, dati mancanti, età e motivi di esclusione.
- [ ] Snapshot immutabili degli input al momento della decisione, inclusi candidati scartati.
- [ ] Test di somma contributi, monotonicità dove prevista, nessun premio per dato mancante, uguaglianza fra viste.
- [ ] Nessun aggiornamento del totale solo per l'arrivo di una review senza indicarne il motivo.

### PR H: modello proposto in parallelo

Pesi iniziali di qualità: prodotto 25%, adozione 25%, engineering 20%, economia token 20%, trasparenza 10%; sicurezza/idoneità separata. Sito e GitHub sono fonti. Narrativa e somiglianza al benchmark diventano filtri. AI spiega e raccoglie evidenze, peso diretto iniziale zero.

- [ ] Implementare la nuova versione senza sostituire subito la baseline.
- [ ] Benchmark temporale e per cluster di progetto; parametri e target congelati prima del test.
- [ ] Ablation senza AI/GitHub/narrativa/somiglianza; confronto con baseline semplici.
- [ ] Risultati comprensivi di falsi negativi, costo API, copertura e intervalli di incertezza.
- [ ] Promozione soltanto dopo evidenza, senza ritoccare i pesi per far risalire nomi desiderati.

Questi pesi sono una proposta motivata, non un modello validato. Non è necessario aspettare questa fase per correggere i gate palesemente errati.

## P2 — Operatività e isolamento

- [ ] Ripristinare GitHub Actions; il run 36541914731 è fallito senza step e deploy skipped. Verificare la causa, non attribuirla senza prove ai test.
- [ ] Stesso Python fra CI/runtime, build riproducibile e scansione dipendenze.
- [ ] Deploy dello SHA/digest verificato, non origin/main mobile.
- [ ] Separare job AI che esegue codice generato e publisher con credenziali.
- [ ] Ricerca/renderer senza accesso alle chiavi, egress controllato; signer con API minima.
- [ ] Healthcheck funzionale su freschezza scanner, queue e riconciliazione; piano rollback/restore.
- [ ] Estrarre router/servizi da main.py progressivamente, senza riscrittura totale.

## Prove allegate e come usarle

Eseguire con Python 3.12:
    
    python docs/audits/2026-09-29/reproduce_audit.py .

Il test runner usa soltanto libreria standard. Estrae le funzioni dal repository indicato, rimuove i decoratori e sostituisce i default Depends per poter chiamare direttamente i corpi; il resto della logica delle funzioni selezionate resta originale. La rete e la firma sono simulate; il ledger usa un database temporaneo. Non importa l'app né avvia servizi. Un test statico controlla l'assenza della lettura di enabled nei tre endpoint diretti.

Lo snapshot originario produce 18 REPRODUCED, come proof-results.json. **Non sono 18 vulnerabilità distinte**: alcuni casi dimostrano più aspetti della stessa causa, altri verificano la formula. Dopo le correzioni è normale che questi assert di caratterizzazione non passino: sostituirli con test di regressione che esigano il comportamento corretto e completare la suite applicativa.

Le prove non autorizzano accessi alla produzione o transazioni reali. La consegna è completa quando le PR di remediation riportano test nuovi, suite pertinente, eventuali limiti residui e commit realmente distribuito.

