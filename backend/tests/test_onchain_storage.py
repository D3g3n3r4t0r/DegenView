"""I dati on-chain vivono sul volume del server (backend/data), non dentro
l'immagine (backend/app/data) che si ricrea a ogni deploy."""
from app.trading.onchain import ledger, listings, pilot, radar, storage


def test_every_onchain_store_is_on_the_volume():
    assert storage.DATA_DIR.name == "data" and storage.DATA_DIR.parent.name == "backend"
    for path in (listings._STORE_FILE, radar._STORE_FILE, pilot._STORE_FILE, ledger._DB_FILE):
        assert path.parent == storage.DATA_DIR


def test_old_copy_is_carried_over_once(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "x.json").write_text("{\"a\": 1}")
    monkeypatch.setattr(storage, "_OLD_DIR", old)
    monkeypatch.setattr(storage, "DATA_DIR", new)
    assert storage.data_file("x.json").read_text() == "{\"a\": 1}"
    (new / "x.json").write_text("{}")
    assert storage.data_file("x.json").read_text() == "{}"
