# Audit di sicurezza — Liquidity Analysis Engine
Data: 29 settembre 2026. Autore: Codex. Destinatario delle correzioni: Claude.

## Esito e perimetro

Il progetto contiene protezioni utili, ma **non considererei sufficientemente affidabile l'esecuzione con fondi reali prima di correggere S01–S05**. Il problema principale è la distanza fra protezioni dichiarate e comportamento effettivo: spegnimento del wallet, limiti di spesa, deduplicazione e conferma degli ordini non sono applicati in modo coerente. Questo è un giudizio sul codice esaminato, non una dichiarazione di compromissione avvenuta.

Snapshot analizzato: **ceef100a04a3a48dbef74137875ddd40ddc399ed**, ramo main, repository privato. Acquisiti 367 file testuali: analisi approfondita dei percorsi di autenticazione, wallet, execution/risk/ledger/reconciliation, scoring, automazioni e deploy; ricerche trasversali e ispezione dei test pertinenti. Non significa revisione riga per riga di tutti i file.

Prove: **18 verifiche offline riproducono i comportamenti descritti**, una delle quali è un controllo statico del codice; le altre usano funzioni originali estratte tramite AST, adattatori fittizi e un database SQLite temporaneo. Il dettaglio è in proof-results.json e reproduce_audit.py. Un esito REPRODUCED conferma il difetto o la formula descritta, NON certifica sicurezza. Nessuna firma reale, transazione o richiesta offensiva alla produzione.

Non eseguita l'intera suite pytest: nell'ambiente di audit mancano pytest e varie dipendenze applicative. Le prove isolate non verificano integrazione HTTP, WebAuthn completo, RPC reali, configurazione/permessi del server, backup, segreti, dipendenze transitive o smart contract di terzi. Non assegno CVSS fittizi senza conoscere esposizione e configurazione reali.

### Stato del deploy osservato

