from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from app import issues
try:
    from app.trading.onchain import auto_chain_pr, storage
except ImportError:
    import sys
    import types

    _pkg = types.ModuleType("app.trading")
    _pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "app" / "trading")]
    sys.modules["app.trading"] = _pkg
    from app.trading.onchain import auto_chain_pr, storage


@contextmanager
def _isolated_env():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        vol_dir = tmp_path / "volume"
        repo_dir = tmp_path / "repo"
        vol_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        repo_discovered = repo_dir / "discovered_chains.json"
        repo_discovered.write_text(
            json.dumps(
                {
                    "_README": "Auto-discovered chain and explorer configurations for cluster scanning.",
                    "chains": {
                        "shipped-chain": {
                            "slug": "shipped-chain",
                            "chain": "layer",
                            "token": "shipped-chain",
                            "symbol": "SHIP",
                            "adapter": "blockscout_v2",
                            "endpoints": ["https://scan.shipped.io/api/v2/addresses"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        issues_file = vol_dir / "issues.json"
        old_issues = list(issues._issues)
        issues._issues.clear()
        try:
            with (
                patch.object(storage, "DATA_DIR", vol_dir),
                patch.object(storage, "_OLD_DIR", repo_dir),
                patch.object(auto_chain_pr, "_REPO_CHAINS_FILE", repo_discovered),
                patch.object(issues, "_STORE_FILE", issues_file),
            ):
                yield
        finally:
            issues._issues.clear()
            issues._issues.extend(old_issues)


def test_load_and_save_discovered_chains():
    with _isolated_env():
        loaded = auto_chain_pr.load_discovered_chains()
        assert "shipped-chain" in loaded
        assert loaded["shipped-chain"]["symbol"] == "SHIP"

        saved = auto_chain_pr.save_discovered_chain(
            "new-chain",
            {
                "chain": "layer",
                "token": "new-chain",
                "symbol": "NEW",
                "adapter": "cosmos_lcd",
                "endpoints": ["https://api.new.net"],
            },
        )
        assert saved["slug"] == "new-chain"

        merged = auto_chain_pr.load_discovered_chains()
        assert "shipped-chain" in merged
        assert "new-chain" in merged
        assert merged["new-chain"]["symbol"] == "NEW"


def test_probe_unknown_chain_cosmos_and_nextjs():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://chains.cosmos.directory/cheqd":
            return httpx.Response(
                200,
                json={
                    "chain": {
                        "chain_name": "cheqd",
                        "symbol": "CHEQ",
                        "apis": {
                            "rest": [{"address": "https://api.cheqd.net"}],
                            "rpc": [{"address": "https://rpc.cheqd.net"}],
                        },
                    }
                },
            )
        if url.startswith("https://rest.cosmos.directory/cheqd/cosmos/staking/v1beta1/validators"):
            return httpx.Response(200, json={"validators": [{"operator_address": "cheqdvaloper1abc"}]})
        if url == "https://explorer.cheqd.io/accounts":
            html = (
                '<html><head><script id="__NEXT_DATA__" type="application/json">'
                '{"props":{"pageProps":{"graphqlUrl":"https://graphql.cheqd.io/v1/graphql",'
                '"rpcUrl":"https://rpc.cheqd.io"}}}'
                "</script></head><body>Accounts</body></html>"
            )
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, json={"error": "not found"})

    async def _run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            spec = await auto_chain_pr.probe_unknown_chain(
                chain="layer",
                token="cheqd",
                url="https://explorer.cheqd.io/accounts",
                error="unsupported explorer",
                client=client,
            )
            assert spec["slug"] == "cheqd"
            assert spec["symbol"] == "CHEQ"
            assert spec["origin"] == "https://explorer.cheqd.io"
            assert spec["adapter"] == "cosmos_lcd"
            assert "https://chains.cosmos.directory/cheqd" in spec["endpoints"]
            assert "https://api.cheqd.net" in spec["endpoints"]
            assert "https://graphql.cheqd.io/v1/graphql" in spec["endpoints"]

            persisted = auto_chain_pr.load_discovered_chains()
            assert "cheqd" in persisted
            assert persisted["cheqd"]["adapter"] == "cosmos_lcd"

    with _isolated_env():
        asyncio.run(_run())


def test_probe_unknown_chain_blockscout_v2():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://scan.octa.space/api/v2/addresses":
            return httpx.Response(200, json={"items": [{"hash": "0x1234", "coin_balance": "1000"}]})
        if url == "https://scan.octa.space/api/v2/stats":
            return httpx.Response(200, json={"total_addresses": "50000", "total_blocks": "1200000"})
        return httpx.Response(404)

    async def _run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            spec = await auto_chain_pr.probe_unknown_chain(
                chain="layer",
                token="octa-octaspace",
                url="https://scan.octa.space",
                client=client,
            )
            assert spec["slug"] == "octa-octaspace"
            assert spec["symbol"] == "OCTA"
            assert spec["adapter"] == "blockscout_v2"
            assert "https://scan.octa.space/api/v2/addresses" in spec["endpoints"]
            assert "https://scan.octa.space/api/v2/stats" in spec["endpoints"]

    with _isolated_env():
        asyncio.run(_run())


def test_ensure_auto_pr_opens_github_pr_and_registers_issue():
    put_calls: list[dict] = []
    pr_calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method.upper()

        if url == "https://chains.cosmos.directory/cheqd":
            return httpx.Response(200, json={"chain": {"chain_name": "cheqd", "symbol": "CHEQ"}})
        if url.startswith("https://rest.cosmos.directory/cheqd/cosmos/staking/v1beta1/validators"):
            return httpx.Response(200, json={"validators": []})

        if method == "GET" and url == "https://api.github.com/repos/D3g3n3r4t0r/DegenView/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "abc1234567890mainsha"}})
        if method == "POST" and url == "https://api.github.com/repos/D3g3n3r4t0r/DegenView/git/refs":
            return httpx.Response(201, json={"ref": "refs/heads/auto/chain-support-cheqd"})
        if (
            method == "GET"
            and url.startswith(
                "https://api.github.com/repos/D3g3n3r4t0r/DegenView/contents/backend/app/data/discovered_chains.json"
            )
        ):
            initial_b64 = base64.b64encode(b'{"_README": "init", "chains": {}}').decode("ascii")
            return httpx.Response(200, json={"sha": "file_sha_001", "content": initial_b64})
        if (
            method == "PUT"
            and url == "https://api.github.com/repos/D3g3n3r4t0r/DegenView/contents/backend/app/data/discovered_chains.json"
        ):
            body = json.loads(request.content.decode("utf-8"))
            put_calls.append(body)
            return httpx.Response(200, json={"commit": {"sha": "new_commit_sha"}})
        if method == "POST" and url == "https://api.github.com/repos/D3g3n3r4t0r/DegenView/pulls":
            body = json.loads(request.content.decode("utf-8"))
            pr_calls.append(body)
            return httpx.Response(
                201,
                json={
                    "number": 42,
                    "html_url": "https://github.com/D3g3n3r4t0r/DegenView/pull/42",
                },
            )
        return httpx.Response(404)

    async def _run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            pr_rec = await auto_chain_pr.ensure_auto_pr(
                chain="layer",
                token="cheqd",
                url="https://explorer.cheqd.io/accounts",
                error="no public transfer source answered",
                client=client,
            )
            assert pr_rec["slug"] == "cheqd"
            assert pr_rec["symbol"] == "CHEQ"
            assert pr_rec["branch"] == "auto/chain-support-cheqd"
            assert pr_rec["status"] == "opened"
            assert pr_rec["pr_number"] == 42
            assert pr_rec["pr_url"] == "https://github.com/D3g3n3r4t0r/DegenView/pull/42"
            assert len(put_calls) == 1
            assert len(pr_calls) == 1
            assert pr_calls[0]["title"] == "Auto-add cluster support for CHEQ (explorer.cheqd.io)"

            pr_rec_2 = await auto_chain_pr.ensure_auto_pr(
                chain="layer",
                token="cheqd",
                url="https://explorer.cheqd.io/accounts",
                client=client,
            )
            assert pr_rec_2["pr_number"] == 42
            assert len(pr_calls) == 1

            all_prs = auto_chain_pr.list_auto_prs()
            assert len(all_prs) == 1
            assert auto_chain_pr.get_auto_pr("layer", "cheqd") is not None

            matching_issues = [
                it
                for it in issues.list_issues()
                if it.get("title") == "Auto-PR supporto cluster per CHEQ (explorer.cheqd.io)"
            ]
            assert len(matching_issues) == 1

    with (
        _isolated_env(),
        patch.dict(os.environ, {"GITHUB_API_TOKEN": "ghp_test_token_123", "GITHUB_REPO": "D3g3n3r4t0r/DegenView"}),
    ):
        asyncio.run(_run())


def test_ensure_auto_pr_queued_without_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://astar.api.subscan.io/api/scan/metadata":
            return httpx.Response(200, json={"code": 0, "data": {"blockNum": "1000"}})
        return httpx.Response(404)

    async def _run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            pr_rec = await auto_chain_pr.ensure_auto_pr(
                chain="layer",
                token="astar",
                url="https://astar.subscan.io",
                error="unsupported subscan chain",
                client=client,
            )
            assert pr_rec["slug"] == "astar"
            assert pr_rec["symbol"] == "ASTR"
            assert pr_rec["adapter"] == "subscan"
            assert pr_rec["status"] == "queued"
            assert pr_rec["pr_number"] is None
            assert "compare/main...auto/chain-support-astar" in pr_rec["pr_url"]

    env_copy = {k: v for k, v in os.environ.items() if k != "GITHUB_API_TOKEN"}
    with _isolated_env(), patch.dict(os.environ, env_copy, clear=True):
        asyncio.run(_run())


class AutoChainPrTests(unittest.TestCase):
    def test_all(self):
        test_load_and_save_discovered_chains()
        test_probe_unknown_chain_cosmos_and_nextjs()
        test_probe_unknown_chain_blockscout_v2()
        test_ensure_auto_pr_opens_github_pr_and_registers_issue()
        test_ensure_auto_pr_queued_without_token()


if __name__ == "__main__":
    unittest.main()
