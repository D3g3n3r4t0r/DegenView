"""The deterministic reader: an analyst's checklist in arithmetic."""
from app.trading.onchain import reader

from tests.test_onchain_research import SOLROUTER

DOCS = ("Solrouter is private AI chat. Use it in the web chat, Claude Code, Cursor or your own app. "
        "npm install @solrouter/sdk then call client.chat(). Each sealed call writes a receipt to Solana. "
        "Latency under 300 ms on the Nosana GPU network.")
HYPE = ("$PEPEX is the next 100x memecoin! Fair launch, LP burned, renounced. Community-driven degen army, "
        "to the moon, don't miss out!")
BUZZ = ("Nova is a revolutionary next-gen web3 ecosystem that empowers users with cutting-edge AI. Our "
        "innovative platform seamlessly unlocks the future of finance. Roadmap: Q4 2026.")


def _read(desc, site=(), **kw):
    r = reader.read(desc, list(site), **kw)
    r.pop("sketch")
    return r


def test_real_project_reads_as_a_gem():
    r = _read(SOLROUTER, [DOCS], name="Solrouter")
    assert r["verdict"] == "gem" and r["stage"] == "live" and r["original"]
    assert "fees" in r["evidence"]["utility"] and not r["red_flags"]


def test_hype_and_buzzwords_are_thin():
    for text in (HYPE, BUZZ):
        r = _read(text)
        assert r["verdict"] == "thin" and r["points"] < 20 and r["red_flags"]


def test_profit_promises_are_a_scam():
    r = _read("Stake $YLD and earn guaranteed returns of 3% daily. Risk-free, presale is live.")
    assert r["verdict"] == "scam" and "promises returns" in r["red_flags"][0]


def test_copied_text_is_not_original():
    corpus = {"solana:A": reader.sketch(SOLROUTER)}
    r = _read(SOLROUTER.replace("Solrouter", "Privroute"), corpus=corpus, key="solana:B")
    assert not r["original"] and r["verdict"] == "thin" and r["evidence"]["twin"] == "solana:A"
    assert reader.similarity(reader.sketch(SOLROUTER), reader.sketch(HYPE)) < 0.1


def test_a_site_about_something_else_is_not_read():
    """A launchpad's token page: rich text, none of it about the project."""
    r = _read("Pixel frogs that jump across the chain for fun and friendship forever.", [DOCS])
    assert r["verdict"] == "thin" and any("not read" in f for f in r["red_flags"])
    r = _read(SOLROUTER, [DOCS], name="Frogcoin", symbol="FROG")
    assert "site never names the project: not read" in r["red_flags"]


def test_stage_needs_evidence():
    assert reader.stage("We are building it. Roadmap: testnet in Q3 2026 and more words " * 3)[0] == "testnet"
    assert reader.stage("Now live on mainnet, used by 4000 traders, get started in the app. " * 3)[0] == "live"
    assert reader.stage("short")[0] == "unclear"


def test_token_role_is_read_near_the_token():
    assert reader.token_utility("$ROUTER is the token used to pay for inference and staked by nodes") == \
        ["fees", "staking"]
    assert reader.token_utility("The token. " + "filler " * 30 + "fees are low") == []