Il [run 36541914731](https://github.com/snowcomingsoon/liquidity-analysis-engine/actions/runs/36541914731) relativo allo snapshot risulta failure; il job “Lint e test” non riporta step eseguiti, runner_id 0; “Deploy” è skipped. Anche gli altri quattro run più recenti consultati risultavano failure. La causa non è determinabile da questo dato e **non equivale a test del codice falliti**. La versione effettivamente online resta da verificare.

## Priorità

| ID | Gravità | Problema | Evidenza |
|---|---|---|---|
| S01 | Alta | Spegnimento wallet non applicato ai percorsi diretti; autotrader salta breaker e discrepanze | Codice + prova offline breaker |
| S02 | Alta | Importi/prezzi del client governano i limiti; riduzione USD non riduce la transazione | Prova offline + tracciamento endpoint |
| S03 | Alta | Retry e concorrenza possono duplicare ordini e superare il tetto giornaliero | Tre prove offline |
| S04 | Alta | Broadcast scambiato per conferma; recovery incompleto | Due prove offline + codice |
| S05 | Alta | Una sessione può aggiungere una propria passkey e promuoversi ad autorizzazione export | Tracciamento codice; WebAuthn completo non eseguito |
| S06 | Media | Logout non revoca una copia del cookie | Prova offline |
| S07 | Media | Cifratura personalizzata senza autenticazione del ciphertext e root key condivisa | Prova offline + codice |

Le gravità di esecuzione presuppongono wallet finanziato ed esecuzione reale abilitata. Non dimostrano prelievo da remoto senza autenticazione. Un cookie compromesso ha però una capacità molto ampia sui fondi custoditi dal server.

## S01 — Arresto del wallet e protezioni minime aggirabili

**Riferimenti:** [backend/app/main.py:2695](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2695), [backend/app/main.py:3493](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3493), [backend/app/main.py:3543](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3543), [backend/app/main.py:3597](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3597), [backend/app/trading/onchain/execute.py:112](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/execute.py#L112), [backend/app/trading/onchain/risk.py:144](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/risk.py#L144), [backend/app/trading/onchain/autotrader.py:315](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/autotrader.py#L315).

Il pulsante wallet aggiorna enabled e annuncia che nessun nuovo ordine partirà. I tre endpoint diretti controllano che il wallet esista, non che enabled sia vero. Il livello comune execute_order/risk non legge quel flag. Non basta che alcuni percorsi automatici lo controllino: chiamare direttamente l'API resta possibile per la sessione proprietaria.

Inoltre guards=False nell'autotrader salta **tutta** run_all_checks, compresi circuit breaker e discrepanze contabili. La preferenza “usa soltanto la percentuale scelta” può giustificare limiti economici diversi, ma non implica automaticamente ignorare lo stato di emergenza o una riconciliazione fallita.

**Prova:** breaker attivato dopo cinque perdite; execute_order(..., guards=False) viene accettato con adattatore di invio fittizio.

**Correzione:** controlli obbligatori comuni prima della firma e nuovamente prima del broadcast: master switch, live switch, wallet corrente abilitato, proprietario, breaker, riconciliazione e autorizzazione dell'operazione. Separare queste invarianti dai limiti di strategia configurabili. Caricare lo stato aggiornato, non fidarsi di un oggetto utente acquisito prima di attese di rete.

**Accettazione:** per swap, send, TWAP, limit order, autotrader e approve, wallet disabilitato o breaker attivo implica zero chiamate al signer/broadcaster; test anche su disabilitazione durante un'attesa.

## S02 — Il tetto limita il numero registrato, non necessariamente i fondi movimentati

**Riferimenti:** [backend/app/main.py:3521](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3521), [backend/app/main.py:3530](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3530), [backend/app/main.py:3577](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3577), [backend/app/main.py:3589](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3589), [backend/app/main.py:3628](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3628), [backend/app/trading/onchain/execute.py:90](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/execute.py#L90), [backend/app/trading/onchain/risk.py:90](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/risk.py#L90).

Il client dichiara notional_usd e price_usd; gli importi raw usati per costruire lo swap sono campi separati. Per i trasferimenti il server moltiplica amount per un price_usd fornito dal browser. Una richiesta può dichiarare un valore USD piccolo per una quantità grande.

Anche con client onesto esiste un secondo difetto: clamp_size_to_pool riduce notional_usd, ma il quote e amount_in rimangono invariati. I controlli e il ledger vedono la quantità ridotta; il signer riceve quella originale.

**Prova:** richiesta USD 1.000, cap USD 100, liquidità fittizia USD 100.000: ledger registra 100, mentre il costruttore della transazione riceve ancora amount_in=1000. Non è una misura di prezzo reale: la prova dimostra il mancato collegamento fra riduzione e importo raw.

**Correzione:** derivare lato server token canonici, decimali, valore, timestamp della quotazione e importo esatto. Se si riduce la size, ottenere un nuovo quote per il nuovo importo; se non è possibile, rifiutare esplicitamente. Usare interi per unità raw e Decimal per conversioni economiche; imporre valori finiti/positivi e bounds di slippage. Verificare che i campi token/side/strategy non permettano di cambiare la policy applicata.

**Accettazione:** client che altera price/notional/token/side, numeri negativi/non finiti, slippage fuori range e quantità oltre limite non ottengono una firma; amount firmato, riservato e contabilizzato sono coerenti.

## S03 — Idempotenza e prenotazione del rischio incomplete

**Riferimenti:** [backend/app/trading/onchain/execute.py:131](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/execute.py#L131), [backend/app/trading/onchain/send.py:58](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/send.py#L58), [backend/app/trading/onchain/ledger.py:132](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/ledger.py#L132), [backend/app/trading/onchain/ledger.py:177](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/ledger.py#L177), [backend/app/trading/onchain/risk.py:21](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/risk.py#L21).

Ogni tentativo genera un nuovo UUID lato server. La chiave primaria impedisce di ripetere lo stesso UUID, ma il retry della stessa richiesta genera un'altra chiave: non è idempotenza dell'intento. Inoltre controllo del budget e reserve non sono una transazione atomica; il budget considera spesa confermata, non importi in volo. Infine mark_confirmed aggiunge quantità e spesa anche se l'ordine era già confermato.

**Prove:** due chiamate identiche sono entrambe accettate con UUID diversi; due ordini concorrenti da USD 100 superano un tetto di USD 150, registrando USD 200; confermare due volte una stessa riga da 10 produce posizione 20.

**Correzione:** chiave d'intento stabile per proprietario e operazione, associata a hash del payload; stesso ID/payload restituisce lo stato esistente, stesso ID/payload diverso dà conflitto. Riservare budget e nonce per wallet atomicamente prima di firmare. Rendere le transizioni ledger condizionali e idempotenti. La strategia deve assegnare un ID stabile al segnale, non reinventarlo a ogni tick.

**Accettazione:** N retry e richieste concorrenti producono una sola operazione; budget include pending/submitted; doppia conferma non cambia quantità né spesa; riavvio conserva deduplicazione.

## S04 — Inviato non significa confermato

**Riferimenti:** [backend/app/trading/onchain/execute.py:168](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/execute.py#L168), [backend/app/trading/onchain/send.py:97](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/send.py#L97), [backend/app/trading/onchain/reconciliation.py:37](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/reconciliation.py#L37), [backend/app/trading/onchain/ledger.py:262](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/ledger.py#L262).

Dopo l'ack del broadcaster, execute_order e send_token chiamano immediatamente mark_confirmed. Quantità/prezzo derivano da valori attesi, non dagli effettivi movimenti on-chain. Il reconciler legge soltanto submitted: questi ordini diventati confirmed troppo presto non vengono controllati.

La documentazione [Solana sendTransaction](https://solana.com/docs/rpc/http/sendtransaction) distingue esplicitamente accettazione da conferma. Il ramo Jito usa inoltre un bundle ID, che non è una normale signature. Un timeout di invio non prova che il nodo non abbia ricevuto la transazione. Le righe pending antecedenti a mark_submitted non sono incluse nel recovery corrente. Anche _solana_signature_status classifica ogni risultato senza err come confirmed senza valutare confirmationStatus.

**Prova:** adattatore che restituisce solo un ack, senza alcun metodo di receipt, produce stato confirmed e nessun ordine da riconciliare; una riga soltanto riservata non appare in pending_unconfirmed.

**Correzione:** stato submitted/unknown finché receipt e livello di conferma non sono verificati; persistere hash/signature derivabili prima dell'invio; riconciliare pending, submitted e unknown; gestire bundle separatamente; ricostruire fill, fee e saldi reali. Timeout ambiguo non autorizza una seconda operazione economica.

**Accettazione:** dropped, reverted, timeout dopo ricezione, blockhash scaduto, processed ma non confirmed, Jito pending e crash nei diversi punti del flusso non generano saldi inventati o doppi invii. Contabilità aggiornata una sola volta dopo successo verificato.

## S05 — Una passkey nuova non prova l'identità del proprietario precedente

**Riferimenti:** [backend/app/main.py:2613](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2613), [backend/app/main.py:2628](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2628), [backend/app/main.py:2645](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2645), [backend/app/main.py:2771](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2771), [backend/app/main.py:2808](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2808), [backend/app/trading/onchain/passkey.py:76](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/passkey.py#L76).

Registrazione/rimozione passkey richiedono soltanto una sessione. La biometria durante la registrazione prova che chi sta usando quel dispositivo può sbloccarlo; non prova che sia il titolare originario del wallet. Con una sessione sottratta, l'attaccante può registrare la propria passkey, richiedere l'export, approvarlo con la credenziale appena aggiunta e consumare il token. Il codice non impone un secondo dispositivo: il QR è presentazione, non vincolo crittografico.

Il percorso password /reveal/approve non usa il limiter del login. Oggi il middleware globale richiede una sessione anche a quei percorsi, contrariamente ai commenti “telefono senza login”: questa incoerenza limita l'accesso anonimo ma non protegge contro un utente autenticato che tenta password altrui. Non correggere l'usabilità aprendo il percorso senza aggiungere protezioni.

**Correzione:** nuova autenticazione con fattore già fidato prima di aggiungere/rimuovere passkey, autorizzazioni brevi vincolate all'azione e al wallet, notifiche e gestione del recupero; throttling per utente/IP/token sugli endpoint di approvazione. Decidere e testare il modello di export: approvazione aggiuntiva, non promessa infondata di due dispositivi. Per trasferimenti irreversibili introdurre autorizzazione legata a destinatario/importo.

**Accettazione:** una sessione da sola non iscrive il fattore che la abilita a esportare la chiave; token non riusabile/cross-user/cross-wallet; abusi vengono limitati. Eseguire veri test WebAuthn in ambiente controllato. Riferimento: [OWASP MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html).

## S06 — Logout locale senza revoca server

**Riferimenti:** [backend/app/auth.py:416](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/auth.py#L416), [backend/app/main.py:2303](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L2303).

Il cookie firmato dura 30 giorni. Logout elimina quello del browser, non invalida una copia già sottratta. Non risulta un registro sessioni o una versione di revoca per utente nel verificatore esaminato.

**Prova:** emettere un cookie fittizio, chiamare il corpo originale di logout e ripassare lo stesso cookie al verificatore: resta valido.

**Correzione:** sessioni revocabili o session_version server-side, revoca per singolo dispositivo e globale, scadenza più breve delle autorizzazioni sensibili. **Accettazione:** cookie copiato respinto dopo logout/revoca; nessuna rotazione improvvisa della root key che renda irrecuperabili i wallet esistenti.

## S07 — Cifratura e separazione dei segreti da rafforzare

**Riferimenti:** [backend/app/trading/crypto.py:7](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/crypto.py#L7), [backend/app/auth.py:39](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/auth.py#L39), [backend/app/auth.py:59](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/auth.py#L59).

La cifratura XOR con keystream HMAC non include un tag di autenticazione. Il ciphertext è malleabile: modificando un byte si può modificare il plaintext senza errore. Il controllo indirizzo della chiave on-chain è una difesa utile contro corruzioni, ma non sostituisce AEAD e non copre le credenziali exchange allo stesso modo.

La chiave on-chain deriva da SESSION_SECRET. La derivazione separa gli usi, ma conoscere la root permette comunque di derivare la chiave e firmare sessioni: non è isolamento fra compromissione dell'auth e custody.

**Prova:** con segreto e testo fittizi, modifica del ciphertext trasforma AAA in BAA senza errore.

**Correzione:** libreria AEAD consolidata, chiave di cifratura separata e versionata, associated data con user/chain/key-version; migrazione con backup cifrato e controllo di corrispondenza degli indirizzi. Separare signer e scraper come obiettivo architetturale. **Accettazione:** tamper/troncamento/chiave errata/scambio fra utenti vengono rifiutati; migrazione idempotente senza perdita di fondi. Riferimento: [OWASP Cryptographic Storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html).

## Rischi ulteriori e verifiche ancora necessarie

Questi punti non sono presentati come exploit riusciti:

- **SSRF/DNS:** [backend/app/trading/onchain/legit.py:183](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/legit.py#L183) verifica gli IP pubblici prima della richiesta, ma HTTPX risolve nuovamente il nome; [backend/app/trading/onchain/jstext.py:291](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/jstext.py#L291) conserva l'esito per hostname e lascia Chromium risolvere. Resta una finestra DNS rebinding/TOCTOU. Verificare in laboratorio e imporre egress di rete verso destinazioni pubbliche, limiti di protocollo/porta e isolamento del renderer. Redirect ricontrollati sono già una buona difesa.
- **Script di terzi/CSP:** [deploy/Caddyfile:45](https://github.com/snowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/deploy/Caddyfile#L45) consente unsafe-inline e unpkg; l'escaping HTML in molti componenti è positivo ma non autorizza a dichiarare impossibile esfiltrazione. img-src https: consente richieste a destinazioni esterne. Nessun XSS sfruttabile è stato dimostrato in questo audit.
- **Custody e JSON:** users.json viene riscritto direttamente e caricato in memoria. Crash durante scrittura può renderlo illeggibile e _load_users ritorna silenziosamente. Serve storage transazionale, backup verificato e allarme su corruzione; non avviare più worker con stato indipendente senza migrazione.
- **Identità amministrativa:** ruolo derivato da email configurata, registrazione senza prova del possesso dell'email. Se un indirizzo amministrativo non è ancora registrato e la registrazione lo consente, chi lo registra per primo può reclamarlo. Stato reale degli account non verificato.
- **CI/worker AI:** generate e publish girano nello stesso workspace del runner; i test generati possono alterare file che lo step successivo esegue con GITHUB_TOKEN. Togliere variabili d'ambiente dai test e persist-credentials:false aiuta ma non isola il filesystem. Usare job separati e publisher fidato con artifact/diff validato; nessun payload eseguito in questa revisione.
- **Deploy non ancorato:** il workflow verifica il commit del run ma sul server fa reset a origin/main corrente. Due push possono fare deploy di un commit diverso da quello verificato. Distribuire SHA/image digest immutabile e verificare la versione dopo il deploy.
- **Dipendenze:** versioni dirette pinning presenti; manca una verifica completa delle transitive/SBOM e advisory. Nessuna CVE specifica è affermata senza scansione.
- **Salute operativa:** healthcheck HTTP della homepage non misura freschezza scanner, code, riconciliazione e notifiche. Docker restart:unless-stopped da solo non riavvia un processo vivo soltanto perché unhealthy.

## Correzioni del modello che incidono sulla sicurezza degli utenti

Nel documento ANALISI_E_PESI.md, M01/M02 mostrano che la “tokenomics” può presentare come sicuri dati insufficienti o concentrazione in contratti arbitrari; M03 mostra l'esenzione del benchmark dai blocchi fatal. Trattarli come requisiti di sicurezza del prodotto, pur non essendo vulnerabilità di accesso al server.

## Regola di consegna a Claude

Prima correggere le invarianti di esecuzione, poi auth/custody, poi criteri e ranking. Nessuna modifica ai pesi deve mascherare un problema di sicurezza. I test allegati descrivono il vecchio comportamento: trasformarli in regression test che chiedono il comportamento sicuro e aggiungere integrazione end-to-end. Le correzioni richiedono PR distinte e prova che lo SHA verificato sia quello distribuito.

