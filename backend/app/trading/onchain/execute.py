"""Fase 4: l'ordine vero, non simulato — stessi guardrail di simulate.py,
ma con una chiave, una rete, e (solo se acceso) un invio reale.

Entrambe le chain hanno ora un percorso di firma reale: Solana via
Jupiter (verificato dal vivo fino all'invio), Robinhood Chain via
SwapRouter02.exactInputSingle (router/QuoterV2/Factory tutti verificati
dal vivo il 19/09/2026 — vedi quotes.py/execution.py) — ma quest'ultima
NON e' mai stata provata con un invio vero (nessuna transazione reale
mandata in questa sessione, solo quote e getPool in lettura): il codice
di firma e' reale, l'esperienza dal vivo dell'invio no. Non un motivo per
bloccarla del tutto (il guardrail di settings.onchain_execution_enabled
resta comunque spento di default), ma un motivo per accenderla con
prudenza — size piccole, prima operazione osservata a mano.

settings.onchain_execution_enabled resta la sola porta che decide se
l'invio (mai la firma) parte davvero: qui e' controllato esplicitamente,
non delegato a execution.send_signed_solana_tx/send_signed_evm_tx (che di
proposito non lo controllano da soli)."""
import uuid

from app.config import settings
from app.trading.onchain import execution, ledger, risk


async def execute_order(
    owner_id: str, chain: str, token: str, strategy_name: str, side: str,
    notional_usd: float, price_impact_pct: float, price_usd: float,
    private_key_hex: str, quote: dict,
) -> dict:
    ok, reason = risk.run_all_checks(owner_id, chain, token, notional_usd, price_impact_pct)
    if not ok:
        return {"accepted": False, "reason": reason, "idempotency_key": None, "tx_signature": None}

    if chain not in ("solana", "robinhood"):
        return {"accepted": False, "reason": f"chain non supportata: {chain}",
                "idempotency_key": None, "tx_signature": None}

    idempotency_key = f"live-{uuid.uuid4().hex}"
    if not ledger.reserve(idempotency_key, owner_id, chain, token, strategy_name, side, "live", notional_usd):
        return {"accepted": False, "reason": "ordine gia' in corso (chiave idempotente duplicata)",
                "idempotency_key": None, "tx_signature": None}

    try:
        if chain == "solana":
            signed = await execution.build_signed_solana_swap(private_key_hex, quote)
        else:
            signed = await execution.build_signed_robinhood_swap(
                private_key_hex, quote["token_in"], quote["token_out"], quote["fee"],
                quote["amount_in"], quote["amount_out_minimum"],
            )
    except Exception as exc:
        ledger.mark_failed(idempotency_key, f"firma fallita: {exc}")
        return {"accepted": False, "reason": f"firma fallita: {exc}",
                "idempotency_key": idempotency_key, "tx_signature": None}

    if not settings.onchain_execution_enabled:
        ledger.mark_failed(idempotency_key, "esecuzione reale disattivata (onchain_execution_enabled=False)")
        return {"accepted": False, "reason": "esecuzione reale disattivata su questo server",
                "idempotency_key": idempotency_key, "tx_signature": None}

    try:
        if chain == "solana":
            signature = await execution.send_signed_solana_tx(signed)
        else:
            signature = await execution.send_signed_evm_tx(signed)
    except Exception as exc:
        ledger.mark_failed(idempotency_key, f"invio fallito: {exc}")
        return {"accepted": False, "reason": f"invio fallito: {exc}",
                "idempotency_key": idempotency_key, "tx_signature": None}

    ledger.mark_submitted(idempotency_key, signature)
    ledger.mark_confirmed(
        idempotency_key,
        executed_qty=notional_usd / price_usd,
        executed_price_usd=price_usd,
        price_impact_pct=price_impact_pct,
    )
    return {"accepted": True, "reason": "", "idempotency_key": idempotency_key, "tx_signature": signature}
