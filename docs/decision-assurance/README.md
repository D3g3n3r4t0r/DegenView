# Decision assurance: specifica vincolante per Claude

## Stato e perimetro

Questa PR aggiunge una specifica tecnica e un contratto SQLite eseguibile in memoria. Non modifica il runtime, non cambia voti e non certifica remediation già in corso. L'implementazione applicativa spetta a Claude.

Base letta: `e8e0a97c688cf36461a1f43791b4e19610e0b33b` (main, 29/09/2026). Tutti i riferimenti sotto si riferiscono a questo SHA. Prima di applicare modifiche rivalutare i punti di integrazione sulla nuova HEAD.

Precedenze: correzioni sicurezza #347 e PR #348; architettura #357; memoria #358. Questo lavoro copre otto temi complementari: ground truth, utilità umana, manipolabilità, costi degli errori, vantaggio cumulativo, governance, diritti sulle fonti e perimetro del prodotto. La PR #361 modifica presentazione/alert della Top: coordinare qualsiasi esperimento UI per non sovrascriverla.

HANDOVER descrive alcune correzioni come ancora da fare, ma main contiene test nuovi per S01–S07. La presenza dei test non dimostra che passino né che il deployment sia aggiornato. Non reiterare patch di sicurezza sulla base del solo HANDOVER.

## Evidenze e conseguenze

| ID | Punto del codice | Osservazione verificata staticamente | Conseguenza per questo piano |
|---|---|---|---|
| E01 | outcomes.py:288–348 apply_sample/_mark_rug | Tre prezzi mancanti, perdita di liquidità e crollo prezzo confluiscono in rug=True | Separare evento osservato da incidente verificato; vietare training del nuovo target con etichette legacy implicite |
| E02 | outcomes.py:374–382 rug_label | Dopo tre giorni senza rug restituisce False, anche prima dell'orizzonte di sette giorni | Esplicitare endpoint e maturità; nessuna etichetta negativa senza copertura sufficiente |
| E03 | outcomes.py:559–593 _cv_fit/train | Fold per indice modulo 5, attivazione automatica a soglia AUC | Il nuovo benchmark usa split temporali e il nuovo rilascio richiede manifest immutabile |
| E04 | projects_db.py:50–70 e 211–245 | Una riga corrente per progetto; record aggiorna score/pillars con COALESCE | Non usare questa tabella come dataset storico; aggiungere snapshot separati senza cambiare il contratto corrente |
| E05 | depth.py:183–187,242–246 | Nomi directory/file valgono punti per test e CI | Fixture avversariali: presenza superficiale vs evidenza di esecuzione |
| E06 | leaderboard.py:529–565,605–628 | Benchmark esente e più passaggi AI modificano il risultato | Versionare scelta editoriale, gate e scoring separatamente; gli esperimenti non rimuovono eccezioni in produzione |
| E07 | deepseek_desk.py:39–45, record/cost | Prezzi statici e contatori per giorno/tipo | Estendere telemetria per decisione e listino versionato; non chiamare costo reale un confronto a listino |
| E08 | providers/base.py:6–38 | Esistono errori distinti per indisponibilità, dato non pronto e quota | Riutilizzare questi concetti negli adattatori onchain; non appiattirli a dato negativo |
| E09 | frontend/static/onchain/leaderboard.js:refresh/render | Polling e podio con punteggi sono parti reali del flusso | Testare comprensione e fiducia, non solo click o velocità |
| E10 | traction.py:111–147 judge | TVL/fee e multipli contribuiscono a traction/value | Testare segnali incentivati e separare valore del prodotto da diritti economici del token |

I percorsi E01–E06,E10 hanno prefisso backend/app/trading/onchain; E07 backend/app/notify; E08 backend/app.
Questi sono fatti di codice, non misure d'impatto in produzione. Nessuno studio umano, audit contrattuale dei provider o benchmark reale è stato eseguito in questa consegna.

## Architettura minima e ownership

