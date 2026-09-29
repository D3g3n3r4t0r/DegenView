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
proposito non lo controllano da soli).

Ogni chiamata genera un correlation_id (uuid4, diverso dalla idempotency_key
del ledger) loggato su OGNI riga di log di questo ordine — piano SRE punto 2.
Non e' una persistenza a 30 giorni dedicata: questo processo scrive su
stdout/stderr senza una rotazione di log configurata da nessuna parte nel
sito (verificato: nessun logging.basicConfig/RotatingFileHandler in
main.py o altrove) — chi gestisce il deploy deve avere una rotazione a
livello di systemd/docker (es. `journalctl`, `docker logs` con
`max-size`/`max-file`) se vuole i 30 giorni richiesti dal piano. Gap noto,
non silenziato: costruire qui un secondo sistema di log parallelo solo per
onchain sarebbe piu' rischio (due fonti di verita' sui log) che beneficio."""
import hashlib
import logging
import uuid

from app.config import settings
from app.trading.onchain import execution, jito, ledger, pool_safety, prices, risk

logger = logging.getLogger("onchain_execute")


async def _send_solana_with_jito_fallback(
    correlation_id: str, private_key_hex: str, signed_tx_bytes: bytes, notional_usd: float,
) -> str:
    """Piano MEV: instrada via Jito bundle (transazione firmata + tip in un
    bundle atomico, che riduce la finestra di front-run) e ricade
    sull'invio diretto via RPC (send_signed_solana_tx, il percorso di
    prima, mai toccato) se Jito e' spento o non risponde in modo sensato.
    Un bundle Jito non da' MAI una signature vera e propria come una
    sendTransaction — da' un bundle_id — quindi in caso di successo il
    "signature" ritornato qui e' il bundle_id, prefissato per essere
    distinguibile in log e nel ledger da una signature RPC diretta."""
    if not settings.onchain_use_jito:
        return await execution.send_signed_solana_tx(signed_tx_bytes)

    try:
        sol_price_usd = await prices.native_price_usd("solana") or 0.0
        tip_lamports = jito.compute_dynamic_tip_lamports(notional_usd, sol_price_usd)
        tip_account = jito.pick_tip_account()
        tip_tx = await execution.build_signed_solana_tip_tx(private_key_hex, tip_account, tip_lamports)
        bundle_id = await jito.send_bundle_via_jito(signed_tx_bytes, tip_tx)
        logger.info("[%s] inviato via Jito bundle, tip=%d lamports -> %s", correlation_id, tip_lamports, bundle_id,
                     extra={"correlation_id": correlation_id})
        return f"jito:{bundle_id}"
    except Exception as exc:
        logger.warning("[%s] Jito non disponibile (%s), fallback su invio RPC diretto", correlation_id, exc,
                        extra={"correlation_id": correlation_id})
        return await execution.send_signed_solana_tx(signed_tx_bytes)


def intent_key(owner_id: str, chain: str, intent_id: str) -> str:
    digest = hashlib.sha256(f"{owner_id}|{chain}|{intent_id}".encode()).hexdigest()[:32]
    return f"intent-{digest}"


def _replay(order: dict, token: str, side: str, correlation_id: str) -> dict:
    """The same intent again: report what the first attempt did. The same id
    with a different trade is a client bug, refused."""
    if order["token"] != token or order["side"] != side:
        return {"accepted": False, "reason": "this order id was already used for a different trade",
                "idempotency_key": None, "tx_signature": None, "correlation_id": correlation_id}
    accepted = order["status"] in ("signed", "submitted", "confirmed", "unknown")
    reason = "" if accepted else ("order already in progress" if order["status"] == "pending"
                                  else order.get("reason") or "already attempted")
    return {"accepted": accepted, "reason": reason,
            "idempotency_key": order["idempotency_key"], "tx_signature": order.get("tx_signature"),
            "status": order["status"], "duplicate": True, "correlation_id": correlation_id}


async def execute_order(
    owner_id: str, chain: str, token: str, strategy_name: str, side: str,
    notional_usd: float, price_impact_pct: float, price_usd: float,
    private_key_hex: str, quote: dict,
    pool_address: str | None = None,
    guards: bool = True,
    intent_id: str | None = None,
) -> dict:
    """intent_id: stable for one decision (a click, a signal). A retry with
    the same one returns the order already made instead of a second trade
    (audit 29/09, S03)."""
    correlation_id = uuid.uuid4().hex
    idempotency_key = intent_key(owner_id, chain, intent_id) if intent_id else f"live-{uuid.uuid4().hex}"
    existing = ledger.get_order(idempotency_key) if intent_id else None
    if existing is not None:
        return _replay(existing, token, side, correlation_id)
    logger.info(
        "[%s] execute_order owner=%s chain=%s token=%s side=%s notional_usd=%.2f",
        correlation_id, owner_id, chain, token, side, notional_usd,
        extra={"correlation_id": correlation_id},
    )

    # Allowlist pool + size dinamica, ricalcolate ad ogni tentativo — non
    # solo alla prima. pool_address opzionale: se manca (chain non ancora
    # coperta da DexScreener, o il chiamante non lo passa) il comportamento
    # e' quello di prima, nessuna riduzione e nessun controllo di allowlist.
    pool_info = None
    pool_liquidity_usd = None
    if pool_address is not None:
        snapshot = await pool_safety.fetch_pool_snapshot(chain, pool_address)
        pool_liquidity_usd = snapshot["liquidity_usd"] if snapshot else None
        if pool_liquidity_usd is not None:
            ledger.record_pool_liquidity(chain, pool_address, pool_liquidity_usd)
        reference_max = ledger.max_pool_liquidity_since(chain, pool_address)
        pool_info = {
            "liquidity_usd": pool_liquidity_usd,
            "created_at": snapshot["created_at"] if snapshot else None,
            "reference_max_liquidity_usd": reference_max,
        }

    # guards=False: the system's autotrader, whose only limit is the share of
    # the balance Lorenzo picks ("solo la % scelta"): no per-trade cap, no
    # pool clamp, no impact veto. Ledger, idempotency and the server switch stay.
    ok, reason = risk.run_safety_checks(owner_id, chain, token)
    if ok and guards:
        # The quote (and so the signed amount) is fixed by the caller: a
        # smaller size here would shrink only the ledger row, not the swap
        # (audit 29/09, S02). Refuse instead of pretending.
        allowed_usd = risk.clamp_size_to_pool(notional_usd, pool_liquidity_usd)
        if allowed_usd < notional_usd - 0.01:
            ok, reason = False, (
                f"size {notional_usd:.2f} USD above what this pool allows ({allowed_usd:.2f} USD): lower the amount"
            )
        else:
            ok, reason = risk.run_all_checks(
                owner_id, chain, token, notional_usd, price_impact_pct, pool_info=pool_info,
                strategy_name=strategy_name,
            )
    if not ok:
        logger.warning("[%s] rifiutato dal risk guardrail: %s", correlation_id, reason,
                        extra={"correlation_id": correlation_id})
        return {"accepted": False, "reason": reason, "idempotency_key": None, "tx_signature": None,
                "correlation_id": correlation_id}

    if chain not in ("solana", "robinhood"):
        return {"accepted": False, "reason": f"unsupported chain: {chain}",
                "idempotency_key": None, "tx_signature": None, "correlation_id": correlation_id}

    if not ledger.reserve(idempotency_key, owner_id, chain, token, strategy_name, side, "live", notional_usd):
        logger.warning("[%s] idempotency_key duplicata: %s", correlation_id, idempotency_key,
                        extra={"correlation_id": correlation_id})
        return {"accepted": False, "reason": "order already in progress (duplicate idempotency key)",
                "idempotency_key": None, "tx_signature": None, "correlation_id": correlation_id}

    try:
        if chain == "solana":
            signed = await execution.build_signed_solana_swap(private_key_hex, quote)
        else:
            signed = await execution.build_signed_robinhood_swap(
                private_key_hex, quote["token_in"], quote["token_out"], quote["fee"],
                quote["amount_in"], quote["amount_out_minimum"],
            )
    except Exception as exc:
        logger.error("[%s] firma fallita: %s", correlation_id, exc, extra={"correlation_id": correlation_id})
        ledger.mark_failed(idempotency_key, f"signing failed: {exc}")
        return {"accepted": False, "reason": f"signing failed: {exc}",
                "idempotency_key": idempotency_key, "tx_signature": None, "correlation_id": correlation_id}

    if not settings.onchain_execution_enabled:
        logger.info("[%s] esecuzione reale disattivata, ordine non inviato", correlation_id,
                     extra={"correlation_id": correlation_id})
        ledger.mark_failed(idempotency_key, "esecuzione reale disattivata (onchain_execution_enabled=False)")
        return {"accepted": False, "reason": "live execution disabled on this server",
                "idempotency_key": idempotency_key, "tx_signature": None, "correlation_id": correlation_id}

    # Signing and quoting take network round-trips: the wallet may have been
    # switched off (or the breaker tripped) meanwhile.
    ok, reason = risk.run_safety_checks(owner_id, chain, token)
    if not ok:
        ledger.mark_failed(idempotency_key, reason)
        return {"accepted": False, "reason": reason, "idempotency_key": idempotency_key, "tx_signature": None,
                "correlation_id": correlation_id}

    expected = {"expected_qty": notional_usd / price_usd if price_usd > 0 else None,
                "expected_price_usd": price_usd if price_usd > 0 else None,
                "price_impact_pct": price_impact_pct}
    tx_id = execution.tx_id(chain, signed)
    if tx_id:
        ledger.mark_signed(idempotency_key, tx_id, **expected)
    try:
        if chain == "solana":
            signature = await _send_solana_with_jito_fallback(correlation_id, private_key_hex, signed, notional_usd)
        else:
            signature = await execution.send_signed_evm_tx(signed)
    except Exception as exc:
        logger.error("[%s] invio fallito: %s", correlation_id, exc, extra={"correlation_id": correlation_id})
        if tx_id and not isinstance(exc, RuntimeError):
            # A timeout or a dropped connection does not prove the node never
            # got it: the reconciler looks the signature up.
            ledger.mark_unknown(idempotency_key, f"send outcome unknown: {exc}")
            return {"accepted": False, "reason": f"send outcome unknown, checking the chain: {exc}",
                    "idempotency_key": idempotency_key, "tx_signature": tx_id, "correlation_id": correlation_id}
        ledger.mark_failed(idempotency_key, f"send failed: {exc}")
        return {"accepted": False, "reason": f"send failed: {exc}",
                "idempotency_key": idempotency_key, "tx_signature": None, "correlation_id": correlation_id}

    # Accepted by the node is not confirmed (audit 29/09, S04): position and
    # spend move when the reconciler sees the transaction confirmed.
    if signature.startswith("jito:") and tx_id:
        signature = tx_id       # a bundle id cannot be looked up; the tx signature can
    ledger.mark_submitted(idempotency_key, signature, **expected)
    logger.info("[%s] inviato tx=%s", correlation_id, signature, extra={"correlation_id": correlation_id})
    return {"accepted": True, "reason": "", "idempotency_key": idempotency_key, "tx_signature": signature,
            "status": "submitted", "correlation_id": correlation_id}
