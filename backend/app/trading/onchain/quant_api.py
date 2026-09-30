"""Authenticated, read-only local evidence. No model, research job or order call."""
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from app.trading.onchain import quant_memory, quant_runtime, alert_track

logger = logging.getLogger(__name__)


def router(authenticate):
    api = APIRouter(prefix="/api/agent/quant", dependencies=[Depends(authenticate)])

    @api.get("")
    def overview():
        try:
            result = quant_memory.status()
        except Exception:
            logger.exception("quant evidence read unavailable")
            raise HTTPException(503, "Quantitative evidence unavailable") from None
        approval = quant_runtime.approved()
        result["approval"] = ({"mode": approval["mode"], "report_hash": approval["report_hash"],
                               "active_from": approval["active_from"], "stages": approval["policy"].stages,
                               "strategy": approval["policy"].strategy} if approval else None)
        result["at"] = time.time()
        return result

    @api.get("/project")
    def project(chain: str = Query(min_length=1, max_length=40), token: str = Query(min_length=1, max_length=200)):
        key = quant_memory.project_key({"chain": chain, "token": token})
        try:
            with quant_memory.connect() as db:
                windows = [json.loads(row[0]) for row in db.execute(
                    "SELECT payload FROM quant_windows WHERE project=? ORDER BY horizon", (key,))]
                candle_count = db.execute("SELECT count(*) FROM quant_candles WHERE project=?", (key,)).fetchone()[0]
        except Exception:
            logger.exception("quant project read unavailable")
            raise HTTPException(503, "Project evidence unavailable") from None
        if not windows:
            raise HTTPException(404, "No observations recorded for this project")
        alerts = [a for a in list(alert_track._alerts.values()) if quant_memory.project_key(a) == key]
        latest = max(alerts, key=lambda a: a.get("at", 0), default={})
        signal = latest.get("quant_system") or {}
        return {"chain": chain, "token": token, "windows": windows, "candles": candle_count,
                "status": latest.get("quant_status", "not evaluated"),
                "signal": {k: signal.get(k) for k in ("state", "reason", "eligible", "in_at", "evaluated_at", "report_hash", "policy_id")}}

    @api.get("/reports/{report_id}")
    def report(report_id: str):
        if len(report_id) != 64 or any(c not in "0123456789abcdef" for c in report_id):
            raise HTTPException(404, "Report not found")
        try:
            result = quant_memory.report_by_id(report_id)
        except Exception:
            logger.exception("quant report read unavailable")
            raise HTTPException(503, "Report unavailable") from None
        if result is None:
            raise HTTPException(404, "Report not found")
        return result

    return api