Nuovo package proposto: `backend/app/assurance/`, senza dipendenza da main.py e senza inizializzazioni di rete/import che avviino scanner.
Moduli: contracts.py (DTO), store.py (transazioni), labels.py (etichette), snapshots.py (adattatori), evaluation.py (metriche), policies.py (versioni/promozione), sources.py (diritti), experiments.py (assegnazione e risultati).
I nomi sono normativi per la prima implementazione; se #357 ha già introdotto un equivalente, riusarlo e aggiornare la mappa in una ADR, evitando un secondo sistema.

`contract.sql` è il prototipo del contratto di persistenza. Non è una migrazione pronta per produzione. I CHECK e trigger sono vincoli minimi; le validazioni semantiche descritte qui restano responsabilità applicative.

Persistenza proposta: database assurance separato nel data_file già esistente, schema_version=1, PRAGMA foreign_keys=ON per ogni connessione. Nessun aggiornamento automatico degli archivi onchain esistenti.
Snapshot e risultato devono essere registrati insieme nel nuovo database; in fase shadow la cattura è best effort rispetto alla classifica corrente, con errore visibile e contatore capture_failed. Un fallimento di cattura non deve bloccare ordini né essere contato come valutazione valida.
Non usare doppia scrittura corrente/storico come garanzia atomica: per la successiva promozione valutare outbox nello storage autorevole oppure dichiarare esplicitamente la copertura.

## Contratti di servizio comuni

Tutti i timestamp sono interi UTC in millisecondi. Vietati float NaN/Infinity; quantità monetarie originali in stringhe decimali con unità. JSON canonico: chiavi ordinate, separatori compatti, UTF-8, allow_nan=False; hash SHA-256 sui byte. Indirizzi Solana preservano case; normalizzazione EVM solo tramite parser della chain, mai lower() universale.

- capture_snapshot(project_key, decision_at_ms, evidence[], input_json, versions) -> snapshot_id. Solo prove received_at_ms <= decision_at_ms. Un dato tardivo crea un nuovo snapshot.
- annotate(case_id, reviewer_id, verdict, evidence_ids, rubric_version) -> annotation_id. Annotazioni indipendenti non sovrascrivibili.
- adjudicate(case_id, adjudicator_id, result, rationale, evidence_ids) -> label_id. Non produce consenso automatico da media di voti.
- evaluate(manifest_id, policy_version, snapshot_ids) -> run_id. Solo I/O locale del benchmark; niente chain/broadcast/notifiche.
- request_promotion(policy_id, run_ids, approver_id) -> transition_id. Non altera main o deployment; produce una decisione di promozione verificabile.
- can_use_source(source_revision, purpose, now_ms) -> allowed|denied|unknown con reason_code.

Errori stabili: INVALID_INPUT, FUTURE_EVIDENCE, STALE_POLICY, RIGHTS_UNKNOWN, LABEL_UNRESOLVED, MANIFEST_MISMATCH, INSUFFICIENT_SAMPLE, UNAUTHORIZED_TRANSITION. Non convertire errori in punteggio zero.

## A01 — Verità di riferimento e semantica degli esiti

### Target distinti

1. market_drawdown_80: prezzo osservato <=20% del prezzo iniziale entro l'orizzonte, evento di mercato; non prova frode.
2. liquidity_drop_80: liquidità comparabile <=20% del riferimento; considerare migrazione del pool come possibile confondente.
3. source_unavailable: errore/provider o osservazioni mancanti; label di qualità dati, non del progetto.
4. verified_exploit: incidente supportato da prova verificabile del meccanismo; annotazione umana/adjudication.
5. project_quality: rubrica ordinale per una domanda specifica, mai derivata automaticamente da rendimento.
6. executable_return: calcolo separato con ingresso/uscita e costi definiti prima del test; max_ret non è rendimento eseguibile.

Una label è positiva, negativa, censurata, disputed o unknown. Per un evento entro H, positive richiede evento e prova; negative richiede orizzonte completato e coverage sufficiente definita nel manifest; altrimenti censored/unknown. Definire coverage temporale, gap massimo e affidabilità dei provider prima di osservare risultati.

