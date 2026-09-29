# Memoria verificabile e riuso delle analisi senza token di tracciamento

## Mandato e limite della consegna

Lorenzo: «mi piace l'idea, applichiamola scrivi tutto e pubblica su github per poi darlo in pasto a claude».

Questa specifica definisce l'implementazione da affidare a Claude. Non attiva nuove funzionalità in produzione. Base verificata: e8e0a97c688cf36461a1f43791b4e19610e0b33b, 29/09/2026.
Collegamenti: #358 (memoria e ricerca), #357 (backend), PR #362 e issue #363 (decision assurance), #347 (sicurezza).
Questa specifica estende la memoria A05 e i manifest A06: non creare un secondo registro di snapshot o una seconda autorità di promozione.

**Invariante di costo: nessuna chiamata a un modello per scrivere ricevute, calcolare hash, decidere cache hit, applicare regole, renderizzare spiegazioni standard o verificare la cronologia.** AI ammessa solo per un task analitico esplicito che ne abbia bisogno.

Non è una blockchain. V1: un backend, persistenza transazionale, storico e replay. Nessun consenso, token, validatore, integrazione DREGG o ZK. DREGG ispira il confine fra proposta e verifica, non è una dipendenza.
Un hash identifica contenuti e permette confronti; non dimostra la verità della fonte e non impedisce all'amministratore del server di riscrivere database e hash insieme.

## 1. Punti reali di integrazione

| Modulo | Stato letto | Modifica richiesta |
|---|---|---|
| research.py:270–292 _deepseek_reading | cache per key+ds e TTL di 7 giorni | intercettare input effettivo, scope, versioni e dipendenze prima della chiamata |
| research.py:369+ analyze | cache dossier separata | adattatore condiviso; non mantenere due autorità di validità |
| judge.py:205–250 judge | TTL 3 giorni + PROMPT_VERSION | aggiungere impronta completa input/modello/parser; cache TTL da sola non basta |
| code_review.py:169–202 review | TTL 7 giorni e riuso pushed_at a dati invariati | preservare il riuso esistente; usare commit/sampled-content verificati, non solo timestamp |
| leaderboard.py apply_analysis/final_score/_rank | analisi, calcolo e ordinamento separabili | registrare risultato del calcolo e diff deterministico con policy versionata |
| deepseek_desk.py ask_message/record | usage API e conteggio per tipo | correlation ID e motivo della chiamata, senza una chiamata extra per riassumerla |
| projects_db.py record | stato corrente aggiornato | conservare come proiezione; storico nel registro condiviso di #362 |
| storage.py data_file | percorso di persistenza già comune | riusarlo; niente file nella home né secondo storage inventato |

Le righe possono cambiare: gli anchor normativi sono le funzioni, il comportamento e il base SHA. Prima di sviluppare confrontare le PR già in corso.

## 2. Primo risultato da implementare

Primo flusso: code_review.review su un singolo repository/progetto, con AI simulata nei test.
1. Acquisire snapshot del codice con SHA del commit e hash dei file effettivamente letti.
2. Costruire request canonica con prompt, parser e configurazione del modello.
3. Cercare analisi validata riusabile.
4. Su hit: restituirla e scrivere una ricevuta di riuso, zero chiamate AI.
5. Su miss motivato e budget disponibile: una chiamata, validazione output, salvataggio atomico dell'analisi con la sua ricevuta.
6. Se l'input cambia mentre la chiamata è in corso: salvare il risultato storico, ma non applicarlo come corrente.
7. Alla variazione di sola liquidità: ricalcolare rischio/regole, mantenendo il giudizio tecnico solo se il suo input reale non contiene dati di liquidità e le altre dipendenze restano valide.

Non promettere isolamento delle dipendenze prima di aver letto il prompt reale: se una review incorpora market cap, quel campo deve entrare nella chiave finché il task non viene separato esplicitamente.
Secondo flusso: research/judge; terzo: replay delle decisioni e UI. Prima dimostrare il riuso sul flusso completo.

## 3. Modello dati e identità

Estendere lo store proposto in docs/decision-assurance, oppure il suo equivalente già implementato. Nomi logici obbligatori, implementazione fisica adattabile con ADR:

- EvidenceSnapshot: id, project_key, source_id, observed_at_ms, received_at_ms, payload_ref, raw_hash, normalized_hash, normalizer_version, rights_revision.
- AnalysisRequest: request_id, task_type, sharing_scope, project_key, dependency_digest, request_hash, provider, model_id, model_revision nullable, model_params, prompt_hash, parser_version, tool_contract_hash, created_at_ms.
- AnalysisArtifact: artifact_id, request_id, raw_output_ref, parsed_output_ref, output_hash, validation_version, status, created_at_ms, valid_until_ms, provenance_status.
- Dependency: artifact_id, evidence_id, field_paths, expected_hash, max_age_ms, dependency_kind.
- DecisionReceipt: receipt_id, idempotency_key, project_key, snapshot_id, artifact_ids, policy_id, previous_decision_id nullable, action, reason_codes, result_ref, result_hash, occurred_at_ms, recorded_at_ms, kind.
- AnalysisJob: job_id, request_hash, generation, lease_owner, lease_until_ms, fencing_token, state, attempts, provider_request_id nullable.
- ArtifactEvent: artifact_id, event_type, reason_code, at_ms, supersedes_event_id nullable. Invalidazione non riscrive il risultato storico.

Timestamp UTC in millisecondi; tempi di durata monotoni nel processo. Usare wall clock persistito per scadenze con controllo degli scarti; un rollback dell'orologio non deve estendere arbitrariamente la validità.
project_key: chain + identità canonica validata. Non usare ticker come identità; non lower-case degli indirizzi Solana.

Parsed output strutturato dall'analisi già necessaria. Non aggiungere un secondo prompt solo per produrre un JSON di log: registrare anche una risposta testuale con parser esistente e stato validato/non valido.
Se si cambia lo schema di output della chiamata principale, misurare variazione di token e qualità: il registro è gratuito in token, l'aggiunta di contenuto generato non lo è.

## 4. Hash e cache key

Canonicalizzazione v1 locale, identica fra writer e verifier: JSON UTF-8, chiavi ordinate, separatori compatti, allow_nan=False; nessun timestamp volatile di esecuzione nel request_hash.
Quantità monetarie come stringhe decimali normalizzate con unità; distinguere null/assente/zero. Array mantengono ordine salvo contratto esplicitamente set-valued. Non fare normalizzazioni del testo che cancellino negazioni, numeri, URL o codice.
SHA-256 prefissato da dominio e versione per evitare collisioni logiche fra tipi, per esempio bytes("analysis-request:v1\n") + canonical_json.

request_hash copre: task_type, scope, project identity, input effettivamente mandato al modello, prompt/system/tools, provider+model/config, parser/schema version, dependency normalizer version.
dependency_digest copre la lista ordinata delle prove realmente usate e gli hash dei campi dipendenti.
Non usare similarità semantica per cache hit V1. Identità esatta e compatibilità sono requisiti; la ricerca di casi analoghi è un'altra funzione.
Per modelli con alias mobile registrare model_revision se disponibile; se non disponibile, nuova model_epoch locale alla modifica dichiarata del provider e TTL massimo. Non promettere riproducibilità bit-a-bit di nuove generazioni.

Una risposta diversa a parità di request_hash non viene sovrascritta silenziosamente: artifact distinti e manifest di selezione deterministico. Nessuna nuova chiamata solo per controllare la stabilità, salvo esperimento autorizzato.

## 5. Predicato di riuso

can_reuse(artifact, current_dependencies, request, now) -> ReuseDecision(reusable, reasons[], artifact_id)

Riusabile se e solo se:
- scope compatibile e accesso consentito;
- request_hash identico o migrazione di compatibilità esplicita e testata (V1 solo identico);
- status validated, non revoked/invalidated;
- now < valid_until e ogni dipendenza richiesta ha freschezza sufficiente;
- dependency hash invariati, fonti non smentite, diritti d'uso ancora validi;
- output/schema ancora accettati dal consumer.

