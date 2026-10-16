# Punti di forza, debolezze e pesi del voto
Liquidity Analysis Engine — 29 settembre 2026 — snapshot ceef100a04a3a48dbef74137875ddd40ddc399ed.

## Valutazione complessiva

L'idea merita di essere sviluppata: riunire evidenze tecniche, on-chain e di mercato, registrare gli esiti e verificare se i criteri funzionano. Il software ha già molti pezzi utili. Il limite attuale è che **il voto mescola qualità, preferenze narrative, somiglianza a un progetto scelto, valutazioni AI e opportunità economica**. Queste dimensioni non rispondono alla stessa domanda.

Non butterei il progetto. Ristrutturerei il criterio di giudizio e consoliderei l'esecuzione. Oggi un 85/100 è un risultato di una procedura euristica; non è una probabilità dell'85% di guadagno, assenza di rug o qualità certificata. Non attribuisco un voto numerico complessivo al software: non abbiamo misure sufficienti di rendimento fuori campione, affidabilità operativa e incidenti.

## 1. Non esiste un solo “voto”

| Percorso | Cosa misura | Formula o logica |
|---|---|---|
| Gem Finder/Gems | Qualità di progetto secondo pilastri e giudizi | depth.overall + leaderboard.final_score |
| Top nella schermata Strategie | Unione di Gems e progetti studiati | Ordina score salvati, ma applica filtri diversi |
| Pagella legit | Media dei controlli che hanno uno score | Pesi uguali fra controlli disponibili; filtri aggiuntivi |
| Meme engine | Flusso, momentum, liquidità e concentrazione | 25 flow, 15 ticket, 20 momentum, 15 turnover, 15 depth, 10 holders, meno penalità |
| Vecchio Sniper | Punti sui dati osservabili | scorer.py/TokenScore, schema distinto |
| Backtest/System | Rendimento simulato di strategie | Ritorni/costi, mediana e selezione di una strategia; non qualità del progetto |
| Modello outcomes | Rug o trade vincente secondo esiti osservati | Modello statistico e soglie di attivazione; non lo score delle gemme |

