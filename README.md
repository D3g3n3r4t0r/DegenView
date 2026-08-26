# Liquidity Analysis Engine

Software di analisi grafica (azioni + crypto) con rilevamento automatico di livelli di liquidità
in stile Smart Money Concepts (order block, fair value gap, equal highs/lows, BOS/CHoCH) su tre
timeframe personalizzabili (HTF/MTF/LTF, granularità a scelta stile TradingView), confluence
scoring cross-timeframe, indicatori tecnici classici, dati crypto live via MEXC (WebSocket) e un
motore di alert su strategie rule-based con notifiche Telegram opzionali.

La specifica completa è in [PROMPT_SPEC.md](PROMPT_SPEC.md).

## Avvio locale

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Poi apri `http://127.0.0.1:8000` nel browser.

**Nota**: non usare `--reload` — su questo setup Windows il reloader di uvicorn si è dimostrato
inaffidabile (si blocca a metà senza completare il riavvio). Dopo ogni modifica al backend,
riavvia manualmente il processo.

## Configurazione (`backend/.env`, vedi `backend/.env.example`)

- `TWELVE_DATA_API_KEY` — **richiesta** per le azioni. Chiave gratuita su [Twelve Data](https://twelvedata.com).
  Piano free: 8 richieste/minuto, 800/giorno; ogni ricerca consuma 3 richieste (una per timeframe),
  poi cache 90s (intraday) / 10min (daily+). Le crypto non ne hanno bisogno: usano MEXC, dati pubblici.
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_IDS` — opzionali, per ricevere su Telegram gli alert della
  strategia. Setup: @BotFather su Telegram → `/newbot` → copia il token; scrivi un messaggio al bot
  appena creato, poi apri `https://api.telegram.org/bot<TOKEN>/getUpdates` per leggere il tuo chat_id.

## Struttura

- `backend/app/providers/` — dati di mercato: Twelve Data (azioni), MEXC (crypto, REST + WebSocket)
- `backend/app/live/mexc_stream.py` — relay WebSocket per candele crypto in tempo reale
- `backend/app/analysis/` — motore SMC (`smartmoneyconcepts`), indicatori (`pandas-ta`), confluence scoring, summary
- `backend/app/analysis/strategies.py` — motore alert (porting della strategia trend-follower "Lorenzo")
- `backend/app/notify/` — invio notifiche Telegram, tracking dei segnali già notificati
- `backend/app/timeframes.py` — intervalli disponibili per HTF/MTF/LTF
- `backend/app/main.py` — endpoint `/api/analyze`, `/api/symbols`, `/ws/live`
- `frontend/` — pagina singola con TradingView Lightweight Charts

## Note ambiente

Il venv usa **Python 3.13**, non 3.14: `numba` (dipendenza di `pandas-ta`) non supporta ancora
Python 3.14 su questo sistema al momento della creazione del progetto.
