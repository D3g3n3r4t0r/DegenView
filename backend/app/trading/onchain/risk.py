"""Guardrail confermati da Lorenzo il 19/09/2026 (config.py):
tetto per operazione, tetto giornaliero, concentrazione per token.

Ogni funzione ritorna (ok: bool, reason: str) — mai un'eccezione per un
rifiuto normale: un ordine rifiutato per slippage o tetto e' un esito
previsto del sistema, non un errore. reason e' sempre in italiano, e'
quello che finisce nel log e nell'eventuale notifica."""
from app.config import settings
from app.trading.onchain import ledger


def check_per_trade_cap(size_usd: float) -> tuple[bool, str]:
    if size_usd > settings.onchain_max_usd_per_trade:
        return False, (
            f"size {size_usd:.2f} USD sopra il tetto per operazione "
            f"({settings.onchain_max_usd_per_trade:.2f} USD)"
        )
    return True, ""


def check_daily_cap(owner_id: str, chain: str, size_usd: float) -> tuple[bool, str]:
    spent = ledger.get_daily_spent(owner_id, chain)
    if spent + size_usd > settings.onchain_max_usd_per_day:
        return False, (
            f"spenderebbe {spent + size_usd:.2f} USD oggi su {chain}, "
            f"sopra il tetto giornaliero ({settings.onchain_max_usd_per_day:.2f} USD)"
        )
    return True, ""


def check_concentration(owner_id: str, chain: str, token: str, additional_usd: float) -> tuple[bool, str]:
    """Concentrazione relativa DENTRO il portafoglio on-chain di questa
    chain (somma del costo di tutte le posizioni), non rispetto al saldo
    nativo del wallet — quello richiederebbe un prezzo SOL/ETH in USD che
    qui non abbiamo ancora. Semplificazione dichiarata, non nascosta: il
    vero backstop resta il controllo di slippage/price-impact sul quote,
    questo e' una difesa in piu', non l'unica."""
    positions = ledger.get_all_positions(owner_id, chain)
    existing_token_cost = next((p["cost_usd"] for p in positions if p["token"] == token), 0.0)
    total_portfolio_cost = sum(p["cost_usd"] for p in positions)
    if total_portfolio_cost <= 0:
        # Nessuna posizione ancora aperta: la prima operazione e' per forza
        # il 100% di un portafoglio vuoto — il tetto ha senso solo dal
        # momento in cui esiste un portafoglio con cui confrontarsi.
        return True, ""
    new_token_cost = existing_token_cost + additional_usd
    new_total = total_portfolio_cost + additional_usd
    pct = (new_token_cost / new_total) * 100
    if pct > settings.onchain_max_token_concentration_pct:
        return False, (
            f"{token} sarebbe il {pct:.1f}% del portafoglio on-chain su {chain}, "
            f"sopra il tetto di concentrazione ({settings.onchain_max_token_concentration_pct:.0f}%)"
        )
    return True, ""


def check_circuit_breaker(owner_id: str, chain: str) -> tuple[bool, str]:
    status = ledger.breaker_status(owner_id, chain)
    if status["tripped"]:
        return False, f"circuit breaker attivo su {chain}: {status['reason']} — riattivazione manuale richiesta"
    return True, ""


# Soglie del price impact, dal piano approvato (revisione risk management).
PRICE_IMPACT_WARN_PCT = 1.0
PRICE_IMPACT_REJECT_PCT = 5.0


def check_price_impact(price_impact_pct: float) -> tuple[bool, str]:
    """Il vero backstop contro lo slippage assurdo: sotto l'1% passa senza
    fiatare, fra 1-5% passa ma andrebbe loggato come WARNING da chi chiama,
    sopra il 5% e' un rifiuto secco — nessuna transazione va inviata."""
    if price_impact_pct > PRICE_IMPACT_REJECT_PCT:
        return False, f"price impact {price_impact_pct:.2f}% sopra il tetto assoluto ({PRICE_IMPACT_REJECT_PCT:.0f}%)"
    return True, ""


def run_all_checks(
    owner_id: str, chain: str, token: str, size_usd: float, price_impact_pct: float,
) -> tuple[bool, str]:
    """Tutti i controlli in ordine, ferma al primo che rifiuta — l'ordine
    di questa lista e' quello suggerito dal piano: prima il circuit
    breaker (nessun senso controllare altro se e' gia' scattato), poi i
    tetti in USD (piu' cheap da calcolare), poi price impact (richiede un
    quote gia' in mano) e concentrazione."""
    for check, args in (
        (check_circuit_breaker, (owner_id, chain)),
        (check_per_trade_cap, (size_usd,)),
        (check_daily_cap, (owner_id, chain, size_usd)),
        (check_price_impact, (price_impact_pct,)),
        (check_concentration, (owner_id, chain, token, size_usd)),
    ):
        ok, reason = check(*args)
        if not ok:
            return False, reason
    return True, ""
