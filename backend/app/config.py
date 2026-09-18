import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# When frozen (PyInstaller sidecar exe), read .env from next to the exe itself
# — not from the temp extraction dir, which never contains the user's real
# secrets. Same pattern as the DegenScan sidecar (binaries/.env next to the
# server exe, both shipped as Tauri resources).
if getattr(sys, "frozen", False):
    _ENV_FILE = Path(sys.executable).resolve().parent / ".env"
else:
    _ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8")

    # Le azioni sono spente: qui si opera solo in USDT/USDC. Tenerle accese
    # significava dipendere da TwelveData (7 richieste al minuto, il collo di
    # bottiglia piu' stretto del sistema) e ricevere avvisi di errore per
    # ticker che nessuno guarda. Rimettila a True e tutto torna com'era.
    stocks_enabled: bool = False

    # Lo sniper nasce come cacciatore di lanci, e un cacciatore di lanci trova
    # meme coin: Pump.fun e' un lanciatore di meme, e le soglie d'ingresso
    # (MC $1k, liquidita' $500, 30 giorni) sono quelle. Spento, il feed
    # Pump.fun non parte e l'archivio smette di riempirsi di quella roba.
    sniper_memecoins_enabled: bool = False

    # Interruttore generale, separato da quello sopra (che spegne solo il
    # feed Pump.fun): a False nessuno dei tre loop di fondo dello sniper
    # parte (polling dell'archivio, arricchimento CEX, agenti), e le scansioni
    # manuali rispondono che il servizio e' spento invece di girare comunque.
    # Rimettilo a True per riaccenderlo — nient'altro cambia. Spento su
    # richiesta di Lorenzo il 17/09.
    sniper_enabled: bool = False

    # Interruttore generale per l'intero sistema wallet on-chain (Fase 1: solo
    # generazione chiave + saldo, ancora nessuna firma) — a False ogni
    # endpoint /api/onchain/* risponde "disattivato" invece di girare
    # comunque. Serve come leva unica in caso di incidente: non tocca i dati
    # gia' salvati (le chiavi restano cifrate al loro posto), spegne solo
    # l'accesso.
    onchain_enabled: bool = True

    # Serve solo a costruire il link/QR di approvazione dal telefono per
    # rivelare una chiave on-chain — un URL relativo non e' scansionabile da
    # un secondo dispositivo.
    public_base_url: str = "https://liquidityengine.app"

    twelve_data_api_key: str = ""
    twelve_data_base_url: str = "https://api.twelvedata.com"

    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""  # comma-separated
    # Dove finiscono i messaggi di SISTEMA (deploy, errori 500), separati dagli
    # alert di trading che vanno alla chat personale di ogni utente. Vuota =
    # vanno in telegram_chat_ids, com'e' sempre stato.
    telegram_dev_chat_ids: str = ""  # comma-separated
    github_api_token: str = ""   # PAT for fetching commit history on deploy notify

    # Registration is open to anyone, but actual Telegram delivery is
    # deliberately locked to specific account emails (comma-separated) —
    # other registered users can still use the app/watchlist, just without
    # alerts going out, until this is opened up more broadly.
    telegram_allowed_emails: str = "lorenzocorazzi@gmail.com,whitekobra@icloud.com"

    # Chi puo' aprire un account. Il sito e' pubblico, e un account non e' un
    # dettaglio estetico: da' accesso all'ottimizzatore, che occupa un core
    # per minuti, e alla parte che conserva chiavi di trading. Vuoto =
    # registrazione aperta a chiunque (com'era prima, e non e' una buona idea
    # su un indirizzo pubblico).
    registration_allowed_emails: str = "lorenzocorazzi@gmail.com,whitekobra@icloud.com"

    # Read-only exchange account credentials, used ONLY for GET
    # account/balance endpoints (app/exchange_balances.py) — never for any
    # order/trade/withdrawal endpoint. Empty = that exchange's balance card
    # just shows "not configured" instead of erroring.
    mexc_api_key: str = ""
    mexc_api_secret: str = ""
    kucoin_api_key: str = ""
    kucoin_api_secret: str = ""
    kucoin_api_passphrase: str = ""

    # Personal exchange balances are sensitive — visible only to these
    # account emails (comma-separated), separate from the Telegram
    # allowlist since this isn't necessarily the same audience.
    balance_visible_emails: str = "lorenzocorazzi@gmail.com"

    # Timeframe set: HTF -> MTF -> LTF, matches PROMPT_SPEC.md section 5.
    # Each DataProvider maps these neutral keys to its own interval format.
    timeframe_keys: tuple[str, str, str] = ("htf", "mtf", "ltf")
    # 500 = MEXC's REST max; gives the "Lorenzo" strategy's 268-period trend
    # filter enough settled history instead of just ~30 usable candles. Only
    # used for htf/mtf, which need recent context, not deep history.
    candles_per_timeframe: int = 500
    # LTF drives the chart — kept at MEXC's own single-page cap (the
    # smallest of the three exchanges') so the chart's own fetch never
    # triggers pagination and stays a single fast request regardless of
    # exchange. Deeper history is what the dedicated backtest fetch below is
    # for, not this one.
    ltf_candles: int = 3000
    # The backtest is a separate, deliberately coarser fetch (see
    # `_backtest_interval` in main.py) so a chart set to 1m/5m doesn't cap
    # its own lookback to a few hours — 5000 daily candles is more than any
    # symbol's real listing history, so providers that support pagination
    # (the crypto exchanges) will walk pages back to the actual listing date
    # and stop there; it's a ceiling, not a target.
    backtest_candles: int = 5000

    # Kill switch: mette in pausa tutta l'esecuzione automatica degli ordini
    # senza toccare alert, backtest o ottimizzatore. Si attiva via endpoint
    # POST /api/trading/halt (richiede autenticazione) o da .env.
    trading_halt: bool = False


settings = Settings()