Un contenuto identico può essere riosservato: nuova EvidenceSnapshot con received_at nuovo e hash uguale. Può aggiornare la freschezza della prova secondo policy, ma non rinnovare indefinitamente la scadenza dell'analisi senza una regola esplicita. Non inventare nuovo observed_at se il provider serve dati vecchi.
Errore, timeout, output malformato e quota esaurita non sono analisi valide. Negative caching breve dei fallimenti evita retry a raffica, senza trasformare il fallimento in giudizio negativo sul progetto.
Una dipendenza sconosciuta blocca il riuso per decisioni che la richiedono; la UI può mostrare la precedente analisi come storica/scaduta.

Scope: public_project soltanto se tutti gli input sono pubblici, condivisibili e privi di dati personali o preferenze individuali. Altrimenti tenant/user scope separato. Hash dei dati privati non vanno pubblicati come se fossero anonimi.
Un risultato personalizzato non può soddisfare la cache pubblica. Richieste dello stesso progetto da utenti diversi riusano solo la parte pubblica.

## 6. Invalidazione precisa e prudente

Gli adattatori dichiarano dipendenze obbligatorie da contratto; eventuali citazioni del modello le arricchiscono, non le sostituiscono.
Usare DAG di dipendenze con ciclo rifiutato, attraversamento bounded e job deduplicati. Propagare invalidazione prima di rendere disponibile una nuova decisione; analisi in corso non può rendere corrente una generazione superata.

Matrice iniziale:
- quote/liquidità -> market risk e eligibility; non engineering se isolato;
- commit/file campionato -> engineering; se cambia dipendenza critica non campionata, invalidazione conservativa;
- testo sostanziale documenti -> product claims;
- cambio autorità/upgrade contratto -> hard safety immediata e conclusioni dipendenti;
- revoca/smentita fonte -> tutte le conclusioni che ne richiedono la validità;
- policy scoring -> decision receipt nuova, possibile replay senza AI;
- modello/prompt/parser -> nuove analisi non compatibili, salvo migrazione esplicita;
- sola data decorativa -> raw hash cambia, normalized hash può restare uguale solo tramite normalizer approvato.

Iniziare da hash esatti: falsi miss sono preferibili a falsi hit. La normalizzazione cosmetica è una fase successiva con fixture avversariali.
Revisioni che invalidano sicurezza non aspettano la coda DeepSeek. Stato prudente unknown/blocked definito dalla policy comune, senza aggirare i gate.

## 7. Concorrenza, retry e budget

Unique claim sul request_hash+scope+generation con transazione e lease. Un solo owner attivo. Fencing token monotonico impedisce al vecchio worker di pubblicare un risultato dopo riassegnazione.
Una cache hit non deve prenotare budget AI. Job nuovi prenotano budget atomicamente; attese riusano il job corrente con timeout bounded.
Crash dopo risposta API ma prima della persistenza può causare costo duplicato al retry se il provider non supporta idempotenza. Non promettere exactly-once billing. Persistire richiesta prima dell'invio, salvare provider request ID quando disponibile e limitare retry ambigui.
Ricevuta e artifact nello stesso commit DB. Chiave idempotente della ricevuta basata su evento logico (request/job/decision) non UUID nuovo a ogni retry.
Non tenere transazioni DB aperte durante una chiamata di rete.

Budget separati: monitoraggio critico, ricerca ordinaria, esplorazione. La quota esplorativa evita che solo i progetti già conosciuti accumulino prove.
Importi/limiti configurati, non scelti implicitamente dal modello. Se budget finito: queued_budget e prossima condizione di risveglio, non failed_quality.

## 8. Ricevute e verificatore locale

kind: analyzed|reused|recomputed|invalidated|deferred|failed.
reason_codes stabili: INPUT_UNCHANGED, DEPENDENCY_CHANGED, SOURCE_REVOKED, EXPIRED, POLICY_CHANGED, MODEL_CHANGED, OUTPUT_INVALID, BUDGET_WAIT, STALE_GENERATION, RIGHTS_UNKNOWN.
La ricevuta lega snapshot, versione e risultato. I payload conservati devono essere sufficienti al controllo dichiarato; se rimane solo hash, stato integrity_only e replay non disponibile.

