# Note per Claude

## Da fare a ogni conversazione, prima di altro

Leggi la bacheca segnalazioni:

```
curl -s https://liquidity-analysis-engine.fly.dev/api/issues
```

Sono i problemi che Lorenzo e chi lavora con lui hanno scritto dall'app. Se ce
ne sono di nuovi o di aperti, dillo subito e proponi da quale partire, senza
aspettare che te lo chiedano.

Quando risolvi qualcosa, scrivi la risoluzione in
`backend/app/data/resolutions.json`, con chiave uguale all'`id` della
segnalazione. **Non modificare le segnalazioni**: quelle vivono sul volume Fly e
appartengono a chi le ha scritte.

| | dove vive | chi scrive |
|---|---|---|
| segnalazioni | volume Fly, `data/issues.json` | loro, dall'app |
| risoluzioni | repo, `app/data/resolutions.json` | Claude, via git |

L'unione avviene in lettura, per `id`. Un id che non corrisponde a nessuna
segnalazione è una diagnosi che nessuno vedrà mai — c'è un test che lo verifica.

## Il progetto

FastAPI + frontend vanilla JS, deploy automatico su Fly da `main` (2-3 minuti).
Il codice sta in `backend/app`, il frontend in `frontend/`.

**Python 3.12 obbligatorio** — `pandas-ta` non si installa su 3.11. Se la shell
ha una versione più vecchia: `uv venv --python 3.12 backend/.venv`, poi
`uv pip install --python backend/.venv/bin/python -r backend/requirements.txt`.

Tre strategie, e **una sola è trend-following**:

| strategia | meccanica | famiglia |
|---|---|---|
| Lorenzo | incrocio EMA sulla derivata di una media | trend-following |
| Gabriele | RSI + banda di Bollinger | mean-reversion |
| Accumulo / Distribuzione | divergenze RSI su swing | contro-trend |

Confonderle è il modo più facile di sbagliare: un filtro che chiede persistenza
è giusto per la prima e rovesciato per le altre due.

## Cose misurate, da non riderivare

- **L'obiettivo del backtest è una funzione a gradini.** 200 valori di un
  parametro danno 5 risultati distinti; il 98% dei passi non cambia nulla. I
  metodi che presuppongono continuità (Nelder-Mead, CMA-ES, ottimizzazione
  bayesiana con kernel lisci) qui non si applicano.
- **La ricerca casuale è una lotteria.** Stessa serie, cambia solo il seed:
  `cv_oos` 66% su Gabriele, 225% su Lorenzo. Con la pipeline deterministica
  scende a 0% — ma solo dove le celle si enumerano.
- **Su KASUSDT daily nessuna delle due strategie ha edge.** Il gate blocca
  entrambe (VR≈1.15, indistinguibile da random walk), tutti i seed danno OOS
  negativo, e buy-and-hold faceva +643%.
- **Il PBO conferma il verdetto dello Sharpe deflazionato, non lo duplica.** Su
  una serie senza edge: PBO 0.56 su 5 candidati (soglia 0.20), DSR 0.02. Il
  primo giudica la *selezione*, il secondo corregge un *numero* — un risultato
  può superare l'uno e fallire l'altro.
- **Più parametri = risultato peggiore.** Il ramo di Lorenzo a 4 parametri batte
  quello a 8 sia in-sample sia fuori campione.

## Cose che scottano

- `/api/optimize` gira su un feed diverso dal grafico (`backtest_interval_for()`
  forza il minimo a `1d`) e non lo dichiara: stessi parametri, 27 trade contro
  186. È la segnalazione `seed-0007`.
- `_find_confirmation()` in `strategies.py` parte da `swing_pos + 1`, ma uno
  swing è identificabile solo dopo `swing_length` barre: il 97% degli ingressi
  di Accumulo/Distribuzione usa informazione futura. È `seed-0010`, e il fix
  abbassa tutti i risultati storici — non applicarlo senza dirlo.

## Verifiche prima di committare

```
cd backend && .venv/bin/python -m pytest tests/ -q
ruff check backend/app backend/tests
node --check frontend/static/app.js
```

LibreOffice in sandbox non ricalcola i file Excel: `recalc.py` fallisce
all'avvio, non per colpa del file.

## Lingua

Lorenzo scrive in italiano. Rispondi in italiano; commenti e messaggi di commit
in inglese, come il resto del codice.
