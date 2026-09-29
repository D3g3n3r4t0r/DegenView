# Audit dedicato: consumi DeepSeek e contatori riconciliabili

## Richiesta e limite della verifica

Lorenzo chiede un lavoro esclusivamente dedicato a ridurre token e chiamate API e segnala: `27849 studies · 866 readings · 745 judge · 336 narratives · 285 backtests · 181 readings · 80 consistency · 54 code · 10 chats · 9 scans · 2 manual`, mentre il database indica 893 studied.

Numeri forniti dall'utente, non estratti dal server in questa sessione. Diagnosi statica su main e8e0a97c688cf36461a1f43791b4e19610e0b33b. Non assumere che sia lo SHA in produzione. Nessun accesso a fatture, API key, dump DB live o conteggi provider. Non sommare queste voci per stimare chiamate o costo: le unità sono diverse e alcune si sovrappongono.

## C01 — Confermato: la tab mescola eventi e chiamate

`frontend/static/onchain/agent.js`, chips():
```
const counts = { ...(viewData?.today ?? {}), ...(viewData?.done ?? {}) };
```
`today` contiene chiamate dal ledger; `done` contiene eventi note(). Per la stessa chiave done sovrascrive today. Non è né un conteggio di chiamate né un conteggio uniforme di lavori conclusi. `note()` può essere emesso prima di un risultato: anche un tentativo fallito può comparire come lavoro effettuato.

`backend/app/notify/deepseek_desk.py`, note(): incrementa done[day][kind] ad ogni invocazione, senza distinct project o idempotency key. activity(): today = calls per kind del giorno Europe/Rome; working = evento negli ultimi 180 secondi, non presenza accertata di una richiesta AI in volo. Anche un backtest deterministico può far apparire DeepSeek al lavoro.

Fix: tre dimensioni separate e sempre etichettate — eventi del motore, richieste API, progetti distinti. Non fondere mappe. Un tab chiamato DeepSeek non deve attribuire all'AI ogni attività del backend. Mostrare stato Engine e stato AI separatamente, inclusi stale/disconnected.

## C02 — Confermato: studies non equivale a progetti studiati

`backend/app/trading/onchain/leaderboard.py`, _analyze() chiama _note_study() dopo un result non vuoto. _note_study() emette note("study", ...) anche quando si rianalizza un progetto già conosciuto. La nota stessa non chiama un modello; la pipeline precedente può averlo chiamato o avere riusato cache.

`backend/app/trading/onchain/projects_db.py`: projects.key è PRIMARY KEY, record() aggiorna il progetto; stats() conta le righe raggruppate per stato. `frontend/static/onchain/projects.js`, paintFunnel(): studied visualizzato = by_status.studied + by_status.ranked, una fotografia degli stati correnti, non gli eventi giornalieri e nemmeno necessariamente tutti i progetti mai esaminati.

Quindi 27849 eventi e 893 righe in tali stati sono quantità non confrontabili. NON concludere «31 chiamate AI per progetto»: periodi, popolazione, stati e unità non coincidono. La causa di ripetizioni eccessive va comunque misurata per project_key/task/input_hash, distinguendo refresh necessario, retry, cambio input e duplicato inutile.

## C03 — Confermato: doppia etichetta readings e sovrapposizione semantica

agent.js PLURAL assegna sia research sia scanner a "readings". Inoltre judge.judge() emette note("research", "Judging ...") ma la chiamata viene registrata con kind="judge". Un giudizio può quindi essere visibile sia fra eventi research sia fra chiamate judge. Non è prova di doppia fatturazione.

Fix labels stabili: ricerca documentale, giudizi AI, valutazioni scanner, review codice, batch narrative, controlli coerenza, chat. Separare task_type da event_type (started/completed/failed/cache_hit) e billing_attempt. Migrare UI con schema_version; non reinterpretare vecchi eventi come chiamate.

## C04 — Anomalia aperta: 80 consistency

Nello SHA letto consistency.py ha EVERY_S=2h, DAILY_MAX=12 per giorno UTC, gate in due()/step(). Il ledger/UI usa Europe/Rome. Il solo scarto di fuso non basta a spiegare 80 con un singolo writer regolare e questi limiti. Verificare deployed SHA, replica/process count, file persistiti/ripristinati, reset contatori, vecchia configurazione, eccezioni di persistenza e tutti i callsite note/ask. Non ridurre il numero a mano e non dichiarare già trovata la causa.

## C05 — Confermato: ledger incompleto per audit dei costi