### Modifiche

In outcomes.py mantenere per compatibilità le chiavi rug/rug_why solo come legacy heuristic, senza chiamarle verified_exploit. Aggiungere adattatore in assurance/labels.py che importa motivo, versione e provenienza senza convertirli in gold label.
All'importare record storici: verified status=unknown salvo nuove prove; niente backfill di received_at con il timestamp del mercato. Conservare legacy_label separata.
rug_memory.py e training continuano il percorso corrente finché non viene promossa la nuova policy; UI deve distinguere esplicitamente label legacy e nuovo target durante shadow.

### Protocollo umano

Due reviewer indipendenti, non esposti al voto AI né all'esito futuro per project_quality; conflitto di interesse dichiarato. Disaccordo -> disputed; terzo adjudicator distinto per risolvere. Conservare distribuzione dei giudizi e accordo, non cancellare dissenso.
Rubrica v1: product_evidence, engineering_evidence, adoption_evidence, token_mechanism; valori ordinali 0..3 o unknown, con esempi ancorati e evidence_ids obbligatori. Nessun totale automatico nella v1.

### Accettazione

A01-T1 tre fetch falliti -> source_unavailable e verified_exploit unknown.
A01-T2 drawdown80 con trading regolare -> market_drawdown_80 positive; nessuna implicazione automatica su frode.
A01-T3 tre giorni osservati su H=7d -> negative rifiutata.
A01-T4 revisore vede solo snapshot point-in-time; evidence ricevuta dopo cutoff rifiutata.
A01-T5 annotazioni discordanti -> disputed, esclusa dai target binari maturi.
Test applicativi futuri: test_assurance_labels.py, test_assurance_annotation_access.py.

## A02 — Utilità umana, non soltanto accuratezza del modello

Esperimento offline, volontario, senza wallet e senza denaro reale. Nessuna assegnazione di utenti reali in questa PR.
Confronto iniziale: A dossier di fonti statiche; B stesso dossier con interfaccia Liquid. Le prove disponibili sono identiche; non confondere accesso a più dati con migliore interfaccia.
Assegnazione bloccata per esperienza del partecipante; ordine controbilanciato con casi diversi e comparabili. Stesso partecipante non vede lo stesso caso in entrambe le condizioni.
Prima dell'avvio congelare manifest: rubric_hash, case_set_hash, assignment_seed, endpoint primario, margine di danno, numerosità e analisi. Pilot per stimare varianza; nessuna soglia di efficacia inventata dopo i risultati.

Endpoint primario: errore di decisione rispetto alla rubrica adjudicated, con costi A04 congelati.
Secondari: comprensione dei rischi, astensione appropriata, tempo di completamento, confidenza dichiarata e calibration solo per domande binarie con riferimento valido.
Click, visite e tempo sul sito non sono proxy di qualità; analizzare abbandoni senza eliminarli retrospettivamente.

Record trial: experiment_id, pseudonymous participant_id, case_id, arm, assigned_at_ms, started_at_ms, submitted_at_ms, answer, confidence, status(completed|abandoned|technical_failure). Nessun nome, chat, wallet o cronologia finanziaria.
UI sperimentale isolata dalla leaderboard reale; flag server default OFF; endpoint admin e accesso partecipanti con token scoped al trial, non token riutilizzabile cross-user.

A02-T1 stable assignment dopo refresh/retry; duplicato submit stessa risposta idempotente, payload diverso 409.
A02-T2 non mostra voto AI al reviewer della rubrica.
A02-T3 output con N assegnati/completati/abbandonati per gruppo e intervalli d'incertezza; N insufficiente -> inconclusive, mai promoted.
Punti: leaderboard.js, API dedicata assurance (router separato), experiments.py. Coordinare #361.

## A03 — Manipolabilità a budget limitato

Runner offline di trasformazioni su snapshot, mai su servizi di terzi.
Ogni coppia ha original_snapshot, transformed_snapshot, changed_paths, invariant_paths, budget_units e attack_family.
budget_units sono costi sintetici ordinali, NON dollari o stime di costo reale.