verify_receipt(receipt_id) restituisce:
- integrity: hash dei payload presenti coerenti;
- provenance: riferimenti completi, cutoff temporale rispettato;
- computation: riproducibilità del calcolo deterministico, se possibile;
- coverage: quali elementi non sono verificabili e perché.

Non equiparare questi esiti alla verità di un sito o alla correttezza del ragionamento AI.
V1 verifica localmente contro il DB fidato. Catena di hash opzionale futura, non necessaria per cache o replay. Senza checkpoint esterno fidato, riscrittura completa e troncamento del registro da parte di un amministratore non sono rilevabili in modo indipendente.

Fase futura solo con bisogno dimostrato: checkpoint periodico minimale pubblicato a un riferimento indipendente, senza payload privati. Richiede scelta di minaccia, retention, prova di inclusione/completamento e gestione delle chiavi. Non aggiungere adesso blockchain, notarizzazione o servizi a pagamento.

## 9. Replay e spiegazioni senza AI

replay(decision_id, candidate_policy_id) lavora su copie immutabili, senza rete, senza firma e senza invocare DeepSeek.
Riusa output AI salvati come input opachi versionati: può confrontare formule deterministiche, non dimostrare cosa avrebbe risposto un modello diverso.
Se la candidate richiede un dato non disponibile al cutoff -> incomplete_replay. Non riempire con dati odierni e non chiamare l'AI in modo implicito.
Vecchia policy, stessi input -> stesso risultato deterministico. Policy diversa -> nuova ricevuta di simulazione; nessuna modifica a ranking attivo.

Spiegazioni generate da reason_codes e diff strutturati, template italiani. Esempio:
«Analisi tecnica riutilizzata: prove invariate. Rischio ricalcolato: liquidità diminuita. Nessuna nuova analisi AI.»
Non dire «nessuna chiamata» quando un job ha invocato altri modelli. Contatore per decisione includendo sottotask; evidenziare unknown usage.

UI può mostrare: fonte/prova, ultima osservazione, validità analisi, cosa è cambiato, decisione precedente e prossima verifica. Per V1 integrare il pannello già esistente, senza ridisegnare il prodotto.

## 10. Cosa potrebbe far cambiare il giudizio

Per regole deterministiche esporre blockers e condizioni necessarie di rivalutazione.
Esempio: liquidità sotto soglia e distribuzione sconosciuta -> due condizioni separate. Il superamento di una non garantisce ammissione.
Distinguere sufficient_conditions da necessary_conditions; testo non deve promettere un risultato quando esistono altre regole.
Per input complessi/AI, restituire unknown_condition; non chiedere al modello un controfattuale per ogni progetto.

Optional dopo V1: bound dell'effetto di un criterio numerico. Se anche il contributo massimo non cambia una decisione di ranking, rimandare quel task ordinario secondo scheduler.
Sono esclusi sicurezza, ricerca esplorativa e task che possono cambiare le premesse. Bound conservativo deve includere clipping, interazioni e tutti i rami; se non dimostrabile, NON sopprimere il task.
Non applicare questa ottimizzazione alla formula corrente prima di aver modellato i passaggi AI e le deroghe: sommare pesi nominali non basta.

## 11. Errori come regressioni e copertura

Ogni incidente riproducibile diventa fixture con snapshot sintetico/redatto, policy, risultato osservato, comportamento atteso e ID finding. Aggiunta manualmente revisionata, non una regola autoappresa dal modello.
Due suite: replay di compatibilità per comportamento ancora intenzionale; regressioni di correzione per difetti. Non aggiornare golden file automaticamente per rendere verde la suite.
Misurare copertura dei progetti osservabili, attesa per categoria, dati mancanti, quota ricerca/esplorazione e dipendenza da famiglie di fonti. Nessuna chiamata AI per produrre tali metriche.

## 12. Migrazione e rollout

