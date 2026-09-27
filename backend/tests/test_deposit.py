"""The Deposit sheet's data (deposit.py)."""
from app.trading.onchain import deposit

EVM = "0x" + "b" * 40
SOL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


def test_every_network_gets_the_right_kind_of_address_and_a_qr():
    res = deposit.options([("solana", SOL, "site"), ("evm", EVM, "site")], robinhood_usdc="0xUSDC")
    nets = {n["id"]: n for n in res["networks"]}
    assert set(nets) == {"solana", "base", "bsc", "robinhood", "ethereum"}
    assert nets["solana"]["address"] == SOL
    assert all(nets[c]["address"] == EVM for c in ("base", "bsc", "robinhood", "ethereum"))
    assert nets["robinhood"]["usdc"] == "0xUSDC"
    assert nets["base"]["qr"].startswith("data:image/png;base64,")


def test_the_site_wallet_wins_over_a_connected_one_and_missing_kinds_say_so():
    res = deposit.options([("evm", "0x" + "c" * 40, "connected"), ("evm", EVM, "site")])
    nets = {n["id"]: n for n in res["networks"]}
    assert nets["base"]["address"] == EVM and nets["base"]["source"] == "site"
    assert nets["solana"]["address"] is None and nets["solana"]["qr"] is None


def test_card_deposits_only_with_a_configured_onramp(monkeypatch):
    assert deposit.options([("solana", SOL, "site")])["onramp"] is None
    monkeypatch.setattr(deposit.settings, "onramp_url", "https://buy.example/?wallet={address}")
    assert deposit.options([("solana", SOL, "site")])["onramp"] == f"https://buy.example/?wallet={SOL}"


def test_exchanges_only_offer_networks_we_read():
    ids = {n[0] for n in deposit.NETWORKS}
    assert all(set(e["networks"]) <= ids for e in deposit.EXCHANGES)