Famiglie:
- add_empty_tests_dir/add_empty_ci_dir: segnali superficiali senza cambiamento funzionale;
- inflate_commit_activity: storico cosmetico controllato;
- duplicate_press_release: molte copie con un unico source_family_id;
- cosmetic_site_rewrite: stessa sostanza, migliore stile;
- incentivized_usage_claim: dati dichiarati non verificati;
- benchmark_identity: verifica esplicita delle eccezioni editoriali senza rimuoverle silenziosamente.

Metriche: delta-score, inversioni di ranking, gate-crossing, variazione di qualità delle prove e numero di source_family indipendenti.
Una robustezza perfetta non è garantita: definire envelope tollerato nel manifest, confrontare baseline e candidate. Nessuna promozione se input cosmetico supera un hard gate.
Adattatore baseline chiama funzioni pure effettive depth.judge_github/judge_site e leaderboard.final_score su input validi; network e AI registrati/replay, nessuna chiamata live nel test deterministico.

A03-T1 directory vuota non incrementa engineering_verified.
A03-T2 5 copie comunicato -> independent_sources=1.
A03-T3 stessa evidenza e lessico diverso -> hard_gate invariato.
A03-T4 log changed_paths dimostra che non è stata alterata la fixture del target.
Output attack_report.json con policy_sha e dataset_hash. Non usare il runner per falsificare repository reali.

## A04 — Costi degli errori e modalità del prodotto

Modalità v1: research, monitor, execution_support. Non introdurre preferenze che alterino fatti o bypassino risk.run_safety_checks.
Decisioni di ricerca: include, exclude, abstain. Stato vero per il singolo task: eligible, ineligible, unresolved; unresolved non è etichetta negativa.
Matrice loss_matrix[truth][action] non negativa, versionata e completa; unresolved escluso dal loss primario e riportato come copertura.
Non imporre valori universali. Manifest privo della matrice approvata -> esperimento descrittivo, promozione vietata.

Loss medio = somma dei costi sui casi risolti / N risolti. Riportare separatamente copertura, tasso di false ammissioni fra ineligible e false esclusioni fra eligible. AUC da sola non determina la soglia ottima.
Astensione ha costo esplicito. Se restituiamo sempre abstain non possiamo apparire perfetti: coverage_min e abstention_max congelati nel manifest.
Decision profiles agiscono dopo l'idoneità comune e prima della presentazione; nessun coefficiente profilo arriva ai controlli di firma.

A04-T1 cambio profilo non cambia evidence_hash, verified_label o hard_gate.
A04-T2 matrix incompleta/negativa/NaN rifiutata.
A04-T3 unresolved esclusi dal denominatore con numero esposto.
A04-T4 execution_support non invoca execute/send in alcun test assurance.

## A05 — Vantaggio cumulativo: dati utili e ricostruibilità

Inventariare asset realmente esistenti: projects_db corrente, journal outcomes, cache research/judge e log DeepSeek. Misurare perdite di informazione, non dichiarare un vantaggio competitivo senza prova.
Nuovo event lineage: snapshot_id -> decision_id -> outcome_id -> evaluation_run. Un dato è un asset utilizzabile solo se identificato, temporalmente corretto, legalmente utilizzabile e riproducibile.
Metriche iniziali: replayable_decisions/total_captured; usable_mature_labels/observed_cases; unique_source_families; missing_cutoff_rate; cost_per_adjudicated_case.
Comparazione sperimentale: storia completa vs snapshot corrente, stesso modello e budget. Tenere storico soltanto se migliora il compito o consente accountability indispensabile.
Nessuna raccolta extra di dati utente per costruire un presunto moat.

A05-T1 esportazione autorizzata e reimport in db vuoto preservano hash e risultati deterministici.
A05-T2 label con fonte non utilizzabile esclusa dal benchmark esportabile.
A05-T3 fonte eliminata -> artifact tombstone e lineage ancora spiegabile senza ripubblicare il payload rimosso.
Primo report: dataset_asset_inventory.json con counts reali o null e motivo; mai conteggi inventati.

