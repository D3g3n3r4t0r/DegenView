# Dalla scoperta alla decisione: consegna eseguibile e agent osservabile

## Stato e dipendenze

Richiesta di Lorenzo: «produci su github ciò che serve, poi claude implementerà il tuo codice»; estensione: mappa interattiva a neuroni e agent più utile di un elenco delle scansioni.

Base runtime letta: e8e0a97c688cf36461a1f43791b4e19610e0b33b. Questa consegna estende PR #364 / issue #365 e PR #362 / issue #363, non sostituisce i loro contratti. Al controllo del 29/09 entrambe le PR risultavano aperte. Le correzioni parallele vanno riconciliate prima di modificare il runtime.

`journey_reference.py` è una specifica eseguibile Python standard library; `test_journey_reference.py` ha 12 test. NON è una libreria di sicurezza pronta da importare in produzione. Opera su input già normalizzati e fidati; non valida prove esterne, non persiste dati, non applica lock o autorizzazioni. Le stringhe hash dello scenario sono segnaposto. Non modifica il voto corrente o l'esecuzione di ordini.

`neural-map.fragment.html` è un prototipo interattivo concettuale: 20 macro-nodi, dipendenze selezionabili e tre scenari sintetici. Non è una scansione automatica esaustiva del repository né telemetria live. Cerchi = moduli esistenti da collegare; quadrati = nuovi contratti. Un arco rappresenta una dipendenza logica, non una chiamata Python verificata. L'esecuzione ha volutamente un confine separato: la ricerca non autorizza fondi.

## 1. Risultato funzionale

Il prodotto deve generare una scheda motivata e aggiornata per ogni progetto:

| Campo | Contratto |
|---|---|
| Identità | chain + indirizzo canonico; alias/ticker soltanto descrittivi |
| Stato | eligibility distinta da research_state, ranking_membership e execution_status |
| Perché | reason_codes deterministici con evidenze e versione della policy |
| Rischi e dubbi | fallimenti verificati separati da informazioni mancanti e ipotesi |
| Cosa è cambiato | diff fra snapshot, con prova aggiunta/revocata/scaduta |
| Prossima verifica | condizione, task, scadenza o motivo di attesa |
| Cronologia | ricevute precedenti, analisi riusate, esperimenti e risultati osservati |
| Uso AI | chiamate/usage effettivi o unknown, mai zero inventato |

I tre stati del riferimento (blocked, unknown, eligible_for_research) descrivono soltanto ammissibilità alla ricerca. Non implicano automaticamente ranked, buy o safe. Ogni percorso runtime deve elencare i gate obbligatori nel manifest di policy; il riferimento usa solo identity/liquidity a scopo didattico e non definisce soglie economiche.

## 2. Percorso di ALFA e comportamento atteso

1. Scoperta: identità nota, liquidità mancante -> unknown, nessuna qualità negativa attribuita.
2. Dati minimi disponibili: gate pass, analisi mancante, budget esaurito -> eligible_for_research + queued_budget.
3. Budget concesso: needs_analysis è intenzione di scheduling; non è una chiamata già avvenuta né una prenotazione atomica.
4. Risposta validata: salvare artifact + ricevuta analyzed nella stessa transazione; una lettura successiva può riusare l'artifact. La funzione project restituisce lo stato di leggibilità, NON decide se emettere analyzed o reused: quello dipende dall'evento realmente avvenuto.
5. Liquidità scende: nuova generazione/snapshot -> blocked. La review tecnica resta leggibile se le sue dipendenze sono indipendenti e valide. Nessuna AI per applicare il gate o scrivere il log.
6. Vecchia risposta in volo: conservarla solo come storica; CAS transazionale su generation + fencing_token + request_hash impedisce applicazione corrente. complete() simula il confronto, NON implementa atomicità.
7. Orizzonte di esito: osservare mercato e disponibilità fonti separatamente; una perdita o un timeout non prova una frode. Etichetta negativa solo a orizzonte maturato, copertura sufficiente e policy di adjudication prevista da #362.

Fonte smentita: invalida transitivamente le conclusioni dipendenti e l'ammissibilità che le richiede. Non cancella lo storico, non riscrive retroattivamente ciò che era noto, non delega l'invalidazione a DeepSeek.

## 3. Agent: obiettivi, ipotesi e valore della ricerca

Non esporre una presunta trascrizione dei pensieri interni del modello. La superficie pubblica è una spiegazione operativa, composta da task reali, prove, motivazioni sintetiche e risultati verificabili. Nessuna chiamata extra per raccontare che cosa sta facendo.

