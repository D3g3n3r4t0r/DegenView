"""The deploy notice: a "Solo-account: whitekobra" commit sends no Telegram
at all (Lorenzo, 17/10), the rest goes to the repository's chat."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

from app import main
from app.notify import weekly_recap

_KOBRA = "Fix the gems page\n\nAggiornamento: pagina gemme sistemata\nSolo-account: whitekobra\n"
_ALL = "Fix the chart\n\nAggiornamento: grafico sistemato\n"


def _run(monkeypatch, tmp_path, messages):
    commits = [{"sha": f"{i:07d}abc", "commit": {"message": m}} for i, m in enumerate(messages)]
    commits.append({"sha": "old0000", "commit": {"message": "old"}})

    class _Client:
        async def get(self, *a, **kw):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: commits)

    @contextlib.asynccontextmanager
    async def pooled(**kw):
        yield _Client()
    monkeypatch.setattr(main.http_client, "pooled", pooled)
    monkeypatch.setattr(main.settings, "telegram_bot_token", "t")
    monkeypatch.setattr(main.settings, "github_api_token", "g")
    monkeypatch.setattr(main, "_LAST_SHA_FILE", tmp_path / "sha.txt")
    (tmp_path / "sha.txt").write_text("old0000", encoding="utf-8")
    sent = []

    async def send_message(text):
        sent.append(text)
    monkeypatch.setattr(main.telegram, "send_message", send_message)
    asyncio.run(main._notify_deploy())
    return sent


def test_a_whitekobra_only_change_is_left_out_of_the_deploy_notice(monkeypatch, tmp_path):
    sent = _run(monkeypatch, tmp_path, [_KOBRA, _ALL])
    assert len(sent) == 1 and "grafico sistemato" in sent[0] and "pagina gemme" not in sent[0]


def test_a_deploy_of_whitekobra_only_changes_sends_nothing(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [_KOBRA]) == []


def test_the_weekly_recap_leaves_private_changes_out():
    assert weekly_recap.private_account(_KOBRA) == "whitekobra" and weekly_recap.private_account(_ALL) == ""
    text = weekly_recap.build_recap([_KOBRA, _ALL], now=1_790_000_000, resolutions_path=None)
    assert "Modifiche al codice: 1" in text and "pagina gemme" not in text


def test_deploy_notice_has_figures_details_and_renders_png_card(monkeypatch, tmp_path):
    sent_photos = []

    async def send_photo(photo_bytes, caption=""):
        sent_photos.append((photo_bytes, caption))
        return True

    monkeypatch.setattr(main.telegram, "send_photo", send_photo)
    commit_msg = (
        "Harden auth and enrich deploy notices (seed-0389)\n\n"
        "- Fix X-Forwarded-For rate-limit IP extraction\n"
        "- Add CSRF Sec-Fetch-Site protection\n\n"
        "Aggiornamento: risolte le vulnerabilità di sicurezza e arricchiti i messaggi di deploy su Telegram\n"
    )
    sent = _run(monkeypatch, tmp_path, [commit_msg])
    assert len(sent) == 1
    msg = sent[0]
    assert "Figura 1 · Mappa d'Impatto dei Moduli" in msg
    assert "Figura 2 · Pipeline" in msg
    assert "risolte le vulnerabilità di sicurezza" in msg
    assert "Fix X-Forwarded-For rate-limit IP extraction" in msg
    assert len(sent_photos) == 1
    assert sent_photos[0][0].startswith(b"\x89PNG\r\n\x1a\n")
    assert len(sent_photos[0][0]) > 1000


def test_security_hardening_invariants(tmp_path):
    from pathlib import Path
    from starlette.requests import Request
    from fastapi.testclient import TestClient
    from app import guest, main, web_common
    from app.pine import storage as pine_storage

    # 1. Rightmost X-Forwarded-For IP (Caddy appends real client IP at the end)
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 8.8.8.8")],
        "client": ("172.18.0.2", 12345),
    }
    assert web_common._client_ip(Request(scope)) == "8.8.8.8"

    # 2. On-chain phone approval endpoints are in _PUBLIC_PATHS
    for p in (
        "/api/onchain/reveal/approve",
        "/api/onchain/reveal/passkey/options",
        "/api/onchain/reveal/passkey/verify",
    ):
        assert p in main._PUBLIC_PATHS

    # 3. Cross-site POST requests are blocked by CSRF Sec-Fetch-Site check
    with TestClient(main.app) as c:
        r = c.post("/api/watchlist", headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403
        assert "Cross-site" in r.json()["detail"]

    # 4. PineScript storage rejects path traversal script_ids
    assert pine_storage.load_script("../../users") is None
    assert pine_storage.delete_script("../users") is False

    # 5. Guest mode blocks /api/export, /api/agent/log, /api/agent/calls, /api/perf
    for blocked in ("/api/export/positions.csv", "/api/agent/log", "/api/agent/calls", "/api/perf"):
        assert guest.allows("GET", blocked) is False

    # 6. Passkey setup HTML no longer injects pk.label into innerHTML
    html_src = (
        Path(main.__file__).resolve().parent.parent.parent / "frontend" / "onchain-passkey-setup.html"
    ).read_text(encoding="utf-8")
    assert "li.innerHTML" not in html_src


def test_layer_clusters_kaspa_and_injective(tmp_path, monkeypatch):
    import httpx
    from app.trading.onchain import layer_clusters, storage, sync_sells, wallet_clusters

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    assert wallet_clusters.request("layer", "kas-kaspa", "KAS") is True
    assert wallet_clusters.request("layer", "inj-injective-protocol", "INJ") is True
    assert wallet_clusters.token_status("layer", "kas-kaspa")["queued"] is True

    # Mock Kaspa REST API + Injective Cosmos LCD
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "api.kaspa.org/info/coinsupply" in u:
            return httpx.Response(200, json={"circulatingSupply": str(25_000_000_000 * 10**8)})
        if "api.kaspa.org/info/virtual-chain-blue-score" in u:
            return httpx.Response(200, json={"blueScore": 90000})
        if "api.kaspa.org/blocks-from-bluescore" in u:
            return httpx.Response(200, json=[{
                "transactions": [{
                    "transaction_id": "ktx1",
                    "block_time": 1729680000000,
                    "accepting_block_blue_score": 89990,
                    "inputs": [{"previous_outpoint_address": "kaspa:qpsender000000000000000000000000000000000000000000000001"}],
                    "outputs": [
                        {"script_public_key_address": "kaspa:qpholder000000000000000000000000000000000000000000000001", "amount": 500_000_000 * 10**8},
                        {"script_public_key_address": "kaspa:qpholder000000000000000000000000000000000000000000000002", "amount": 400_000_000 * 10**8},
                    ],
                }]
            }])
        if "api.kaspa.org/addresses/balances" in u:
            return httpx.Response(200, json=[
                {"address": "kaspa:qpholder000000000000000000000000000000000000000000000001", "balance": 500_000_000 * 10**8},
                {"address": "kaspa:qpholder000000000000000000000000000000000000000000000002", "balance": 400_000_000 * 10**8},
            ])
        if "api.kaspa.org/addresses/" in u:
            return httpx.Response(200, json=[{
                "transaction_id": "ktx2",
                "block_time": 1729680010000,
                "accepting_block_blue_score": 89995,
                "inputs": [{"previous_outpoint_address": "kaspa:qpholder000000000000000000000000000000000000000000000001"}],
                "outputs": [{"script_public_key_address": "kaspa:qpholder000000000000000000000000000000000000000000000002", "amount": 50_000_000 * 10**8}],
            }])
        if "cosmos/bank/v1beta1/supply/by_denom" in u:
            return httpx.Response(200, json={"amount": {"denom": "inj", "amount": str(100_000_000 * 10**18)}})
        if "cosmos/tx/v1beta1/txs" in u:
            txs = []
            for i in range(12):
                txs.append({
                    "txhash": f"injtx{i}",
                    "height": str(50000 + i),
                    "timestamp": "2026-10-23T12:00:00Z",
                    "events": [{
                        "type": "transfer",
                        "attributes": [
                            {"key": "sender", "value": "inj1feeder00000000000000000000000000000000"},
                            {"key": "recipient", "value": f"inj1whale00000000000000000000000000000000{i % 3}"},
                            {"key": "amount", "value": f"{1_000_000 * 10**18}inj"},
                        ],
                    }],
                })
            return httpx.Response(200, json={"tx_responses": txs})
        if "explorer.custom.org/api/v2/tokens/" in u and "/transfers" in u:
            return httpx.Response(200, json={"items": [
                {"block_number": 100, "tx_hash": "0xtx1", "log_index": 0, "from": {"hash": "0x" + "a" * 40}, "to": {"hash": "0x" + "b" * 40}, "total": {"value": "500000"}},
                {"block_number": 101, "tx_hash": "0xtx2", "log_index": 0, "from": {"hash": "0x" + "a" * 40}, "to": {"hash": "0x" + "c" * 40}, "total": {"value": "400000"}},
            ]})
        if "explorer.custom.org/api/v2/tokens/" in u:
            return httpx.Response(200, json={"total_supply": "1000000", "items": []})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        res_kas = asyncio.run(layer_clusters.build("kas-kaspa", "KAS", client=client))
        assert res_kas["chain"] == "layer" and res_kas["token"] == "kas-kaspa"
        assert len(res_kas["clusters"]) >= 1
        assert sync_sells.report_path("layer", "kas-kaspa").exists()

        res_inj = asyncio.run(layer_clusters.build("inj-injective-protocol", "INJ", client=client))
        assert res_inj["chain"] == "layer" and res_inj["token"] == "inj-injective-protocol"
        assert len(res_inj["clusters"]) >= 1
        assert sync_sells.report_path("layer", "inj-injective-protocol").exists()

        tok = "0x" + "1" * 40
        res_url = asyncio.run(layer_clusters.build_from_url(
            f"https://explorer.custom.org/token/{tok}", out_chain="custom", token=tok, symbol="CST", client=client,
        ))
        assert res_url["chain"] == "custom" and len(res_url["clusters"]) >= 1
        assert sync_sells.report_path("custom", tok).exists()
    finally:
        asyncio.run(client.aclose())