## A06 — Governance delle versioni e promozione

Policy bundle immutabile: policy_id, parent_id, code_sha, prompt_hash, scoring_hash, dataset_hash, label_schema_version, source_registry_hash, experiment_manifest_hash.
Macchina a stati: draft -> shadow -> reviewed -> approved -> active -> retired; reviewed -> rejected; active -> retired solo tramite transazione di attivazione della sostituta o spegnimento esplicito.
Un singolo slot attivo per product_surface + decision_mode. Versione corrente legacy rappresentata da manifest, senza cambiare il comportamento.

Promozione richiede: dati maturi, manifest registrato prima del run, gate test obbligatori passati, report integrità, margini/numerosità definiti e approvatore umano identificato. L'AI può proporre, non approvare se stessa.
Un bundle cambiato invalida le approvazioni: nuovo ID, nuovo confronto. Rollback punta a bundle approvato e compatibile con schema; non ripristina snapshot obsoleti come se fossero freschi.
Audit append-only per transizioni e motivazioni. DB trigger non sostituisce autorizzazione HTTP: validazione role e actor dal server, mai dal campo fornito dal client.

A06-T1 approvazione con hash mismatch rifiutata.
A06-T2 due attivazioni concorrenti non producono due attivi.
A06-T3 approvatore assente o ruolo AI -> denied.
A06-T4 replay su vecchia versione non aggiorna active_slot.
Punti: RULES_VERSION/PROMPT_VERSION restano letti nell'adattatore fino al refactor; non rimuoverli prima della migrazione.

## A07 — Dipendenze e diritti sulle fonti

Registro versionato per source_id e prodotto/endpoint: terms_url, retrieved_at_ms, content_hash, account_plan_reference NON segreto, use_internal, retain_raw, send_to_model, redistribute, train, expires_at_ms e reviewer.
Ogni permesso = allowed|denied|unknown. Nessuna conclusione legale è stata verificata qui: partire da unknown e verificare documenti ufficiali/piano effettivo durante implementazione.
Granularità distinta per contenuto GitHub e metadati API; licenza del repository non equivale automaticamente al permesso di ogni riuso.
Per nuovo export/training/trasferimento al modello: unknown -> blocked_pending_review. Non spegnere retroattivamente l'intero scanner durante introduzione: partire con inventario e report shadow; enforcement per singolo uso dopo revisione del proprietario.
Cache scaduta non autorizza redistribuzione. Source registry revision è parte del manifest; revoca invalida future esportazioni e mette in revisione gli artefatti derivati interessati.

A07-T1 internal allowed + redistribute denied -> export denied.
A07-T2 permission unknown/expired -> non trattato come allowed.
A07-T3 token API, cookie e account credentials non serializzati nel registry.
Punti: research.gecko_info, depth.fetch_github, traction, discovery, deepseek_desk.ask_message; base.DataProvider non copre tutti i client onchain: censire anche richieste httpx dirette.

## A08 — Perimetro del prodotto e rimozioni verificabili

Capability registry: capability_id, user_job, owner, dependencies[], surfaces[], evidence_of_value[], runtime_cost, status(core|support|experimental|deprecated), removal_condition.
Inventario iniziale: project_research, continuous_monitoring, project_ranking, ai_chat, strategy_lab, execution. Stato iniziale undecided nel report, non nuova tassonomia applicata in produzione.
Generare call graph dei consumer e contratto API prima di deprecare; risorse condivise non eliminate se ancora usate.
Per ogni proposta di rimozione: export/retention dati, compatibilità consumer, periodo di transizione, flag, rollback e misura di beneficio.
Scegliere la funzione centrale dopo A02/A05, non da una preferenza dell'AI. L'ADR finale deve contenere almeno una alternativa plausibile e il costo di non sceglierla.

A08-T1 flag OFF non causa import error né effetti collaterali su altri flussi.
A08-T2 rimozione suggerita con dipendente attivo -> blocked con lista consumer.
A08-T3 nessuna cancellazione dati automatica legata a capability deprecated.

