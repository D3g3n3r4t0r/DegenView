"""Dove vivono i dati on-chain: sul volume, non dentro l'immagine.

Il server monta un volume su `backend/data`; `backend/app/data` e' codice e
si ricrea a ogni deploy. Listing, scartati, proposte del radar, scoperte del
pilota e registro delle operazioni stavano li' e sparivano a ogni
aggiornamento del sito (Lorenzo: "ho refreshato il sito e non ho piu'
l'elenco [...] dei token scartati e il token che prima era stato scelto non
lo vedo piu'").
"""
from __future__ import annotations

import shutil
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"      # backend/data: il volume
_OLD_DIR = Path(__file__).resolve().parents[2] / "data"      # backend/app/data: dentro l'immagine


def data_file(name: str) -> Path:
    """Il file sul volume; al primo avvio si porta dietro la copia vecchia."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    new, old = DATA_DIR / name, _OLD_DIR / name
    if not new.exists() and old.exists():
        try:
            shutil.copy2(old, new)
        except OSError:
            pass
    return new
