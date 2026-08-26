"""
Entry point packaged into the sidecar exe by PyInstaller (see
liquidity-server.spec). Runs identically as a plain script: `python app_entry.py`.
"""

import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # frozen with redirected/null stdio may not support reconfigure


def main() -> None:
    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
