"""Fase 2 del piano: paper trading. Stessi controlli di rischio e stesso
ledger della Fase 3, ma mode='simulated' — mai una chiave, mai una firma,
mai una transazione. Serve a vedere se il sistema (guardrail, size,
concentrazione) si comporta bene su dati di mercato reali prima di
rischiare fondi veri."""
import uuid

from app.trading.onchain import ledger, risk


def simulate_order(
    owner_id: str, chain: str, token: str, strategy_name: str, side: str,
    notional_usd: float, price_impact_pct: float, price_usd: float,
) -> dict:
    """Ritorna sempre un esito (mai un'eccezione per un rifiuto normale):
    {'accepted': bool, 'reason': str, 'idempotency_key': str|None}."""
    ok, reason = risk.run_all_checks(owner_id, chain, token, notional_usd, price_impact_pct)
    if not ok:
        return {"accepted": False, "reason": reason, "idempotency_key": None}

    # Chiave diversa ad ogni chiamata apposta: una simulazione non ha un
    # segnale reale da cui derivare una chiave deterministica come Fase 3
    # avra' (qui e' l'utente/API a chiedere "provalo ora", non uno
    # scheduler che potrebbe ripetersi).
    idempotency_key = f"sim-{uuid.uuid4().hex}"
    reserved = ledger.reserve(idempotency_key, owner_id, chain, token, strategy_name, side, "simulated", notional_usd)
    if not reserved:
        return {"accepted": False, "reason": "chiave duplicata, riprova", "idempotency_key": None}

    executed_qty = notional_usd / price_usd if price_usd > 0 else 0.0
    ledger.mark_confirmed(idempotency_key, executed_qty=executed_qty, executed_price_usd=price_usd, price_impact_pct=price_impact_pct)
    return {"accepted": True, "reason": "", "idempotency_key": idempotency_key}
