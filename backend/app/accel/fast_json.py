"""SIMD-accelerated JSON encoding/decoding (`orjson` with transparent stdlib fallback)
and mtime-aware in-memory JSON file cache so disk JSON files (`onchain_arena_ladder.json`,
`onchain_arena_tenure.json`, `onchain_sector_snapshots.json`, `resolutions.json`, etc.)
are never re-parsed when unchanged on disk.
"""

from __future__ import annotations

import json as _stdlib_json
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

try:
    import orjson as _orjson  # type: ignore[import-not-found]
    HAS_ORJSON = True
except Exception:
    _orjson = None
    HAS_ORJSON = False

# Statistics for /api/perf telemetry
_stats = {
    "json_loads": 0,
    "json_dumps": 0,
    "http_responses": 0,
    "file_cache_hits": 0,
    "file_cache_misses": 0,
}


class FastJSONResponse(JSONResponse):
    """Drop-in FastAPI `JSONResponse` replacement powered by Rust SIMD `orjson`.

    Falls back to Starlette's standard `JSONResponse.render()` if an object
    contains custom types unsupported by `orjson`.
    """

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        _stats["http_responses"] += 1
        if _orjson is not None:
            try:
                return _orjson.dumps(
                    content,
                    option=_orjson.OPT_NON_STR_KEYS | _orjson.OPT_SERIALIZE_NUMPY,
                )
            except (TypeError, ValueError):
                pass
        return super().render(content)

# (path_str) -> (mtime_ns, size, parsed_obj)
_file_cache: dict[str, tuple[int, int, Any]] = {}


def loads(data: str | bytes) -> Any:
    """Parse JSON using Rust SIMD `orjson` when available, with stdlib fallback."""
    _stats["json_loads"] += 1
    if _orjson is not None:
        try:
            return _orjson.loads(data)
        except Exception:
            return _stdlib_json.loads(data)
    return _stdlib_json.loads(data)


def dumps(obj: Any) -> str:
    """Serialize object to JSON string using `orjson` when available."""
    _stats["json_dumps"] += 1
    if _orjson is not None:
        try:
            return _orjson.dumps(obj).decode("utf-8")
        except Exception:
            return _stdlib_json.dumps(obj, ensure_ascii=False)
    return _stdlib_json.dumps(obj, ensure_ascii=False)


def read_json_cached(path: Path, default: Any = None) -> Any:
    """Read and parse a JSON file from disk with `(mtime_ns, size)` in-memory caching."""
    try:
        st = path.stat()
    except OSError:
        return default
    key = str(path)
    hit = _file_cache.get(key)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        _stats["file_cache_hits"] += 1
        return hit[2]
    _stats["file_cache_misses"] += 1
    try:
        raw = path.read_bytes()
        parsed = loads(raw)
        _file_cache[key] = (st.st_mtime_ns, st.st_size, parsed)
        return parsed
    except Exception:
        return default


def invalidate_file_cache(path: Path | str | None = None) -> None:
    if path is None:
        _file_cache.clear()
    else:
        _file_cache.pop(str(path), None)


def stats() -> dict[str, Any]:
    return {
        "engine": "orjson-simd" if HAS_ORJSON else "stdlib-json",
        "has_orjson": HAS_ORJSON,
        **_stats,
        "cached_files": len(_file_cache),
    }
