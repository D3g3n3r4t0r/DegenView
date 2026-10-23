"""Copy trading of Solana wallets, for the classic site's Trading tab.

The engine is app/trading/onchain/copytrade.py; these routes only read and
change one account's settings. Simulated copying is open to every account;
real money needs the account's own consent (/real) and the server's
settings.onchain_execution_enabled, checked again on every order.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import auth
from app import jobs as jobs_store
from app import guest as guest_links
from app.config import settings
from app.models import User
from app.trading.onchain import copytrade, copytrade_evm, wallet_pnl

router = APIRouter()


def _member(user: User = Depends(auth.get_current_user)) -> User:
    if guest_links.is_guest(user):
        raise HTTPException(status_code=403, detail="Not available on a guest link.")
    return user


class FollowRequest(BaseModel):
    address: str = Field(min_length=32, max_length=44)
    label: str | None = Field(default=None, max_length=40)
    mode: Literal["off", "sim", "real"] | None = None
    copy_: Literal["entry", "both"] | None = Field(default=None, alias="copy")
    sizing: Literal["pct", "fixed"] | None = None
    pct: float | None = None
    fixed_usd: float | None = None
    max_chase_pct: float | None = None
    slippage_pct: float | None = None
    chains: list[str] | None = None          # EVM wallets only: the networks to copy on


class LimitsRequest(BaseModel):
    max_trade_usd: float | None = None
    max_day_usd: float | None = None
    max_open: int | None = None


class RealRequest(BaseModel):
    accept: bool


class AnalyzeRequest(BaseModel):
    address: str = Field(min_length=32, max_length=44)
    fresh: bool = False


class CloseRequest(BaseModel):
    leader: str
    mint: str


@router.get("/api/copytrade")
async def copytrade_state(user: User = Depends(_member)) -> dict:
    acc = copytrade.account(user.id)
    w = (user.onchain_wallets or {}).get("solana")
    sol = None
    if w:
        try:
            sol = await copytrade.sol_balance(w.address)
        except RuntimeError:
            pass
    return {
        "follows": list(acc["follows"].values()),
        "positions": [p | {"leader": leader} for leader, ps in acc["positions"].items() for p in ps.values()],
        "trades": acc["trades"][:100],
        "limits": acc["limits"],
        "spent_today": round(copytrade.spent_today(acc), 2),
        "real_ok": bool(acc["real_ok_at"]),
        "stats": copytrade.stats(acc),
        "wallet": {"address": w.address if w else None, "sol": sol, "enabled": bool(w and w.enabled)},
        "server": {"real_enabled": settings.onchain_execution_enabled, **copytrade.status},
        "evm": await _evm_state(user),
    }


async def _evm_state(user: User) -> dict:
    """The EVM wallet is the account's Robinhood wallet: an EVM key is the same
    address on every EVM network (Lorenzo's choice, 23/10)."""
    w = (user.onchain_wallets or {}).get("robinhood")
    balances = await copytrade_evm.native_balances(w.address) if w else {}
    return {
        "address": w.address if w else None,
        "chains": [{"id": c, "label": cfg["label"], "native": cfg["native"], "copy": copytrade_evm.copyable(c),
                    "dex": cfg["dex"], "tx": cfg["tx"], "balance": balances.get(c),
                    **{k: v for k, v in copytrade_evm.status[c].items() if k in ("state", "error")}}
                   for c, cfg in copytrade_evm.CHAINS.items()],
        "real": False,
    }


@router.post("/api/copytrade/follow")
async def copytrade_follow(body: FollowRequest, user: User = Depends(_member)) -> dict:
    fields = body.model_dump(exclude={"address", "copy_"})
    fields["copy"] = body.copy_
    try:
        return copytrade.set_follow(user.id, body.address.strip(), fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/copytrade/follow/{address}")
async def copytrade_unfollow(address: str, user: User = Depends(_member)) -> dict:
    copytrade.remove_follow(user.id, address)
    return {"ok": True}


@router.post("/api/copytrade/limits")
async def copytrade_limits(body: LimitsRequest, user: User = Depends(_member)) -> dict:
    try:
        return copytrade.set_limits(user.id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/copytrade/real")
async def copytrade_real(body: RealRequest, user: User = Depends(_member)) -> dict:
    copytrade.set_real_ok(user.id, body.accept)
    return {"real_ok": body.accept}


@router.post("/api/copytrade/close")
async def copytrade_close(body: CloseRequest, user: User = Depends(_member)) -> dict:
    try:
        return await copytrade.close_position(user.id, body.leader, body.mint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/copytrade/analyze")
async def copytrade_analyze(body: AnalyzeRequest, user: User = Depends(_member)) -> dict:
    """A wallet's profitability over 24 h / 7 / 30 days (wallet_pnl.py): a
    job, since a busy wallet means thousands of transactions to read. A
    result younger than 15 minutes comes back at once."""
    address = body.address.strip()
    if copytrade_evm.is_evm(address):
        raise HTTPException(status_code=400, detail="The profitability analysis reads Solana wallets only for now.")
    if not copytrade.valid_address(address):
        raise HTTPException(status_code=400, detail="Not a Solana wallet address.")
    hit = None if body.fresh else wallet_pnl.cached(address)
    if hit:
        return {"result": hit}
    jid = jobs_store.create(user.id, "wallet_pnl", f"Profitability {address[:4]}…{address[-4:]}", page="/")
    jobs_store.run(jid, lambda: wallet_pnl.analyze(address, lambda m: jobs_store.log(jid, m)))
    return {"job": jid}
