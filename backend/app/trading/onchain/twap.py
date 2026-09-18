"""Quante fette, e con che ritardo — dal piano approvato: N = clamp(size
del pool / slippage per fetta, 2, N massimo per il gas). Non e' TWAP
istituzionale su minuti/ore: qui il costo e' il gas per fetta, non la
latenza, quindi il numero di fette resta piccolo (3-8) per pool poco
liquidi di token nuovi — sotto un notional minimo si esegue in un colpo
unico, TWAP escluso di proposito."""
import math
import random

DEFAULT_TARGET_SLIPPAGE_PCT = 1.0
DEFAULT_MAX_SLICES = 8
DEFAULT_MIN_SLICE_USD = 5.0
DEFAULT_BASE_DELAY_S = 30.0
DEFAULT_JITTER_PCT = 0.35  # +-35%, per non essere un pattern fisso in mempool


def slice_count(notional_usd: float, pool_liquidity_usd: float, target_slippage_pct: float = DEFAULT_TARGET_SLIPPAGE_PCT) -> int:
    """Quante fette servono perche' ognuna resti sotto target_slippage_pct
    di impatto stimato, dato quanto l'ordine pesa sulla liquidita' del pool."""
    if pool_liquidity_usd <= 0 or notional_usd <= 0:
        return 1
    size_pool_ratio_pct = (notional_usd / pool_liquidity_usd) * 100
    n = math.ceil(size_pool_ratio_pct / target_slippage_pct)
    n = max(1, n)
    # Sotto un notional minimo per fetta, il gas costerebbe piu' del
    # risparmio di slippage — meno fette, non piu' di quante il notional regge.
    max_by_min_slice = max(1, int(notional_usd // DEFAULT_MIN_SLICE_USD))
    n = min(n, max_by_min_slice, DEFAULT_MAX_SLICES)
    return max(n, 1)


def plan_slices(notional_usd: float, pool_liquidity_usd: float, target_slippage_pct: float = DEFAULT_TARGET_SLIPPAGE_PCT) -> list[float]:
    """Le size delle singole fette, non necessariamente identiche — l'ultima
    assorbe l'arrotondamento cosi' la somma torna esatta al centesimo."""
    n = slice_count(notional_usd, pool_liquidity_usd, target_slippage_pct)
    if n <= 1:
        return [round(notional_usd, 2)]
    base = round(notional_usd / n, 2)
    slices = [base] * (n - 1)
    slices.append(round(notional_usd - base * (n - 1), 2))
    return slices


def plan_delays_s(
    n: int, base_delay_s: float = DEFAULT_BASE_DELAY_S, jitter_pct: float = DEFAULT_JITTER_PCT,
    rng: random.Random | None = None,
) -> list[float]:
    """Un ritardo per ogni fetta DOPO la prima (che parte subito) — jitter
    randomico cosi' gli intervalli non sono un pattern fisso e riconoscibile
    in mempool. rng iniettabile per i test, altrimenti random di sistema."""
    rng = rng or random.Random()
    if n <= 1:
        return []
    return [base_delay_s * (1 + rng.uniform(-jitter_pct, jitter_pct)) for _ in range(n - 1)]
