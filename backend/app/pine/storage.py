import json
import re
import time
import uuid
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pine_scripts"
_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
_VALID_SCRIPT_ID = re.compile(r"^[a-zA-Z0-9_-]{1,120}$")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return slug or "script"


def save_script(name: str, source: str, default_params: dict) -> dict:
    script_id = f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
    meta = {
        "id": script_id,
        "name": name,
        "created_at": int(time.time()),
        "default_params": default_params,
    }
    (_SCRIPTS_DIR / f"{script_id}.pine").write_text(source, encoding="utf-8")
    (_SCRIPTS_DIR / f"{script_id}.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def list_scripts() -> list[dict]:
    out = []
    for meta_path in sorted(_SCRIPTS_DIR.glob("*.json")):
        try:
            out.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def load_script(script_id: str) -> tuple[dict, str] | None:
    if not _VALID_SCRIPT_ID.match(script_id or ""):
        return None
    meta_path = _SCRIPTS_DIR / f"{script_id}.json"
    src_path = _SCRIPTS_DIR / f"{script_id}.pine"
    if not meta_path.exists() or not src_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source = src_path.read_text(encoding="utf-8")
    return meta, source


def delete_script(script_id: str) -> bool:
    if not _VALID_SCRIPT_ID.match(script_id or ""):
        return False
    meta_path = _SCRIPTS_DIR / f"{script_id}.json"
    src_path = _SCRIPTS_DIR / f"{script_id}.pine"
    if not meta_path.exists():
        return False
    meta_path.unlink(missing_ok=True)
    src_path.unlink(missing_ok=True)
    return True