ask()/ask_message(): record() dopo raise_for_status() e parsing JSON; i fallimenti/timeout non sono un ledger completo di tutti i tentativi inviati. Usage assente viene convertito in zero; record conserva calls/in/out per kind, non request_id, attempt_id, progetto, cache provider, motivo, durata o status. PRICE è statico e il calcolo non separa cache hit/miss del provider. Non usare il preventivo nel codice come prezzo corrente verificato.

note() e record() condividono _state e salvataggio JSON: record usa un lock threading, note no; _save scrive direttamente e ingoia OSError. Questo non offre atomicità tra processi, deduplicazione o audit affidabile dei fallimenti. Servono test con più worker e storage transazionale comune; non aggiungere un altro JSON di contatori.

KINDS del recap elenca un sottoinsieme dei kind effettivi: recap_text itera quella lista, quindi categorie non incluse (ad esempio judge/code/narratives) possono essere escluse dal riepilogo. Il totale deve aggregare tutte le categorie osservate, quelle sconosciute incluse e segnalate.

## C06 — Risparmio: preservare cache esistenti, chiudere i buchi

Cache già presenti: research TTL 7 giorni; judge TTL 3 giorni + PROMPT_VERSION; code_review TTL 7 giorni + pushed_at invariato. Non presentare il caching come tutto nuovo. #364 rende chiavi, scope e dipendenze più precisi e aggiunge single-flight.

Budget distribuiti: research DeepSeek 300/giorno; judge 600 normale + 150 priority; code 80 + 50 priority; narrative 400 batch/giorno; consistency 12/giorno nello SHA letto. Sono limiti locali, non un unico tetto di spesa globale. Alcuni bucket seguono UTC, altri time.strftime locale, ledger Roma. I commenti sui costi non sono fatture né garanzie.

chat answer(): verifica CHAT_DAILY_TOKENS una volta prima del loop; TOOL_ROUNDS=5 comporta fino a 6 invocazioni ask_message per una risposta. Una chat non equivale a una chiamata. Concorrenza e singole risposte possono oltrepassare il budget controllato solo all'ingresso. Tool result troncato a 6000 caratteri non equivale a limite token; cronologia e tool schema vengono ripetuti a ogni round.

## Piano esclusivo consumi, in ordine

### E0 — Inventario e riconciliazione, senza nuove inferenze
Inventory di ogni callsite HTTP DeepSeek, wrapper, AI review GitHub e worker esterni. Classificare quelli fuori dal server invece di nasconderli nei totali. Raccogliere deployed SHA/config (senza segreti), numero processi, giornate e timezone, contatori attuali e usage provider disponibile. Baseline 24h/7g se già esiste; altrimenti avviare capture e dichiarare storico incompleto. Non aspettare settimane per correggere etichette e accounting.

Output obbligatorio: tabella task_type con task richiesti, progetti distinti, cache hit applicativi, tentativi API, successi, fallimenti, timeout ambigui, token input/output/cache e costo observed/estimated/unknown. Registrare periodo e scope su ogni tabella. Totale eventi != totale task != totale tentativi != progetti.

### E1 — Gateway e budget unico
Un adapter condiviso davanti alle chiamate esistenti, mantenendo i consumer. Record tentativo persistito prima dell'invio:
```
attempt_id, logical_task_id, request_hash, project_keys[], scope,
task_type, trigger_reason, provider, model, model_revision?,
started_at_ms, finished_at_ms?, status,
provider_request_id?, input_tokens?, output_tokens?,
provider_cache_hit_tokens?, provider_cache_miss_tokens?,
usage_status, price_version?, estimated_cost?, actual_cost?,
budget_reservation_id, retry_of?, error_class?
```
Usage mancante = null/unknown, mai 0. Vincoli unici sugli ID; doppio callback non incrementa di nuovo. Tentativo failed non implica non fatturato. Riconciliazione fattura separata dai token riportati in risposta; non inventare actual_cost se si dispone solo di listino.

Prenotazione atomica prima di ogni invio, inclusi round tool, fallback e retry. Tetto globale configurato dal gestore, con sottobudget per task, progetto, ora/giorno e riserva prioritaria INTERNA al tetto. Prenotare input stimato conservativo + output massimo; riconciliare usage effettivo, tenere riserva per timeout ambigui fino a policy di risoluzione. Timezone unica esplicita per finestre budget; timestamp UTC. Un tetto per richieste non è un tetto economico: conservarli entrambi. Il default di rollout non aumenta i limiti effettivi.

