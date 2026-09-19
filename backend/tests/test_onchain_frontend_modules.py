"""La pagina del wallet carica moduli ES veri attraverso un import map
generato dal server. Il modo in cui puo' rompersi e' silenzioso: un modulo
rinominato, o un import con un nome che nella mappa non c'e', danno un 404
a runtime che nessun test del backend vedrebbe — la pagina si apre bianca.

Questi test chiudono proprio quel buco, dal lato che possiamo controllare
senza un browser: che la mappa copra ogni import scritto nei moduli, e che
ogni voce della mappa punti a un file che esiste davvero.
"""

from __future__ import annotations

import json
import re

from app import main

_IMPORTMAP_RE = re.compile(r'<script type="importmap">(.*?)</script>', re.S)
_IMPORT_RE = re.compile(r"""from\s+["'](@onchain/[^"']+)["']""")


def _importmap() -> dict[str, str]:
    match = _IMPORTMAP_RE.search(main._ONCHAIN_APP_HTML)
    assert match, "l'import map non e' stata iniettata nella pagina"
    return json.loads(match.group(1))["imports"]


def test_page_ships_an_importmap_for_every_module_on_disk():
    imports = _importmap()
    on_disk = {f"@onchain/{m.name}" for m in main._onchain_modules()}
    assert on_disk, "nessun modulo trovato in static/onchain/"
    assert set(imports) == on_disk


def test_every_import_written_in_a_module_is_in_the_map():
    imports = _importmap()
    for module in main._onchain_modules():
        for specifier in _IMPORT_RE.findall(module.read_text(encoding="utf-8")):
            assert specifier in imports, f"{module.name} importa {specifier}, che l'import map non risolve"


def test_mapped_urls_point_at_files_that_exist_and_carry_the_version():
    for specifier, url in _importmap().items():
        path, _, query = url.partition("?")
        assert query == f"v={main._ASSET_VERSION}", f"{specifier} senza cache-busting"
        served = main.FRONTEND_DIR / path.removeprefix("/")
        assert served.is_file(), f"{specifier} punta a {path}, che non esiste"


def test_entry_point_script_is_versioned_too():
    # L'import map versiona gli import interni, ma il <script type="module">
    # iniziale ha un URL suo: se resta senza ?v= il browser puo' servire da
    # cache il vecchio entry point e ignorare tutto il resto.
    assert f'src="/static/onchain/main.js?v={main._ASSET_VERSION}"' in main._ONCHAIN_APP_HTML


def test_asset_version_changes_when_a_module_changes(tmp_path, monkeypatch):
    before = main._compute_asset_version()
    real_dir = main.FRONTEND_DIR / "static" / "onchain"
    target = real_dir / "format.js"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n// tocco per il test\n")
        assert main._compute_asset_version() != before
    finally:
        target.write_bytes(original)
    assert main._compute_asset_version() == before
