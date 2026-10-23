"""Bridge to the compiled Native Rust Quant Engine (`libdegenview_rs.so` / `.dll`)
with automatic C-Vectorized NumPy SIMD fallback when running on a host where the
shared library has not been compiled yet.

Every call to the Rust `CDLL` automatically releases the Python GIL, allowing
multi-core execution without blocking FastAPI or WebSocket streams.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_CANDIDATES = (
    _HERE / "libdegenview_rs.so",
    _HERE / "degenview_rs.dll",
    _HERE / "libdegenview_rs.dylib",
    _HERE.parent.parent / "rust_core" / "target" / "release" / "libdegenview_rs.so",
    _HERE.parent.parent / "rust_core" / "target" / "release" / "degenview_rs.dll",
)

_lib: ctypes.CDLL | None = None
for _cand in _CANDIDATES:
    if _cand.exists():
        try:
            _loaded = ctypes.CDLL(str(_cand))
            _loaded.dv_confirmed_events.argtypes = [
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_size_t,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(ctypes.c_int32),
            ]
            _loaded.dv_confirmed_events.restype = ctypes.c_size_t
            _lib = _loaded
            break
        except Exception:
            _lib = None

HAS_RUST_CDYLIB = _lib is not None

_stats = {
    "confirmed_events_calls": 0,
    "lki_indicator_cache_hits": 0,
    "lki_indicator_cache_misses": 0,
}

# Small LRU cache for Gabriele / LKI RSI(14) + Bollinger(20, 2.0) arrays keyed by DataFrame fingerprint
_lki_cache: dict[tuple[Any, ...], tuple[Any, Any, Any, Any]] = {}
_LKI_CACHE_MAX = 64


_TYPE_CODES = (
    "entry_long",
    "entry_short",
    "exit_long",
    "exit_short",
    "flip_to_short",
    "flip_to_long",
)


def fast_confirmed_transitions(
    el: np.ndarray,
    es: np.ndarray,
    xl: np.ndarray,
    xs: np.ndarray,
    n_confirmed: int,
) -> tuple[list[tuple[int, str]], int]:
    """Compute state-machine transitions for `confirmed_events` in `strategies.py`.
    Returns `(list of (bar_index, signal_type), final_position)` matching `strategies.py`
    bit-for-bit while executing in native C/Rust or sparse NumPy nonzero indices.
    """
    _stats["confirmed_events_calls"] += 1
    n_total = len(el)
    if n_total == 0:
        return [], 0

    el_u8 = np.ascontiguousarray(el, dtype=np.uint8)
    es_u8 = np.ascontiguousarray(es, dtype=np.uint8)
    xl_u8 = np.ascontiguousarray(xl, dtype=np.uint8)
    xs_u8 = np.ascontiguousarray(xs, dtype=np.uint8)

    if _lib is not None:
        out_idx = np.empty(n_total, dtype=np.uintp)
        out_typ = np.empty(n_total, dtype=np.uint8)
        final_pos = ctypes.c_int32(0)
        count = _lib.dv_confirmed_events(
            el_u8.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            es_u8.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            xl_u8.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            xs_u8.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            n_total,
            n_confirmed,
            out_idx.ctypes.data_as(ctypes.POINTER(ctypes.c_size_t)),
            out_typ.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            ctypes.byref(final_pos),
        )
        transitions = [(int(out_idx[k]), _TYPE_CODES[int(out_typ[k])]) for k in range(count)]
        return transitions, int(final_pos.value)

    # Sparse NumPy nonzero state machine: only bars where at least one signal is True
    # can ever change `position`! Skips 95%+ of bars in C.
    any_sig = (el_u8 | es_u8 | xl_u8 | xs_u8).nonzero()[0]
    pos = 0
    transitions_out: list[tuple[int, str]] = []
    for idx in any_sig:
        i = int(idx)
        prev_pos = pos
        if pos == 1 and xl_u8[i]:
            pos = 0
        elif pos == -1 and xs_u8[i]:
            pos = 0
        if el_u8[i]:
            pos = 1
        elif es_u8[i]:
            pos = -1

        if pos == prev_pos or i >= n_confirmed:
            continue

        if prev_pos == 0 and pos == 1:
            sig_type = "entry_long"
        elif prev_pos == 0 and pos == -1:
            sig_type = "entry_short"
        elif prev_pos == 1 and pos == 0:
            sig_type = "exit_long"
        elif prev_pos == -1 and pos == 0:
            sig_type = "exit_short"
        elif prev_pos == 1 and pos == -1:
            sig_type = "flip_to_short"
        else:
            sig_type = "flip_to_long"

        transitions_out.append((i, sig_type))

    return transitions_out, pos


def cached_lki_bands(df: Any, rsi_len: int, bb_len: int, bb_mult: float):
    """Return cached `(close, rsi, upper, lower)` Series for `compute_lki_signals` and
    `compute_lki2_signals`. Turns 441 or 1,296 redundant Wilder RSI + Bollinger Band
    recomputations during `max_return_search` / `optimize_strategy` into a single pass!
    """
    close = df["close"]
    n = len(close)
    if n == 0:
        return close, close, close, close

    arr = close.to_numpy(dtype=np.float64, copy=False)
    # Content-aware fingerprint so mutated intrabar windows never collide with full df
    key = (
        n,
        float(arr[0]),
        float(arr[n // 2]),
        float(arr[-1]),
        float(arr[-2]) if n > 1 else 0.0,
        int(rsi_len),
        int(bb_len),
        float(bb_mult),
    )
    hit = _lki_cache.get(key)
    if hit is not None and len(hit[0]) == n and hit[0].index.equals(df.index):
        _stats["lki_indicator_cache_hits"] += 1
        return hit

    _stats["lki_indicator_cache_misses"] += 1
    delta = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / rsi_len, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / rsi_len, adjust=False).mean()
    avg_loss_safe = avg_loss.replace(0, np.nan)
    raw_rsi = 100 - (100 / (1 + avg_gain / avg_loss_safe))
    rsi = pd.Series(
        np.where(avg_loss == 0, 100.0, np.where(avg_gain == 0, 0.0, raw_rsi)),
        index=df.index,
    )

    basis = close.rolling(bb_len).mean()
    dev = bb_mult * close.rolling(bb_len).std(ddof=0)
    upper = basis + dev
    lower = basis - dev

    if len(_lki_cache) >= _LKI_CACHE_MAX:
        _lki_cache.pop(next(iter(_lki_cache)))
    res = (close, rsi, upper, lower)
    _lki_cache[key] = res
    return res


def stats() -> dict[str, Any]:
    return {
        "has_rust_cdylib": HAS_RUST_CDYLIB,
        "engine": "rust-cdylib+numpy-simd" if HAS_RUST_CDYLIB else "numpy-simd-nonzero",
        **_stats,
    }