Fonti: [backend/app/trading/onchain/legit.py:129](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/legit.py#L129), [backend/app/trading/onchain/meme_engine.py:43](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/meme_engine.py#L43), [backend/app/sniper/scorer.py:63](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/sniper/scorer.py#L63), [backend/app/trading/onchain/system.py:271](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/system.py#L271), [backend/app/trading/onchain/outcomes.py:578](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/outcomes.py#L578).

L'interfaccia dovrebbe nominare chiaramente ogni misura. La presenza di più motori non è un difetto in sé; presentare valori diversi come un unico giudizio affidabile lo diventa.

## 2. Formula effettiva delle gemme

Fonti: [backend/app/trading/onchain/depth.py:40](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L40), [backend/app/trading/onchain/depth.py:676](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L676), [backend/app/trading/onchain/leaderboard.py:593](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/leaderboard.py#L593).

Indichiamo con G GitHub, W sito/ricerca e T tokenomics, tutti 0–100.

**Qualità iniziale:** Q = 0,40 G + 0,30 W + 0,30 T, quando tutti sono disponibili. Se un punteggio manca, i pesi vengono rinormalizzati sugli altri. Un fatal azzera overall e normalmente esclude; un pending normalmente trattiene il candidato. GitHub esplicitamente mancante viene trattato diversamente da un'API momentaneamente irraggiungibile.

**Base dopo preferenze:**

B = clamp[Q + 0,30 × max(0, S − Q) − 10 × I(no GitHub) + 0,10 U + 0,05 V + N, 0, 100]

S è somiglianza a DREGG, U trazione DefiLlama, V valutazione relativa, N bonus narrativa 0–6. U/V si aggiungono soltanto se esiste la copertura della fonte. Non sono pesi sottratti agli altri: sono bonus. Il peso 30% della somiglianza è un incremento condizionato, non una quota sempre attiva.

Poi tre miscele successive, quando il dato esiste:

1. J: giudizio AI individuale → 50% B + 50% J.
2. C: media di complessità e innovazione AI → 80% risultato precedente + 20% C.
3. R: revisione AI della classifica, se keep=true → 70% risultato precedente + 30% R.

Il codice arrotonda a un decimale a ogni passaggio. Se un passaggio manca, viene saltato: non viene sostituito da zero.

### Pesi effettivi, quando somiglianza non aggiunge punti

| Dati presenti | GitHub | Sito/ricerca | Tokenomics | Giudice J | Lettura codice C | Revisione R |
|---|---:|---:|---:|---:|---:|---:|
| Solo base, tutti i pilastri | 40% | 30% | 30% | — | — | — |
| Base + J | 20% | 15% | 15% | 50% | — | — |
| Base + J + C | 16% | 12% | 12% | 40% | 20% | — |
| Base + J + C + R | **11,2%** | **8,4%** | **8,4%** | **28%** | **14%** | **30%** |

Nell'ultimo caso F = 0,28 B + 0,28 J + 0,14 C + 0,30 R, salvo arrotondamenti. **Il 72% è assegnato direttamente ai tre giudizi AI.** È una decomposizione della formula, non prova di tre fonti informative indipendenti.

Se S > Q, i coefficienti diretti diventano GitHub 7,84%, sito 5,88%, tokenomics 5,88%, somiglianza 8,4%, e resta 72% ai tre passaggi AI. Il bonus massimo narrativa diventa 1,68 punti finali; trazione fino a 2,8 e valore fino a 1,4, prima di saturazioni. Questi numeri cambiano se mancano J/C/R.

Senza GitHub, se ci sono J e R ma non C, W e T diventano ciascuno il 17,5% del risultato; J 35%, R 30%, e la penalità iniziale −10 vale −3,5 punti finali. Quindi confrontare due progetti può significare confrontare formule diverse.

### Esempio riprodotto

Q=60, somiglianza senza bonus, nessun altro bonus; J=80, C=70, R=90:
60 → 70 dopo J → 70 dopo C → **76** dopo R.

Con tutti questi passaggi attivi, +10 punti al pilastro GitHub aggiungono circa 1,12 al voto finale; +10 alla revisione di classifica aggiungono 3. La revisione conta molto più di quanto lasci intendere una legenda “GitHub 40%”.

## 3. Dentro i pilastri

### GitHub

[backend/app/trading/onchain/depth.py:161](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L161) e [backend/app/trading/onchain/depth.py:241](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L241):

| Indicatore | Punti massimi del pilastro |
|---|---:|
| Commit ultimi circa 90 giorni, saturazione a 60 | 25 |
| Settimane attive, saturazione a 12 | 20 |
| Autori/contributori, saturazione a 5 | 15 |
| Quantità di codice, scala logaritmica | 15 |
| Presenza test | 6 |
| Presenza CI | 5 |
| README | 2 |
| Licenza | 2 |
| Recenza ultimo commit | 10 |

Totale 100 prima delle penalità: moltiplicatore 1 − 0,5 × quota commit classificati trivial; ulteriore ×0,8 per repository nato insieme al token. Fork, quasi assenza di codice, commit in un giorno e troppi commit trivial possono essere fatal.

**Giudizio:** utile come screening di attività, debole come misura di qualità. Più righe, commit o autori non dimostrano buon engineering. “.github esiste” non prova che CI passi. Si cercano test soprattutto nella root: questo stesso repository ha test annidati in backend/tests e sarebbe facilmente sottovalutato dal criterio strutturale. I messaggi dei commit sono manipolabili. Un fork legittimo con miglioramenti non è automaticamente uno scam. Occorre verificare build/test, provenienza delle modifiche, componenti critici e maintainer reali.

### Sito: in realtà è ricerca sul prodotto

[backend/app/trading/onchain/research.py:315](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/research.py#L315):

Con il lettore disponibile, W = 35% miglior sito leggibile + 65% lettura della sostanza. Nel ramo DeepSeek, la lettura stessa è 50% deterministica e 50% DeepSeek. Quindi W = 35% sito + 32,5% lettore locale + 32,5% DeepSeek. Senza lettura si usa un altro fallback; i siti illeggibili seguono una regola apposita.

Nel caso completo della tabella, altri **2,73 punti percentuali** del voto derivano indirettamente dal DeepSeek di ricerca: 8,4% × 32,5%. La quota diretta+indiretta esplicitamente AI sale così al **74,73%**, in quello specifico ramo e senza bonus somiglianza attivo. Gli stessi dati vengono poi riletti dal giudice: non sono quattro esperimenti indipendenti.

Il lettore locale assegna punti a concetti, concretezza, stadio del prodotto, utilità del token, informazione, coerenza e ammissione di limiti; premia inoltre primitive tecniche nominate. [backend/app/trading/onchain/reader.py:157](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/reader.py#L157).

**Giudizio:** leggere docs/app invece della sola homepage è giusto. Contare parole tecniche e dichiarazioni resta facile da ingannare. Dire “abbiamo un SDK, un audit, un'integrazione” non prova che esistano. Ammettere limiti può essere onestà, ma anche testo copiato. La bellezza del sito dovrebbe pesare quasi zero; la verificabilità del prodotto deve pesare molto.

### Tokenomics: il nome è più ampio della misura

[backend/app/trading/onchain/depth.py:625](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L625):

| Indicatore | Punti massimi |
|---|---:|
| Distribuzione primi 10 holder | 40 |
| Quota creatore | 15 |
| Numero holder | 15 |
| Liquidità bloccata | 15 |
| Assenza insider rilevati | 10 |
| Tasse nulle | 5 |

Honeypot/rug, mint/freeze, quota creatore >15%, singolo wallet >20%, top10 >60% e tasse >5% sono fatal nel percorso standard.

**Giudizio:** questa è soprattutto una misura di rischio contrattuale/distribuzione e liquidità. Non valuta in modo completo unlock, vesting, emissioni future, FDV/circolante, incentivi, cattura di valore del token, sostenibilità dei ricavi o controllo amministrativo. Chiamarla “tokenomics” suggerisce una copertura che non ha.

## 4. Difetti del metodo verificati

### M01 — Un contratto non è automaticamente un pool o vesting sicuro

[backend/app/trading/onchain/depth.py:559](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L559) elimina tutti gli holder con is_contract=1 dalle soglie di concentrazione; resta una penalità massima di 10 punti. **Caso sintetico riprodotto:** un contratto non classificato detiene il 90% dell'offerta, altri segnali favorevoli → top1=0, score=90, nessun fatal.

Un multisig, proxy o contratto controllato dal creatore può essere una balena. Escludere soltanto indirizzi con ruolo/proprietà verificati; separare supply circolante da quote vincolate e rendere visibile il controllo beneficiario. Se la classificazione è sconosciuta, il rischio resta sconosciuto.

### M02 — Dati assenti diventano prove favorevoli

[backend/app/trading/onchain/depth.py:553](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/depth.py#L553) usa zero per percentuali mancanti; flag assenti diventano false; LP sconosciuta ottiene 15 punti, come LP almeno 90% bloccata.

**Caso sintetico riprodotto:** risposta contenente soltanto holder_count=5000 → tokenomics=100/100, nessun flag. Non significa che GoPlus risponda sempre così: dimostra che il contratto dati accetta una risposta parziale come perfetta.

Il fallback Gecko arriva fino a 65 pur senza prove di mint/freeze/tax/LP: può superare la soglia 60 o essere ammesso dall'AI. Separare true/false/unknown, coverage e freshness. Assenza di allarme non equivale a controllo passato.

### M03 — DREGG è esente perfino dai fatal

[backend/app/trading/onchain/leaderboard.py:517](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/leaderboard.py#L517) restituisce “ammesso” per il benchmark prima di controllare capitalizzazione, liquidità o fatal. Il ranking corrente non lo fissa più automaticamente al primo posto: quel problema è distinto ed è già stato attenuato. **Resta però l'esenzione dai controlli**, riprodotta con overall.fatal impostato.

Non è una conclusione negativa su DREGG. È un difetto di imparzialità del motore. La menzione d'onore può stare in una sezione editoriale, senza deroghe alle protezioni.

### M04 — Sovrapposizione e disponibilità dei giudizi AI cambiano il metro

Il 72% diretto è molto, soprattutto perché i tre giudizi rileggono evidenze correlate. Chi riceve più passaggi è valutato con un metro diverso. Rate limit, assenza chiavi e code cambiano quali passaggi sono presenti.

Le cache judge durano 3 giorni e code review 7; final_score non controlla autonomamente l'età del dato. Una review positiva antica continua ad aggiungere punti: **prova 50→65 con review at=1**. Occorrono score_version, fingerprint dei dati, prompt/model-version, created_at, expires_at e copertura esposti.

### M05 — Ammissione AI senza soglia di confidenza simmetrica

[backend/app/trading/onchain/leaderboard.py:540](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/leaderboard.py#L540) richiede confidence≥0,7 per il veto, ma ammette gem/watch score≥80 senza confidence minima. **Prova:** tre pilastri a 10/100 vengono ammessi con giudizio 80 e confidenza 0, se non ci sono fatal/pending e i filtri antecedenti passano.

La confidence auto-dichiarata dal modello non è comunque una probabilità calibrata. Preferibile un elenco di deroghe motivate a criteri non di sicurezza, con evidenze verificabili; mai deroga ai gate di rischio.

### M06 — Top e Gems applicano regole diverse

[backend/app/main.py:3947](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/main.py#L3947) aggiunge alla Top righe studiate del database fino a 30 giorni, saltando la soglia di liquidità e vari requisiti della board; controlla alcuni fatal/veto/cap, non tutto qualifies.

**Prova:** riga studiata con score 95, liquidità USD 1 e motivo “liquidity under $10k” entra nella Top. È un comportamento intenzionale descritto nei commenti, ma contraddice l'idea che “Top” significhi “ha superato le regole”. Separare “da approfondire” da “idoneo”, mantenendo una policy unica per gli indicatori di idoneità.

### M07 — Lettura AI del codice limitata e README passato nel formato sbagliato

[backend/app/trading/onchain/code_review.py:101](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/code_review.py#L101) chiede il README con Accept application/vnd.github+json e usa r.text; quindi legge il contenitore JSON e content base64, non il Markdown decodificato. Caso riprodotto con risposta API fittizia conforme al formato documentato da [GitHub](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#get-a-repository-readme).

La review legge soltanto i quattro file sorgenti più grandi, massimo 3.000 caratteri ciascuno, più 4.000 di README. Non può dimostrare sicurezza, originalità globale o funzionamento del prodotto. Correggere decodifica, fissare commit, campionare i componenti per ruolo e chiedere citazioni file/riga. La complessità non deve diventare un premio automatico: può essere anche debito tecnico.

### M08 — Somiglianza al progetto preferito e correzioni ad hoc

[backend/app/trading/onchain/benchmark.py:39](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/benchmark.py#L39) favorisce Lean/verifica formale, ZK, linguaggi di sistema, consenso, SDK, storia lunga e dichiarazione dei limiti. È una descrizione del tipo di progetto che interessa a Lorenzo, non una misura universale di qualità o rendimento.

Il bonus su testo può essere ottenuto con parole chiave. Le note e [issue #289](https://github.com/Smowcomingsoon/liquidity-analysis-engine/issues/289) mostrano aggiustamenti per esempi specifici. I casi reali sono utili test diagnostici; modificare criteri finché i nomi preferiti salgono è overfitting editoriale. Conservare quei casi in un set di sviluppo e valutare poi su un set indipendente non scelto per simpatia.

## 5. Punti di forza da preservare

1. **Separazione di molte responsabilità.** Providers, funzioni pure di scoring, risk, ledger e signer sono moduli riconoscibili. Consentono test mirati e correzioni senza riscrivere tutto.
2. **Evidenze e motivazioni.** Pillars/facts/flags, provenance delle fonti e database dei progetti forniscono una buona base per mostrare perché cambia un voto.
3. **Più fonti.** Dati di codice, documentazione, sicurezza token, attività e prezzi riducono la dipendenza da una sola vetrina. Il renderer ha limiti e controlli espliciti.
4. **Memoria degli esiti.** Outcomes, gem_track e backtest_lab possono trasformare intuizioni in ipotesi misurabili, includendo fallimenti e campioni di controllo.
5. **Attenzione all'overfitting nella pipeline tecnica.** validation.py include PBO e Sharpe deflazionato; esistono test su lookahead, date e causalità. La presenza di questi strumenti è positiva, non dimostra che ogni classifica li usi o che l'edge esista.
6. **Intento di sicurezza concreto.** Cookie HttpOnly/SameSite, hashing con salt, blocco autenticazione per default, wallet inizialmente spenti, controllo indirizzo della chiave, ledger SQLite, contenitore non privilegiato dopo l'avvio e HTTPS nel proxy.
7. **Test numerosi e feedback operativo.** I test coprono molte funzionalità e i problemi vengono registrati. Occorre rafforzare soprattutto invarianti fra moduli, casi avversariali e test che mantengano attivo il middleware.
8. **Efficienza dello sviluppo.** Frontend senza una grossa infrastruttura di framework, cache e quote API, capacità di iterare rapidamente. È adatto a una fase di ricerca purché trading e dati sensibili siano isolati.

## 6. Debolezze strutturali

**Confine ricerca/custody troppo vicino.** Lo stesso processo raccoglie siti non fidati, interroga AI e ha accesso alle chiavi. Un errore di parsing, libreria o autenticazione ha conseguenze molto più ampie di un cattivo punteggio. Separare servizio di ricerca in sola lettura, API utente e signer con policy minima.

**Orchestrazione monolitica.** main.py è circa 369 KB e app.js circa 526 KB nello snapshot. Questo aumenta accoppiamenti e rende facile applicare una protezione in un endpoint ma dimenticarla altrove. Estrarre router e servizi per dominio; non riscrivere in un nuovo framework soltanto per gusto.

**Persistenza mista.** JSON globali in memoria, SQLite e file di cache hanno garanzie diverse. Aggiornamenti concorrenti, crash, più processi e migrazioni richiedono una strategia unica. Users, sessioni, job e versioni di score dovrebbero essere transazionali; cache sacrificabili separate dai dati irrecuperabili.

**Test che possono nascondere difetti di integrazione.** Il middleware salta il gate se esiste qualsiasi dependency_override. Utile nei test di endpoint, ma quei test non provano l'autenticazione reale. La falsa conferma e il falso clamp mostrano che test di singoli componenti non bastano.

**Validazione statistica incompleta.** outcomes._cv_fit usa fold interlacciati per indice, non una separazione temporale: il training può contenere osservazioni successive al test. Le statistiche di imputazione sono correttamente stimate sul training fold, ma resta il problema temporale e di token/progetti correlati. [backend/app/trading/onchain/outcomes.py:559](https://github.com/Smowcomingsoon/liquidity-analysis-engine/blob/ceef100a04a3a48dbef74137875ddd40ddc399ed/backend/app/trading/onchain/outcomes.py#L559).

**“Miglior backtest” selezionato dopo aver visto i risultati.** system._best_trades sceglie max(return_pct) sulla stessa storia mostrata; scoreboard sceglie la strategia con mediana migliore sugli alert già decisi. Sono analisi descrittive utili, non prova di performance futura indipendente. Registrare la scelta al tempo t e misurarla soltanto dopo t. La pipeline PBO/DSR del sito non si trasferisce automaticamente a questi altri percorsi.

**Asimmetrie di copertura.** DefiLlama favorisce ecosistemi/protocolli coperti; GitHub favorisce open source e alcune strutture di repository; testo/keyword favoriscono lingua e gergo riconosciuti. Mancanza di copertura deve ridurre confidenza, non sembrare né merito né colpa.

**Governance delle modifiche.** Pesi, prompt, filtri e deroghe cambiano in molti file. Senza versioni dei dati e una misura ex ante del successo, si rischia di ottimizzare “una Top che sembra convincente” invece di un criterio utile.

## 7. Proposta di ristrutturazione

### Tre risultati distinti

- **Sicurezza/idoneità:** consentito, bloccato, sconosciuto; con rischi, fonti e freschezza. Non compensabile da un bel sito o dall'AI.
- **Qualità del progetto:** voto spiegabile 0–100, sul prodotto e sulle evidenze.
- **Opportunità di trading:** liquidità eseguibile, spread/slippage, volatilità, orizzonte, costi e segnali validati. Un buon progetto può essere un pessimo trade al prezzo corrente.

Mostrare accanto **confidenza/copertura**, data di verifica e versione del metodo. Un numero unico può restare come ordinamento della qualità, ma non deve assorbire tutte le altre dimensioni.

### Pesi iniziali proposti per la qualità

Questi sono un'ipotesi da validare, non pesi “scientificamente ottimali”.

| Fattore | Peso proposto | Prove richieste |
|---|---:|---|
| Prodotto e utilità reale | 25% | Funzioni utilizzabili, problema servito, evidenze verificabili del prodotto |
| Adozione e sostenibilità | 25% | Utilizzo persistente, utenti/attività depurati da incentivi e bot, ricavi quando pertinenti |
| Engineering e manutenzione | 20% | Build/test, architettura, review, sicurezza del software, continuità; GitHub come fonte |
| Economia del token | 20% | Necessità del token, value capture, emissioni, vesting/unlock, FDV e circolante, governance |
| Trasparenza e verificabilità | 10% | Provenienza, audit verificabili, controllo privilegiato, documentazione e limiti dichiarati |

**Sito:** nessun voto autonomo all'estetica. Può fornire prove di prodotto e trasparenza, senza contarle due volte.
**GitHub:** fonte dell'engineering, non sinonimo di qualità; repository privato significa meno verificabilità, non bocciatura automatica.
**Narrativa:** filtro di interesse o pannello separato; non premio per ripetere AI/ZK/DePIN.
**Somiglianza a DREGG:** mantenibile come ricerca “progetti simili”; **peso zero nella qualità generale**.
**AI:** prima versione con **peso diretto zero**: estrae affermazioni, cerca contraddizioni e collega prove, con giudizio editoriale distinto. Eventuale correzione numerica limitata va sperimentata separatamente e mantenuta soltanto se migliora le metriche fuori campione. Non usare self-confidence per presentare probabilità.
**Sicurezza token e liquidità:** gate espliciti, più informazioni operative; non annullabili dalla media. Esenzioni per v4/pool/vesting solo con classificazione verificata, non per qualsiasi contratto.

### Gestione dei dati mancanti

Ogni fatto deve avere value, status (verified/claimed/unknown/stale/not_applicable), fonte e momento. Un dato unknown non vale zero né “tutto bene”. Mostrare copertura ponderata e, quando manca troppo, un intervallo di score invece di falsa precisione. Non classificare insieme candidati pienamente analizzati e dossier parziali senza indicarlo.

Esempio: “Qualità 68–81, copertura 72%, sicurezza non verificata, negoziabilità bassa”. È più informativo di 85 ottenuto da ciò che la rete ha risposto quel giorno.

### Un'unica funzione di policy

Tutti i percorsi Gems, Top, Database e notifiche usano lo stesso esito di idoneità. Una vista esplorativa può includere esclusi, ma mostra il motivo e non li presenta come approvati. Il benchmark segue gli stessi gate; nessuna eccezione per nome o token.

Lo score pubblicato deve contenere contributi per fattore, pesi effettivi, fonte, copertura, bonus/penalità, versione, motivi delle variazioni e stato dei giudizi AI. L'utente deve poter ricostruire il totale.

## 8. Come decidere se i nuovi concetti funzionano

1. Congelare baseline corrente e proposte prima del periodo di confronto; salvare tutti i candidati al momento della prima osservazione, non soltanto quelli sopravvissuti.
2. Definire target diversi: rischio operativo/rug; qualità verificabile; rendimento netto negoziabile a 7/30/90 giorni. Non addestrare “qualità” a inseguire solo pump.
3. Split temporale walk-forward, raggruppamento per progetto/clone/chain e intervalli senza sovrapposizione fra training e target; liquidità/holder disponibili al tempo t, non aggiornamenti futuri.
4. Confrontare baseline semplici e ablation: senza AI, senza GitHub, senza narrativa, senza somiglianza, nuovo modello; misurare quali fattori aggiungono informazione.
5. Misurare precisione dei primi K, frequenza rug/esclusioni erronee, copertura, stabilità del ranking, costi API; per il trading rendimento netto, drawdown e capacità eseguibile. AUC per rug da sola non prova redditività.
6. Se si presentano probabilità, verificare calibrazione con Brier/reliability curve, intervalli di incertezza e numerosità per segmento.
7. Eseguire inizialmente in parallelo senza cambiare ordini reali. Pubblicare vantaggi e regressioni anche quando non favoriscono i token preferiti.

Le soglie di promozione vanno fissate prima di osservare l'esito e proporzionate ai dati disponibili. Non promettere una validazione in pochi giorni se il target è a 90 giorni.

## Decisione consigliata

Preservare acquisizione, dossier, memoria degli esiti e funzioni testabili. Correggere subito sicurezza, dati sconosciuti trattati bene e deroghe al benchmark. Poi implementare spiegazione del voto e policy unica, e confrontare il modello proposto in parallelo. Cambiare soltanto “40/30/30” lascerebbe quasi tutti i problemi intatti.