1. Read-only inventory: cache legacy, dimensioni, versioni disponibili; nessuna pulizia distruttiva.
2. Shared store con #362; import legacy status=legacy_unverified, input_hash non ricostruibile -> non riusabile nel nuovo percorso. Mai attribuire provenance inventata.
3. Shadow capture della pipeline corrente, zero chiamate aggiuntive. Misurare hit potenziali contro reali; shadow non effettua la chiamata che avrebbe evitato.
4. Canary sul solo code_review, feature flag OFF default. Usare risultati validati per evitare duplicati; fallback non deve duplicare una chiamata già in volo.
5. Estensione a research/judge dopo i test delle dipendenze.
6. Replay e UI, poi ottimizzazioni facoltative.

In shadow, logging failure non blocca runtime attuale ma incrementa capture_failed. Nel nuovo percorso, persistenza fallita non crea un artefatto riusabile; nessun retry AI solo per riparare il log. Ricerca temporaneamente unavailable o risultato non registrato esplicitamente marcato, secondo policy del consumer.
Rollback spegne riuso nuovo e conserva storico. Cache legacy non viene aggiornata da artifact invalidi. Non cancellare tabelle al rollback.

Retention: deduplicare blob pubblici per hash e diritti compatibili; ricevute puntano al blob. Eviction non rimuove dati pinned da esperimenti/incidenti in corso, salvo obblighi di cancellazione. Payload cancellato -> tombstone e replay_unavailable, mai risultato di verifica falsamente positivo.
Nessun cookie, API key, seed, chiave wallet o chat privata nel registro pubblico. Per dati privati accesso scoped, cifratura e retention previste dal backend.

## 13. Metriche e criterio di successo

llm_calls_by_reason; reused_artifacts; exact_cache_hit_rate; stale_apply_rejected; invalidation_lag; capture_failed; duplicate_inflight; replay_complete_rate; bytes_per_artifact; verified_receipts; exploration_coverage.
saved_calls: richieste effettivamente soddisfatte da cache che avrebbero richiesto un task AI secondo baseline dichiarata. È una stima controfattuale, non fattura evitata certificata.
Costo API da usage reale se presente e listino versionato; distinguere stimato, osservato e non disponibile.
Successo iniziale: zero chiamate AI dalle funzioni di tracing/verifica/replay; nessuna applicazione di artifact scaduti o di generazione superata nei casi di test; almeno un flusso completo dimostrato con riuso e invalidazione.
Riduzione percentuale dei costi da misurare su workload reale; non promessa a priori.

## 14. PR di implementazione per Claude

R1: types/store/canonical hash e ricevuta, adattati ad assurance #362; migrazione e test isolati.
R2: adapter code_review e single-flight; spike su commit/content hash, senza duplicare cache esistente.
R3: dipendenze e invalidazione con generazioni; convalida delle race.
R4: research/judge adapters, pubblico/privato, budget e import legacy.
R5: replay, verifica e template UI italiani; no endpoint di esecuzione.
R6 opzionale: controfattuali bounded, scheduler esplorazione e valutazione checkpoint esterno. Non blocca R1–R5.

Comando test proposto: python -m pytest backend/tests/test_analysis_receipts.py backend/tests/test_analysis_reuse.py backend/tests/test_analysis_replay.py -q.
Questi test NON esistono per effetto di questa PR documentale: Claude deve crearli e collegarli al runtime.
CLI proposta: python -m app.assurance.receipts verify --receipt ID / replay --decision ID --policy ID, offline by default. Integrare nel package unico anziché introdurre un nuovo framework.

Definition of done: tutti i casi ACCEPTANCE.json implementati o deviazioni motivate approvate; test pertinenti passati, report di canary e confronto costi/copertura, rollback provato. Merge della specifica != completamento runtime.

## 15. Istruzione finale a Claude

Leggi prima questo documento, #358 e #362/#363. Riconcilia la HEAD, produci una mappa unica di storage e contratti, poi realizza R1 e R2 come primo flusso end-to-end.
Mantieni la scansione continua, elimina lavoro analitico duplicato e non spendere token per contabilizzare token. Ogni nuova chiamata deve avere un motivo analitico registrato prima dell'invio.
Apri PR piccole con ID dei test, migrazione, prove e limiti. Nessun merge/deploy o transazione reale impliciti in questa consegna.
