# DeepSeek: il nostro aiutante

Lorenzo, 27/09: "da oggi considera deep seek un tuo aiutante costante; dagli
task che è in grado di svolgere e in base alla sua abilità aumenta il carico
di lavoro; obbiettivo risparmiare token qui". E: "crea un ambiente di scambio
per informazioni".

Questo file è lo scambio fra Claude e DeepSeek: cosa fa DeepSeek, come gli si
passa il lavoro, come sta andando. Claude lo aggiorna dopo ogni lavoro
rivisto; le revisioni delle PR lo leggono insieme a CLAUDE.md.

## Cosa fa oggi

| lavoro | dove | stato |
|---|---|---|
| revisione di ogni PR | `.github/workflows/deepseek-review.yml` | attivo, secondo parere |
| revisione dei token (sistema) | `app/trading/onchain/ai_review.py` | attivo |
| chat su Telegram, con i dati del sito | `app/notify/deepseek_desk.py` | attivo |
| riepilogo giornaliero dei token, alle 21 | `app/notify/deepseek_desk.py` | attivo |
| rischio rug su ogni meme segnalata, a gruppi di 10 | `app/trading/onchain/ai_scan.py` | in ombra: si misura |
| lettura del sito delle gemme | `app/trading/onchain/legit.py` | in ombra (`LEGIT_AI_GATE` per farlo bloccare) |

Lavoro affidabile = conta i token che fa. Il riepilogo li confronta con quello
che sarebbero costati su Claude, a prezzi di listino.

## Come Claude gli passa lavoro

Per ora solo per le strade qui sopra: DeepSeek gira sul server e su GitHub,
Claude no (la sua sandbox non raggiunge internet). Un DeepSeek che scrive
codice e apre PR da solo è stato proposto ed è in attesa della decisione di
Lorenzo: vedi HANDOVER.

## Per DeepSeek, quando rivedi una PR

- Segnala solo quello che hai verificato sul diff: file, riga, cosa succede.
- Leggi il codice prima di dire che un test "non testa" qualcosa: guarda
  quale funzione chiama.
- Le tre strategie non sono tutte trend-following (CLAUDE.md): un filtro di
  persistenza giusto per una è rovesciato per le altre.
- Soldi degli utenti, chiavi, firme: lì ogni dubbio vale la pena scriverlo.

## Com'è andata (Claude aggiorna)

| data | lavoro | esito |
|---|---|---|
| 27/09 | PR #155, prima revisione | 5 osservazioni, 0 valide: diceva che un test non isolava la chiave (la toglieva già) e che un altro chiamava `main()` (chiamava `ask()`). |

Regola per dargli più lavoro: tre revisioni di fila con almeno un'osservazione
giusta e nessuna inventata → gli si affida anche la prima stesura dei testi in
italiano (spiegazioni delle uscite, riepilogo settimanale).
