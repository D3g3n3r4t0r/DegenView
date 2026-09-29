"""Prelievo: mandare crypto (nativo o un token) a un indirizzo qualsiasi —
non uno swap (nessun altro token in cambio), ma la stessa sequenza
obbligata di execute.py: reserve() sul ledger PRIMA di firmare, firma,
invio solo se settings.onchain_execution_enabled, mark_submitted/
mark_confirmed dopo. Un prelievo mancato di questi passaggi sarebbe
firmabile due volte da un retry di rete — lo stesso motivo per cui
execute_order() li impone per gli swap.

Guardrail: stessi di un ordine manuale (tetto per operazione, tetto
giornaliero, circuit breaker, discrepanze) con strategy_name="manuale",
quindi la concentrazione NON si applica — un prelievo riduce sempre una
posizione, non la costruisce, e la scelta di quanto diversificare resta
dell'umano che lo firma di sua volonta' (stesso principio del bypass
gia' deciso per lo swap manuale, vedi risk.py)."""
import logging
import uuid

from app.config import settings
from app.trading.onchain import execute, execution, ledger, risk

logger = logging.getLogger(__name__)


async def send_token(
    owner_id: str, chain: str, token_label: str, to_address: str,
    amount: float, amount_raw: int, notional_usd: float, private_key_hex: str,
    is_native: bool, token_address: str | None, intent_id: str | None = None,
) -> dict:
    correlation_id = uuid.uuid4().hex
    idempotency_key = (execute.intent_key(owner_id, chain, intent_id) if intent_id
                       else f"send-{uuid.uuid4().hex}")
    existing = ledger.get_order(idempotency_key) if intent_id else None
    if existing is not None:
        return execute._replay(existing, token_label, "sell", correlation_id)
    logger.info(
        "[%s] send_token owner=%s chain=%s token=%s to=%s notional_usd=%.2f",
        correlation_id, owner_id, chain, token_label, to_address, notional_usd,
        extra={"correlation_id": correlation_id},
    )

    # price_impact_pct=0: un trasferimento non ha slippage, non e' un
    # quote — il controllo passa sempre, non e' quello che deve fermare
    # un prelievo sbagliato (l'indirizzo di destinazione, che nessun
    # guardrail automatico puo' validare, e' la responsabilita' di chi
    # firma: lo stesso principio per cui un wallet vero non "capisce" se
    # un indirizzo e' giusto).
    ok, reason = risk.run_safety_checks(owner_id, chain, token_label)
    if ok:
        ok, reason = risk.run_all_checks(owner_id, chain, token_label, notional_usd, 0.0, strategy_name="manuale")
    if not ok:
        logger.warning("[%s] rifiutato dal risk guardrail: %s", correlation_id, reason,
                        extra={"correlation_id": correlation_id})
        return {"accepted": False, "reason": reason, "idempotency_key": None, "tx_signature": None,
                "correlation_id": correlation_id}

    if chain not in ("solana", "robinhood"):
        return {"accepted": False, "reason": f"unsupported chain: {chain}",
                "idempotency_key": None, "tx_signature": None, "correlation_id": correlation_id}

    if not ledger.reserve(idempotency_key, owner_id, chain, token_label, "manuale", "sell", "live", notional_usd):
        logger.warning("[%s] idempotency_key duplicata: %s", correlation_id, idempotency_key,
                        extra={"correlation_id": correlation_id})
        return {"accepted": False, "reason": "withdrawal already in progress (duplicate idempotency key)",
                "idempotency_key": None, "tx_signature": None, "correlation_id": correlation_id}

    try:
        if chain == "solana":
            signed = await (
                execution.build_signed_solana_native_transfer(private_key_hex, to_address, amount_raw)
                if is_native else
                execution.build_signed_solana_token_transfer(private_key_hex, token_address, to_address, amount_raw)
            )
        else:
            signed = await (
                execution.build_signed_evm_native_transfer(private_key_hex, to_address, amount_raw)
                if is_native else
                execution.build_signed_evm_token_transfer(private_key_hex, token_address, to_address, amount_raw)
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] firma fallita: %s", correlation_id, exc, extra={"correlation_id": correlation_id})
        ledger.mark_failed(idempotency_key, f"signing failed: {exc}")
        return {"accepted": False, "reason": f"signing failed: {exc}",
                "idempotency_key": idempotency_key, "tx_signature": None, "correlation_id": correlation_id}

    if not settings.onchain_execution_enabled:
        logger.info("[%s] esecuzione reale disattivata, prelievo non inviato", correlation_id,
                     extra={"correlation_id": correlation_id})
        ledger.mark_failed(idempotency_key, "esecuzione reale disattivata (onchain_execution_enabled=False)")
        return {"accepted": False, "reason": "live execution disabled on this server",
                "idempotency_key": idempotency_key, "tx_signature": None, "correlation_id": correlation_id}

    ok, reason = risk.run_safety_checks(owner_id, chain, token_label)
    if not ok:
        ledger.mark_failed(idempotency_key, reason)
        return {"accepted": False, "reason": reason, "idempotency_key": idempotency_key, "tx_signature": None,
                "correlation_id": correlation_id}

    expected = {"expected_qty": amount, "expected_price_usd": notional_usd / amount if amount else 0.0,
                "price_impact_pct": 0.0}
    tx_id = execution.tx_id(chain, signed)
    if tx_id:
        ledger.mark_signed(idempotency_key, tx_id, **expected)
    try:
        signature = (
            await execution.send_signed_solana_tx(signed) if chain == "solana"
            else await execution.send_signed_evm_tx(signed)
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] invio fallito: %s", correlation_id, exc, extra={"correlation_id": correlation_id})
        if tx_id and not isinstance(exc, RuntimeError):
            ledger.mark_unknown(idempotency_key, f"send outcome unknown: {exc}")
            return {"accepted": False, "reason": f"send outcome unknown, checking the chain: {exc}",
                    "idempotency_key": idempotency_key, "tx_signature": tx_id, "correlation_id": correlation_id}
        ledger.mark_failed(idempotency_key, f"send failed: {exc}")
        return {"accepted": False, "reason": f"send failed: {exc}",
                "idempotency_key": idempotency_key, "tx_signature": None, "correlation_id": correlation_id}


    ledger.mark_submitted(idempotency_key, signature, **expected)
    logger.info("[%s] inviato tx=%s", correlation_id, signature, extra={"correlation_id": correlation_id})
    return {"accepted": True, "reason": "", "idempotency_key": idempotency_key, "tx_signature": signature,
            "status": "submitted", "correlation_id": correlation_id}