Estendere AnalysisJob, senza un secondo scheduler, con un ResearchTask persistito:

```
task_id, project_key, scope, generation, objective_code,
question, hypothesis_ids[], supporting_evidence_ids[],
contradicting_evidence_ids[], required_dependency_ids[],
priority_class, priority_reason_codes[], estimate_revision,
budget_reservation_id?, not_before_ms?, deadline_ms?,
wake_condition, stop_condition, state, parent_task_id?,
created_at_ms, updated_at_ms
```

Stati: proposed -> queued -> running -> satisfied | inconclusive | failed | cancelled. Attese distinte waiting_budget / waiting_source / waiting_dependency, con wake_condition; un'attesa non diventa failed_quality. Dopo running un retry crea attempt separato, non cancella il precedente. Ogni transizione richiede evento idempotente e generazione corrente; non persistere payload arbitrari del modello come comandi eseguibili.

Classi di priorità in ordine: safety-critical deterministico, invalidazione, task ordinario richiesto, esplorazione entro quota dedicata. I controlli critici non aspettano DeepSeek. La priorità interna usa prima euristiche esplicite e versionate: freschezza, rilevanza per una decisione pendente, gap di copertura, costo previsto. Non chiamare una stima non calibrata «valore atteso scientifico».

L'agent deve poter rispondere con dati persistiti a:

- Quale dubbio cerca di risolvere? Quale decisione potrebbe cambiare?
- Perché questo progetto prima di un altro? Quale coda potrebbe soffrire starvation?
- Quali prove sostengono l'ipotesi e quali la contraddicono? Quante famiglie di fonti indipendenti?
- Che cosa è già disponibile e riusabile? Che cosa manca davvero?
- Perché una chiamata AI serve qui? Quale budget è stato prenotato?
- Quando smette, rimanda o chiede revisione? Quale evento lo risveglia?
- Che cosa ha prodotto: prova nuova, conclusione cambiata, dubbio ridotto o nessun risultato utile?

Esempio ALFA: domanda «il token è necessario al prodotto?». Ipotesi A: richiesto dal protocollo; B: accessorio commerciale. Il sito da solo non risolve la contraddizione; cercare evidenze del percorso reale. La conclusione inconclusive è valida. Conservare citazioni e limiti, non inventare una percentuale di confidenza.

Stop espliciti: nessuna nuova prova dopo limite configurato, costo massimo, fonte indisponibile, domanda fuori ambito, scadenza, risultato sufficiente secondo criterio verificabile. Max depth/attempts/parallelism da config server, non dal modello. Un ciclo di ricerca aperto non può moltiplicare autonomamente i propri budget.

## 4. Mappa di sistema: contratto per Claude

Tre modalità future, stesso grafo:

1. Architettura: componenti e dipendenze dichiarate, stato esistente/proposto/abilitato.
2. Progetto: solo snapshot e decisione selezionati, con percorso causale pertinente.
3. Cambiamento: dipendenze invalidate, risultati ancora validi e task da rifare.

Node DTO: id, kind, label, implementation_status, runtime_state, scope, evidence_refs[], artifact_refs[], task_refs[], last_event_at_ms nullable, coverage_status. Edge DTO: id, from_id, to_id, relation (observes|depends_on|proposes|validates|invalidates|records|evaluates), status, reason_code, receipt_ref nullable. Nodi e archi non devono derivare liberamente dal testo AI. Registry versionato, validato all'avvio, mapping adattatori -> ID stabili.

Vista overview aggregata con espansione progressiva, non una sfera di centinaia di archi illeggibili. Selezione di un nodo: ingressi, uscite, ultimo evento reale e limiti. Selezione di una decisione: snapshot congelato e causality path; la vista storica non deve mescolare eventi di oggi.

Il prototipo mostra dipendenze concettuali e scenari dimostrativi; Claude deve aggiungere adapter registry, autorizzazione e telemetria prima di chiamarlo live. Un nodo animato significa un evento o un job reale; evitare animazione perpetua che simuli attività inesistente. Disconnessione -> timestamp ultimo evento e stato stale, non silenzioso «tutto attivo».

API proposta, da adattare a routing reale con ADR:
- GET /api/assurance/projects/{project_key}/dossier?decision_id=...
- GET /api/assurance/projects/{project_key}/graph?decision_id=...
- GET /api/assurance/tasks?project_key=...&cursor=...