### E2 — Eliminare chiamate duplicate
Applicare #364: exact request hash, dipendenze, TTL, scope, single-flight interprocesso, generation/fencing. Cache hit non prenota budget AI. Negative cache breve di errori evita raffiche senza etichettare male il progetto. Backoff+jitter e retry max per tipo di errore; nessun retry automatico illimitato su timeout ambiguo. Verificare anche top_fill contro flusso ordinary sullo stesso task: priority non deve duplicare un'inferenza in volo.

### E3 — Osservare spesso, ragionare quando serve
Scanner deterministici possono proseguire; l'AI si risveglia per cambio materiale delle proprie dipendenze, richiesta esplicita o scadenza della policy. Coalescenza bounded di aggiornamenti ordinari sullo stesso progetto; sicurezza/invalidation immediata. Niente timer AI per far sembrare viva la tab.

Consistency deterministica prima di AI: ID, conteggi, rank/stato, presenza campi, timestamp, duplicati sono controlli di codice. AI solo per contraddizione semantica non risolta, con snapshot cambiato e domanda esplicita. Narrative batch già esistente: misurare item utili per batch, non espandere batch indiscriminatamente; riusare label valide a dati invariati. Nessun nuovo riepilogo AI per la UI.

### E4 — Ridurre token per inferenza conservando prove
Evidence pack per task: campi necessari, citazioni stabili, deduplica testo, esclusione boilerplate verificata, limiti per fonte. Versionare estrazione; non troncare ciecamente negazioni o sezioni di rischio. Output schema essenziale, limite per task, niente spiegazioni duplicate in più moduli. Separare input pubblici stabili da parte volatile preservando scope e semantica. Misurare token cache provider riportati; prefisso stabile non elimina una chiamata e non rende il costo nullo.

Chat: retrieval mirato, risultati strutturati paginati, limitare tool disponibili per richiesta con regole trasparenti, deduplica tool identici nello stesso turno, stop se nessun nuovo dato, budget a ogni round. Eventuale riassunto memoria deterministico/estrattivo prima di aggiungere chiamate AI di compressione. Un modello più economico per task semplici solo dopo benchmark di qualità; non cambiare modello per sembrare ottimizzati.

### E5 — Misurare e promuovere
Una baseline di chiamate realmente avvenute; replay deterministico di decisioni cache/scheduler senza invocare due modelli in shadow. Metriche: chiamate per task utile, token per nuovo artifact valido, costo per progetto aggiornato, duplicati, percentuale unknown usage, copertura, freschezza, latenza dei controlli critici, errori di riuso. Non premiare meno chiamate ottenute lasciando tutto scaduto.

Report per ottimizzazione: prima/dopo su workload e periodo comparabili, variazione qualità/copertura e intervalli quando appropriati. Nessuna promessa di percentuale risparmio finché non misurata. Disattivazione feature deve preservare telemetria e non avviare una seconda richiesta di fallback già in volo.

## Test di accettazione obbligatori

1. 100 note sullo stesso project_key -> 100 eventi, 1 progetto, 0 tentativi AI se nessuno inviato.
2. Un judge che emette research note -> 1 evento + 1 tentativo, non 2 chiamate.
3. research e scanner hanno etichette diverse; nessun merge done/today.
4. Una risposta chat con 6 round -> 1 task e 6 tentativi; budget verificato prima di ognuno.
5. Concorrenza tra processi non supera reservation limit; priority non elude il tetto.
6. 20 richieste identiche simultanee -> un owner; crash/fencing testati; nessuna promessa exactly-once billing dopo timeout.
7. Usage assente o timeout -> unknown, non costo zero; ogni categoria compare nei totali recap.
8. Cambio ora legale/mezzanotte, restart e retry non duplicano accounting; delta ledger spiegabile.
9. Input identico riusa artifact valido; input diverso invalida; nessun fallback AI da renderer o logging.
10. Fixture provider cache hit/miss: conteggi e costo stimato con listino versionato; actual non inventato.
11. Aprire/reloadare la tab non genera studi o chiamate; stato working deriva da job reale, non ultima nota.
12. Riconciliazione dei 27849/893/80 con dati server oppure report esplicito delle informazioni irrecuperabili. Gli ultimi 1000 eventi e soli aggregati storici non bastano a ricostruire tutti i progetti distinti: non inventare backfill.

## Consegna a Claude

Filone autonomo rispetto a grafica/agent: prima E0+E1 accounting, poi E2 deduplica, E3 scheduler, E4 token packing e E5 report. Riutilizzare assurance/receipts; niente secondo store. Produrre PR piccole e test applicativi. Questo audit pubblicato definisce il lavoro, non lo dichiara già implementato o verificato sul server.