## API e confine di sicurezza proposti

Prima release: CLI offline e nessun endpoint pubblico. Seconda release, solo dopo auth:
GET /api/admin/assurance/runs/{id} e GET /api/admin/assurance/policies/{id}: admin, response redacted, paginazione bounded.
POST /api/admin/assurance/policies/{id}/review: autenticazione recente, actor derivato server-side, optimistic version, audit event.
POST /api/admin/assurance/policies/{id}/activate: separato dal review, attualmente non implementato; include confronto run/manifest e slot transazionale.
GET/POST /api/assurance/trials/{trial_id}: token scoped a partecipante/caso, non accesso admin, no payload del gruppo di controllo prima dell'assegnazione.
403 cross-user; 409 hash/version conflict; 422 contratto invalido; 503 storage unavailable. Nessun endpoint di firma o esecuzione.
Tutti i nuovi endpoint e la UI sono OFF per default; le route non devono apparire come funzionanti prima che persistenza e autorizzazioni siano testate.

## Dataset, metriche e statistica

Manifest congelato prima dell'esecuzione con target, H, coverage, gruppi correlati, training_cutoff, test_window, loss_matrix, primary_metric, budgets, promotion_rules.
Train include solo label available_at <= training_cutoff. Test include snapshot successivi; nessun gruppo progetto/fork condiviso quando la domanda richiede generalizzazione a nuovi progetti.
Esiti con orizzonte sovrapposto: purge o embargo motivato. Report grouped/time split; mai modulo indice come dimostrazione di generalizzazione temporale.
Non riusare test finale per scegliere soglie; benchmark test sintetico != qualità empirica del modello.
Una configurazione minima valida può restare non-promotable finché costi/errori e numerosità non sono concordati.

## Sequenza PR per Claude

P1: contracts/store/snapshot shadow + test_contrat(ti), senza letture AI aggiuntive. A01/A05; coordinare storage #357/#358.
P2: labels + import legacy + annotazioni CLI e test di tempo/indipendenza. Nessuna etichetta umana inventata.
P3: runner offline A03/A04 + manifest e report. Chiamare baseline pura e candidate con stessi input.
P4: version registry e promozione dry-run A06, prima senza attivazione reale.
P5: source inventory A07, diritti unknown, verifica provider con fonti ufficiali; enforcement separato.
P6: trial UI A02 isolata, previo protocollo completo e partecipanti volontari.
P7: capability inventory e ADR A08 con evidenza A02/A05.

Ogni PR cita Axx-Tn, funzioni cambiate, migrazione, test e conflitti con PR in corso. Non usare etichetta deepseek su questa issue di specifica: non è un task di patch a perimetro ridotto. Claude potrà suddividere il lavoro secondo le istruzioni correnti della repository.

## Verifica di questa consegna

contract.sql + verify_contract.py verificano solo vincoli del prototipo in database temporaneo e casi di riferimento. Non importano FastAPI, non testano auth, baseline runtime, rollout, qualità scientifica o licenze.
ACCEPTANCE.json è il catalogo machine-readable dei test futuri, non un report di test superati.
I test A01–A08 restano required fino a prova applicativa. Non segnare l'issue di implementazione risolta al merge di questa PR documentale.

### Esecuzione del contratto

`python docs/decision-assurance/verify_contract.py`

Validazione locale: 13 test del prototipo passati con Python 3.12 e SQLite in memoria. Non è stata eseguita la suite applicativa completa: la PR contiene soltanto documentazione e un prototipo isolato, non patch runtime. La prova di unicità dello slot è sequenziale contro il vincolo DB; la prova concorrente A06-T2 resta richiesta a Claude.

Vincoli da completare prima della migrazione: validazione JSON/canonical hash, numero/evidenza delle annotazioni, tutte le transizioni di stato, revoca approvazioni, autorizzazione server, redazione, diritto di cancellazione e retry transazionali. Il campo actor_type nel prototipo dimostra un vincolo strutturale: solo l'autenticazione futura può provare che l'attore sia davvero umano.