Risposte: schema_version, generated_at_ms, projection_revision, data_as_of_ms, freshness_status, next_cursor. project_key va codificato nel path; nessuna lookup solo per simbolo. Autorizzazione per scope prima della proiezione; cache e cursori legati al tenant. Non esporre prompt privati, segreti, wallet, hash di dati sensibili o citazioni di altri utenti. HTML e markdown delle fonti sempre trattati come input non fidato. Timeline paginata e limiti server: niente download dell'intero registro al browser.

Per il live iniziare da polling delle revisioni, riusando il modello corrente dell'app. SSE solo se latenza e carico lo giustificano, con eventi ordinati, resume e reset esplicito. Il grafo è una proiezione leggibile, mai una seconda autorità decisionale.

## 5. Integrazione nei file esistenti

| Anchor | Responsabilità nuova |
|---|---|
| code_review.review | primo flusso artifact validato/riusato; rispettare il prompt effettivo e cache esistente |
| research.analyze / _deepseek_reading | task analitici con domanda, dipendenze e condizione di chiusura |
| judge.judge | proposta tracciata, mai deroga a gate tramite testo AI |
| deepseek_desk.record / ask_message | usage e task correlation; nessuna seconda chiamata per la telemetria |
| leaderboard.apply_analysis / final_score / _rank | snapshot di policy e contributi; separare voto, eligibility e inclusione |
| projects_db.record | proiezione corrente derivata dal registro comune, non unico storico |
| outcomes.apply_sample / rug_label | esiti a orizzonte e copertura, separazione assenza dati/incidente/mercato |
| frontend/static/onchain/agent.js | sostituire il solo activity feed con task, risultati e dubbi verificabili |
| frontend/static/onchain/leaderboard.js | aprire scheda/prove della decisione selezionata senza rifare il ranking |

Verificare ogni anchor sulla HEAD corrente. Non incorporare direttamente journey_reference.py nel backend: portare i contratti nei tipi condivisi di assurance. Non introdurre memoria autonoma dentro il frontend. Niente nuovi pesi finali «intelligenti» finché non si misura qualità fuori campione.

## 6. Sequenza per Claude e verifiche richieste

J1 (dentro R1-R3): tipi comuni, gate policy versionata e projection; test runtime del flusso code_review, storage atomico e race.
J2 (R4): ResearchTask sopra scheduler esistente, budget prenotato atomico, stop e wake conditions; iniziare da una domanda strutturata, niente pianificatore ricorsivo generico.
J3 (R5): dossier API autorizzata e read-only, task timeline e mappa su fixture; collegare live solo dopo verifica telemetria.
J4: esiti + replay e dashboard qualità; promozioni di policy solo tramite il processo #362.

Accettazione aggiuntiva:
- Stessa decisione/snapshot produce stessa scheda e stessi reason_codes, indipendentemente dalla UI.
- Esaurimento budget non declassa la qualità; nessuna chiamata da logging/hash/renderer/replay.
- Gate unknown/fail impedisce il percorso che lo richiede anche con voto AI massimo.
- Risposta tardiva non sostituisce corrente; test con worker concorrenti e transazione reale.
- Liquidità modificata preserva engineering solo con dipendenze isolate; fonte revocata invalida transitivamente i risultati pertinenti.
- Timeline mostra analyzed al completamento e reused solo a vero riuso; contatori non incrementati aprendo la pagina.
- Nessuna fuga tra tenant, anche nei riferimenti degli archi, negli ID dei task e nei cursori.
- Fonte o connessione persa appare come stale/unknown, mai come rischio zero o attività live.
- Task inconclusive conserva la domanda e le prove contrarie; chiusura non richiede una risposta inventata.
- Mappa navigabile con tastiera, testo leggibile su mobile, movimento ridotto, dettagli senza hover e loading/error/empty veri.
- Esiti immaturi o senza copertura non generano etichette affidabili; nessun auto-training/promozione impliciti.

Eseguire qui: `python -m unittest discover -s docs/analysis-receipts -p 'test_journey_reference.py' -v` (12 test di riferimento). `python docs/analysis-receipts/journey_reference.py` produce una traccia sintetica, non chiama DeepSeek. Claude deve aggiungere test di integrazione nei backend/tests e seguire CLAUDE.md per check completi. I test di riferimento non provano storage, security, scheduling o comportamento del sito.

## Validazione di questa consegna

12 test standard library eseguiti e passati con Python 3.12. Suite backend non eseguita: runtime invariato. La bacheca /api/issues non era accessibile dal terminale di questa sessione (socket non consentito); nessuna segnalazione dichiarata risolta. Nessuna nuova automazione DeepSeek avviata da questa consegna. Merge e deploy non eseguiti.
