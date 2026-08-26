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

    twelve_data_api_key: str = ""
    twelve_data_base_url: str = "https://api.twelvedata.com"

    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""  # comma-separated

    # Timeframe set: HTF -> MTF -> LTF, matches PROMPT_SPEC.md section 5.
    # Each DataProvider maps these neutral keys to its own interval format.
    timeframe_keys: tuple[str, str, str] = ("htf", "mtf", "ltf")
    # 500 = MEXC's REST max; gives the "Lorenzo" strategy's 268-period trend
    # filter enough settled history instead of just ~30 usable candles.
    candles_per_timeframe: int = 500


settings = Settings()
