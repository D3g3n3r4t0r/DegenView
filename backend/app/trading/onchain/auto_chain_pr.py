"""Automatic self-healing chain discovery and GitHub Pull Request generator.

When cluster scanning encounters an unsupported or newly added chain/explorer,
this module:
1. Probes the chain/explorer in parallel across Blockscout v2, Blockscout/Etherscan v1,
   Cosmos Directory + Cosmos LCD, Subscan, and Next.js `__NEXT_DATA__` / JS bundles.
2. Persists the discovered adapter specification into `discovered_chains.json`
   (merging repo-shipped and runtime volume configurations).
3. Automatically opens a GitHub Pull Request on `GITHUB_REPO` (when `GITHUB_API_TOKEN`
   is configured) or queues a compare-URL PR record in `auto_chain_prs.json`, and
   registers a corresponding Bacheca / `/cantiere` issue via `app.issues.add_issue`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app import issues
from app.atomic_write import write_text_atomic
from app.trading.onchain import storage

logger = logging.getLogger(__name__)

_README_TEXT = "Auto-discovered chain and explorer configurations for cluster scanning."
_REPO_CHAINS_FILE = Path(__file__).resolve().parents[2] / "data" / "discovered_chains.json"

_KNOWN_SLUG_ALIASES: dict[str, tuple[str, str]] = {
    "octa": ("octa-octaspace", "OCTA"),
    "octaspace": ("octa-octaspace", "OCTA"),
    "octa-octaspace": ("octa-octaspace", "OCTA"),
    "scan.octa.space": ("octa-octaspace", "OCTA"),
    "cheqd": ("cheqd", "CHEQ"),
    "cheq": ("cheqd", "CHEQ"),
    "cheq-cheqd-network": ("cheqd", "CHEQ"),
    "explorer.cheqd.io": ("cheqd", "CHEQ"),
    "kas": ("kas-kaspa", "KAS"),
    "kaspa": ("kas-kaspa", "KAS"),
    "kas-kaspa": ("kas-kaspa", "KAS"),
    "inj": ("inj-injective-protocol", "INJ"),
    "injective": ("inj-injective-protocol", "INJ"),
    "tia": ("tia-celestia", "TIA"),
    "celestia": ("tia-celestia", "TIA"),
    "sei": ("sei-sei", "SEI"),
    "atom": ("atom-cosmos", "ATOM"),
    "cosmos": ("atom-cosmos", "ATOM"),
    "osmo": ("osmo-osmosis", "OSMO"),
    "osmosis": ("osmo-osmosis", "OSMO"),
    "akt": ("akt-akash-network", "AKT"),
    "akash": ("akt-akash-network", "AKT"),
    "axl": ("axl-axelar", "AXL"),
    "axelar": ("axl-axelar", "AXL"),
    "dym": ("dym-dymension", "DYM"),
    "dymension": ("dym-dymension", "DYM"),
    "saga": ("saga-saga", "SAGA"),
    "kava": ("kava-kava", "KAVA"),
    "astar": ("astar", "ASTR"),
    "polkadot": ("polkadot", "DOT"),
    "kusama": ("kusama", "KSM"),
    "moonbeam": ("moonbeam", "GLMR"),
    "acala": ("acala", "ACA"),
    "bittensor": ("bittensor", "TAO"),
    "aleph-zero": ("aleph-zero", "AZERO"),
    "azero": ("aleph-zero", "AZERO"),
}

_KNOWN_SYMBOLS: dict[str, str] = {
    "cheqd": "CHEQ",
    "octa-octaspace": "OCTA",
    "octa": "OCTA",
    "octaspace": "OCTA",
    "kas-kaspa": "KAS",
    "kaspa": "KAS",
    "inj-injective-protocol": "INJ",
    "injective": "INJ",
    "tia-celestia": "TIA",
    "celestia": "TIA",
    "sei-sei": "SEI",
    "sei": "SEI",
    "atom-cosmos": "ATOM",
    "cosmos": "ATOM",
    "osmo-osmosis": "OSMO",
    "osmosis": "OSMO",
    "akt-akash-network": "AKT",
    "akash": "AKT",
    "axl-axelar": "AXL",
    "axelar": "AXL",
    "dym-dymension": "DYM",
    "dymension": "DYM",
    "saga-saga": "SAGA",
    "saga": "SAGA",
    "kava-kava": "KAVA",
    "kava": "KAVA",
    "astar": "ASTR",
    "polkadot": "DOT",
    "kusama": "KSM",
    "moonbeam": "GLMR",
    "acala": "ACA",
    "bittensor": "TAO",
    "aleph-zero": "AZERO",
}

_HOST_NOISE_PARTS = {
    "www",
    "explorer",
    "scan",
    "blockscout",
    "blocks",
    "mainnet",
    "testnet",
    "evm",
    "app",
    "api",
    "rpc",
    "lcd",
    "rest",
    "subscan",
    "statescan",
    "mintscan",
    "ping",
    "celatone",
    "io",
    "org",
    "com",
    "net",
    "network",
    "xyz",
    "space",
    "foundation",
    "tech",
    "finance",
    "dev",
    "ai",
    "co",
    "cc",
    "zone",
    "chain",
    "link",
    "cloud",
    "one",
    "world",
    "global",
    "pro",
    "me",
    "gg",
    "sh",
    "fi",
    "build",
    "info",
    "pub",
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_JS_SRC_RE = re.compile(
    r'<script[^>]+src=["\']([^"\']+?\.js(?:\?[^"\']*)?)["\']',
    re.IGNORECASE,
)
_ENDPOINT_URL_RE = re.compile(
    r'https?://(?:[a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,}(?::\d+)?(?:/[^\s"\'<>\\,)]*)?',
    re.IGNORECASE,
)


def _clean_slug(raw: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (raw or "").strip().lower()).strip("-._")
    return s or "unknown-chain"


def _read_chains_file(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    nested = raw.get("chains")
    if isinstance(nested, dict):
        for k, v in nested.items():
            if isinstance(v, dict):
                out[str(k)] = dict(v)
    for k, v in raw.items():
        if k in ("_README", "chains") or str(k).startswith("_"):
            continue
        if isinstance(v, dict):
            out[str(k)] = dict(v)
    return out


def load_discovered_chains() -> dict[str, dict]:
    """Reads and merges `backend/app/data/discovered_chains.json` (shipped in repo)
    and `storage.data_file("discovered_chains.json")` (runtime volume)."""
    merged = _read_chains_file(_REPO_CHAINS_FILE)
    runtime_path = storage.data_file("discovered_chains.json")
    runtime_chains = _read_chains_file(runtime_path)
    for slug, spec in runtime_chains.items():
        if slug in merged and isinstance(merged[slug], dict):
            combined = dict(merged[slug])
            combined.update(spec)
            merged[slug] = combined
        else:
            merged[slug] = dict(spec)
    return merged


def save_discovered_chain(slug: str, spec: dict) -> dict:
    """Saves `spec` under `slug` in the runtime volume `discovered_chains.json`."""
    norm_slug = _clean_slug(slug)
    entry = dict(spec or {})
    entry["slug"] = norm_slug
    chains = load_discovered_chains()
    chains[norm_slug] = entry
    payload = {
        "_README": _README_TEXT,
        "chains": chains,
    }
    runtime_path = storage.data_file("discovered_chains.json")
    write_text_atomic(runtime_path, json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return entry


def get_discovered_chain(chain: str = "", token: str = "", url: str = "") -> dict | None:
    """Finds a previously discovered chain spec matching `chain`, `token`, or `url`."""
    chains = load_discovered_chains()
    if not chains:
        return None
    _host, origin, slug, _sym = extract_chain_identity(chain, token, url)
    for candidate in (slug, (token or "").strip().lower(), (chain or "").strip().lower()):
        if candidate and candidate in chains:
            return chains[candidate]
    for spec in chains.values():
        if origin and spec.get("origin") == origin:
            return spec
        if token and spec.get("token") == token:
            return spec
        if url and spec.get("url") == url:
            return spec
    return None


def extract_chain_identity(chain: str, token: str, url: str = "") -> tuple[str, str, str, str]:
    """Extracts `(host, origin, slug, symbol)` from `(chain, token, url)`."""
    u = (url or "").strip()
    tok = (token or "").strip()
    ch = (chain or "").strip()

    if not u:
        if tok.startswith(("http://", "https://")):
            u = tok
        elif ch.startswith(("http://", "https://")):
            u = ch

    if tok.lower().startswith("layer:"):
        tok = tok.split(":", 1)[1].strip()

    host = ""
    origin = ""
    path_segments: list[str] = []
    if u:
        parsed = urlparse(u if "://" in u else f"https://{u}")
        if parsed.netloc:
            host = parsed.netloc.lower().split(":")[0]
            scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
            origin = f"{scheme}://{parsed.netloc}"
            path_segments = [p.lower() for p in parsed.path.split("/") if p]

    # 1. Check explicit host aliases (e.g. scan.octa.space -> octa-octaspace, explorer.cheqd.io -> cheqd)
    if host in _KNOWN_SLUG_ALIASES:
        slug, sym = _KNOWN_SLUG_ALIASES[host]
        return host, origin, slug, sym
    for domain_key, (mapped_slug, mapped_sym) in _KNOWN_SLUG_ALIASES.items():
        if "." in domain_key and (host == domain_key or host.endswith("." + domain_key)):
            return host, origin, mapped_slug, mapped_sym

    # 2. Check token / chain in known aliases
    tok_low = tok.lower()
    ch_low = ch.lower()
    if tok_low in _KNOWN_SLUG_ALIASES:
        slug, sym = _KNOWN_SLUG_ALIASES[tok_low]
        return host, origin, slug, sym
    if ch_low in _KNOWN_SLUG_ALIASES and ch_low != "layer":
        slug, sym = _KNOWN_SLUG_ALIASES[ch_low]
        return host, origin, slug, sym

    # 3. Extract slug from multi-chain explorer paths (e.g. mintscan.io/{chain}, ping.pub/{chain})
    slug = ""
    if host and any(k in host for k in ("mintscan.io", "ping.pub", "celatone.osmosis.zone")) and path_segments:
        slug = _clean_slug(path_segments[0])

    # 4. Extract slug from hostname labels (e.g. explorer.cheqd.io -> cheqd)
    if not slug and host:
        parts = [p for p in host.split(".") if p and p not in _HOST_NOISE_PARTS]
        if parts:
            slug = _clean_slug(parts[0])
        else:
            slug = _clean_slug(host.split(".")[0])

    # 5. Fallback to token or chain identifier if it's not a generic hash or 0x address
    if not slug or slug == "unknown-chain":
        if tok_low and not tok_low.startswith(("url-", "http://", "https://", "0x")):
            slug = _clean_slug(tok_low)
        elif ch_low and ch_low not in ("layer", "unknown") and not ch_low.startswith(("http://", "https://")):
            slug = _clean_slug(ch_low)
        elif tok_low:
            slug = _clean_slug(tok_low[:16])
        else:
            slug = "unknown-chain"

    if slug in _KNOWN_SLUG_ALIASES:
        slug, sym = _KNOWN_SLUG_ALIASES[slug]
        return host, origin, slug, sym

    # Determine symbol
    symbol = _KNOWN_SYMBOLS.get(slug, "")
    if not symbol:
        if tok and 2 <= len(tok) <= 8 and tok.isalpha():
            symbol = tok.upper()
        else:
            base_part = slug.split("-")[0]
            symbol = _KNOWN_SYMBOLS.get(base_part) or base_part[:6].upper() or "TOKEN"

    return host, origin, slug, symbol


def _is_relevant_discovered_url(candidate: str, slug: str, host: str) -> bool:
    u_low = candidate.lower()
    if any(u_low.endswith(ext) for ext in (".png", ".svg", ".jpg", ".jpeg", ".gif", ".css", ".woff", ".woff2", ".ico")):
        return False
    if any(ignore in u_low for ignore in ("w3.org", "schema.org", "googleapis.com", "gstatic.com", "cloudflare.com", "twitter.com", "x.com", "t.me", "discord.gg", "discord.com", "github.com")):
        return False
    parsed = urlparse(u_low)
    nhost = parsed.netloc.split(":")[0]
    npath = parsed.path
    if (
        nhost.startswith(("api.", "rpc.", "lcd.", "rest.", "graphql.", "indexer."))
        or ".api." in nhost
        or ".rpc." in nhost
        or "graphql" in u_low
        or "/api/v2" in npath
        or "/api/v1" in npath
        or "/cosmos/" in npath
        or (slug and slug in nhost and any(k in u_low for k in ("api", "rpc", "rest", "lcd", "graphql")))
    ):
        return True
    return False


def _extract_urls_from_text(text: str, slug: str, host: str) -> list[str]:
    found: list[str] = []
    if not text:
        return found
    # Inspect Next.js __NEXT_DATA__ JSON payload first if present
    for match in _NEXT_DATA_RE.finditer(text):
        block = match.group(1)
        for m_url in _ENDPOINT_URL_RE.finditer(block):
            u = m_url.group(0).rstrip(".,;'\")}]")
            if _is_relevant_discovered_url(u, slug, host) and u not in found:
                found.append(u)
    # Inspect the rest of the HTML / JS text
    for m_url in _ENDPOINT_URL_RE.finditer(text):
        u = m_url.group(0).rstrip(".,;'\")}]")
        if _is_relevant_discovered_url(u, slug, host) and u not in found:
            found.append(u)
    return found


async def probe_unknown_chain(
    chain: str,
    token: str,
    url: str = "",
    error: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Probes an unknown/unsupported chain or explorer URL in parallel to discover
    working API endpoints and adapter type, and persists the resulting spec."""
    host, origin, slug, symbol = extract_chain_identity(chain, token, url)
    cosmos_slug = slug.split("-")[0] if "-" in slug and slug not in ("aleph-zero",) else slug

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers={"accept": "application/json, text/html;q=0.9"})

    discovered_endpoints: list[str] = []
    adapter_votes: dict[str, int] = {}
    detected_symbol = symbol

    def _add_endpoint(ep: str) -> None:
        if ep and ep not in discovered_endpoints:
            discovered_endpoints.append(ep)

    async def _probe_blockscout_v2() -> None:
        if not origin:
            return
        assert client is not None
        for ep in (f"{origin}/api/v2/addresses", f"{origin}/api/v2/stats"):
            try:
                r = await client.get(ep)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and (
                        "items" in data
                        or "total_addresses" in data
                        or "total_blocks" in data
                        or "coin_price" in data
                    ):
                        _add_endpoint(ep)
                        adapter_votes["blockscout_v2"] = adapter_votes.get("blockscout_v2", 0) + 10
            except Exception:  # noqa: BLE001
                pass

    async def _probe_blockscout_v1() -> None:
        if not origin:
            return
        assert client is not None
        ep = f"{origin}/api?module=account&action=listaccounts"
        try:
            r = await client.get(ep)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and (
                    isinstance(data.get("result"), list)
                    or str(data.get("status")) == "1"
                ):
                    _add_endpoint(ep)
                    adapter_votes["blockscout_v1"] = adapter_votes.get("blockscout_v1", 0) + 6
        except Exception:  # noqa: BLE001
            pass

    async def _probe_cosmos() -> None:
        nonlocal detected_symbol
        assert client is not None
        dir_url = f"https://chains.cosmos.directory/{cosmos_slug}"
        lcd_url = f"https://rest.cosmos.directory/{cosmos_slug}/cosmos/staking/v1beta1/validators?pagination.limit=5"
        api_net = f"https://api.{cosmos_slug}.net"
        api_io = f"https://api.{cosmos_slug}.io"

        results = await asyncio.gather(
            client.get(dir_url),
            client.get(lcd_url),
            client.get(api_net),
            client.get(api_io),
            return_exceptions=True,
        )

        r_dir, r_lcd, r_net, r_io = results
        if not isinstance(r_dir, Exception) and r_dir.status_code == 200:
            try:
                d = r_dir.json()
                chain_info = d.get("chain") if isinstance(d, dict) else None
                if isinstance(chain_info, dict) or (isinstance(d, dict) and ("chain_name" in d or "apis" in d)):
                    _add_endpoint(dir_url)
                    adapter_votes["cosmos_lcd"] = adapter_votes.get("cosmos_lcd", 0) + 8
                    c_obj = chain_info if isinstance(chain_info, dict) else d
                    c_sym = c_obj.get("symbol")
                    if isinstance(c_sym, str) and c_sym.strip():
                        detected_symbol = c_sym.strip().upper()
                    apis = c_obj.get("apis") or {}
                    if isinstance(apis, dict):
                        for rest_entry in (apis.get("rest") or [])[:3]:
                            if isinstance(rest_entry, dict) and rest_entry.get("address"):
                                _add_endpoint(str(rest_entry["address"]).rstrip("/"))
                        for rpc_entry in (apis.get("rpc") or [])[:2]:
                            if isinstance(rpc_entry, dict) and rpc_entry.get("address"):
                                _add_endpoint(str(rpc_entry["address"]).rstrip("/"))
            except Exception:  # noqa: BLE001
                pass

        if not isinstance(r_lcd, Exception) and r_lcd.status_code == 200:
            try:
                d_lcd = r_lcd.json()
                if isinstance(d_lcd, dict) and ("validators" in d_lcd or "pagination" in d_lcd):
                    _add_endpoint(lcd_url)
                    adapter_votes["cosmos_lcd"] = adapter_votes.get("cosmos_lcd", 0) + 9
            except Exception:  # noqa: BLE001
                pass

        for ep_url, resp in ((api_net, r_net), (api_io, r_io)):
            if not isinstance(resp, Exception) and resp.status_code == 200:
                _add_endpoint(ep_url)
                adapter_votes["cosmos_lcd"] = adapter_votes.get("cosmos_lcd", 0) + 5

    async def _probe_subscan() -> None:
        assert client is not None
        sub_url = f"https://{cosmos_slug}.api.subscan.io/api/scan/metadata"
        try:
            r = await client.get(sub_url)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and (data.get("code") == 0 or "data" in data):
                    _add_endpoint(sub_url)
                    adapter_votes["subscan"] = adapter_votes.get("subscan", 0) + 8
        except Exception:  # noqa: BLE001
            pass

    async def _probe_html_and_bundles() -> None:
        target = (url or origin or "").strip()
        if not target:
            return
        assert client is not None
        try:
            r = await client.get(target)
            if r.status_code != 200:
                return
            html_text = r.text or ""
            for ep in _extract_urls_from_text(html_text, cosmos_slug, host):
                _add_endpoint(ep)
                if "graphql" in ep.lower():
                    adapter_votes["graphql"] = adapter_votes.get("graphql", 0) + 4
                elif any(k in ep.lower() for k in ("cosmos", "lcd", f"api.{cosmos_slug}")):
                    adapter_votes["cosmos_lcd"] = adapter_votes.get("cosmos_lcd", 0) + 3
                else:
                    adapter_votes["custom_api"] = adapter_votes.get("custom_api", 0) + 2

            # Also inspect up to 2 JS bundle URLs referenced in the page if needed
            js_urls: list[str] = []
            for m_js in _JS_SRC_RE.finditer(html_text):
                src = m_js.group(1)
                if src.startswith("http://") or src.startswith("https://"):
                    js_urls.append(src)
                elif origin and src.startswith("/"):
                    js_urls.append(f"{origin}{src}")
                if len(js_urls) >= 2:
                    break
            if js_urls:
                js_resps = await asyncio.gather(
                    *(client.get(ju) for ju in js_urls),
                    return_exceptions=True,
                )
                for jr in js_resps:
                    if not isinstance(jr, Exception) and jr.status_code == 200:
                        for ep in _extract_urls_from_text(jr.text or "", cosmos_slug, host):
                            _add_endpoint(ep)
                            if "graphql" in ep.lower():
                                adapter_votes["graphql"] = adapter_votes.get("graphql", 0) + 4
                            else:
                                adapter_votes["custom_api"] = adapter_votes.get("custom_api", 0) + 2
        except Exception:  # noqa: BLE001
            pass

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _probe_blockscout_v2(),
                _probe_blockscout_v1(),
                _probe_cosmos(),
                _probe_subscan(),
                _probe_html_and_bundles(),
                return_exceptions=True,
            ),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.debug("probe_unknown_chain timed out after 5.0s for %s (%s)", slug, url)
    finally:
        if own_client and client is not None:
            await client.aclose()

    if adapter_votes:
        detected_adapter = max(adapter_votes.items(), key=lambda kv: kv[1])[0]
    elif discovered_endpoints:
        detected_adapter = "custom_api"
    else:
        detected_adapter = "unknown"

    spec = {
        "slug": slug,
        "chain": chain or "layer",
        "token": token or slug,
        "symbol": detected_symbol,
        "origin": origin,
        "url": url,
        "adapter": detected_adapter,
        "endpoints": discovered_endpoints,
        "error": error,
        "discovered_at": int(time.time()),
    }
    save_discovered_chain(slug, spec)
    return spec


def _auto_prs_file() -> Path:
    return storage.data_file("auto_chain_prs.json")


def _load_auto_prs_map() -> dict[str, dict]:
    path = _auto_prs_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(raw, dict):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {
            str(it.get("slug") or idx): dict(it)
            for idx, it in enumerate(raw)
            if isinstance(it, dict)
        }
    return {}


def _save_auto_prs_map(prs: dict[str, dict]) -> None:
    write_text_atomic(_auto_prs_file(), json.dumps(prs, indent=2, sort_keys=True), encoding="utf-8")


def list_auto_prs() -> list[dict]:
    """Returns all auto-generated PR records sorted newest first."""
    prs = _load_auto_prs_map()
    return sorted(prs.values(), key=lambda r: int(r.get("created_at") or 0), reverse=True)


def get_auto_pr(chain: str, token: str = "") -> dict | None:
    """Returns the auto-PR record matching `(chain, token)` or slug if present."""
    prs = _load_auto_prs_map()
    if not prs:
        return None
    _host, _origin, slug, _sym = extract_chain_identity(chain, token, token if (token or "").startswith(("http://", "https://")) else "")
    for candidate in (slug, (token or "").strip().lower(), (chain or "").strip().lower()):
        if candidate and candidate in prs:
            return prs[candidate]
    for rec in prs.values():
        if token and (rec.get("token") == token or rec.get("url") == token):
            return rec
        if chain and rec.get("chain") == chain and not token:
            return rec
    return None


def _ensure_bacheca_issue(spec: dict, host: str, token: str, record: dict) -> str:
    issue_title = f"Auto-PR supporto cluster per {spec['symbol']} ({host or token or spec['slug']})"
    for existing in issues.list_issues():
        if existing.get("title") == issue_title:
            return str(existing.get("id") or "")

    endpoints_str = ", ".join(spec.get("endpoints") or []) or "nessun endpoint pubblico standard rilevato (richiede adapter custom)"
    detail = (
        f"Rilevata chain/explorer non ancora supportato nativamente durante la scansione cluster.\n"
        f"- Chain/Slug: {spec['slug']} ({spec['symbol']})\n"
        f"- URL: {spec.get('url') or spec.get('origin') or token}\n"
        f"- Adapter rilevato: {spec.get('adapter')}\n"
        f"- Endpoints scoperti: {endpoints_str}\n"
        f"- Branch PR: {record['branch']}\n"
        f"- Link PR: {record['pr_url']}"
    )
    if spec.get("error"):
        detail += f"\n- Errore iniziale: {spec['error']}"
    created = issues.add_issue(
        title=issue_title,
        detail=detail,
        priority="alta",
        author="auto-pr",
    )
    return str(created.get("id") or "")


def _build_pr_body(spec: dict, host: str) -> str:
    ep_lines = "\n".join(f"- `{ep}`" for ep in (spec.get("endpoints") or [])) or "- *(none automatically responded; requires custom indexer/adapter)*"
    return (
        f"## Automatic Cluster Support PR for `{spec['symbol']}` (`{spec['slug']}`)\n\n"
        f"An unsupported chain or explorer was encountered during cluster analysis and automatically probed.\n\n"
        f"### Discovered Chain Specification\n"
        f"- **Slug**: `{spec['slug']}`\n"
        f"- **Symbol**: `{spec['symbol']}`\n"
        f"- **Chain / Token**: `{spec.get('chain')}` / `{spec.get('token')}`\n"
        f"- **Host / Origin**: `{host or spec.get('origin') or 'N/A'}`\n"
        f"- **Explorer URL**: {spec.get('url') or 'N/A'}\n"
        f"- **Detected Adapter**: `{spec.get('adapter')}`\n"
        f"- **Initial Scan Error**: `{spec.get('error') or 'N/A'}`\n\n"
        f"### Discovered Endpoints\n"
        f"{ep_lines}\n"
    )


async def _open_github_pr(
    spec: dict,
    host: str,
    branch: str,
    repo: str,
    gh_token: str,
    client: httpx.AsyncClient,
) -> tuple[str | None, int | None]:
    """Creates branch `auto/chain-support-{slug}`, commits updated
    `backend/app/data/discovered_chains.json`, and opens a GitHub Pull Request."""
    api_base = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    slug = spec["slug"]
    title = f"Auto-add cluster support for {spec['symbol']} ({host or slug})"

    # 1. Get main branch SHA
    r_ref = await client.get(f"{api_base}/git/ref/heads/main", headers=headers)
    if r_ref.status_code != 200:
        return None, None
    ref_data = r_ref.json() or {}
    base_sha = (ref_data.get("object") or {}).get("sha")
    if not base_sha:
        return None, None

    # 2. Create branch ref (ignore 422 if branch already exists)
    r_create_ref = await client.post(
        f"{api_base}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
    )
    if r_create_ref.status_code not in (200, 201, 422):
        return None, None

    # 3. Fetch current `backend/app/data/discovered_chains.json` on the branch/repo
    contents_url = f"{api_base}/contents/backend/app/data/discovered_chains.json"
    r_file = await client.get(contents_url, headers=headers, params={"ref": branch})
    if r_file.status_code == 404:
        r_file = await client.get(contents_url, headers=headers)

    file_sha: str | None = None
    existing_chains = load_discovered_chains()
    if r_file.status_code == 200:
        f_data = r_file.json() or {}
        file_sha = f_data.get("sha")
        b64_content = f_data.get("content") or ""
        if b64_content:
            try:
                decoded = base64.b64decode(b64_content).decode("utf-8")
                loaded = json.loads(decoded)
                if isinstance(loaded, dict) and isinstance(loaded.get("chains"), dict):
                    for k, v in loaded["chains"].items():
                        if isinstance(v, dict):
                            existing_chains[str(k)] = dict(v)
            except Exception:  # noqa: BLE001
                pass

    existing_chains[slug] = spec
    updated_payload = {
        "_README": _README_TEXT,
        "chains": existing_chains,
    }
    encoded_content = base64.b64encode(
        json.dumps(updated_payload, indent=2, sort_keys=True).encode("utf-8")
    ).decode("ascii")

    put_body: dict = {
        "message": title,
        "content": encoded_content,
        "branch": branch,
    }
    if file_sha:
        put_body["sha"] = file_sha

    r_put = await client.put(contents_url, headers=headers, json=put_body)
    if r_put.status_code not in (200, 201):
        return None, None

    # 4. Open Pull Request
    r_pr = await client.post(
        f"{api_base}/pulls",
        headers=headers,
        json={
            "title": title,
            "head": branch,
            "base": "main",
            "body": _build_pr_body(spec, host),
        },
    )
    if r_pr.status_code in (200, 201):
        pr_data = r_pr.json() or {}
        pr_number = pr_data.get("number")
        pr_url = pr_data.get("html_url") or pr_data.get("url")
        return pr_url, int(pr_number) if pr_number is not None else None

    return None, None


async def ensure_auto_pr(
    chain: str,
    token: str,
    url: str = "",
    error: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Probes an unknown chain, saves its discovered configuration, and ensures
    an automatic GitHub Pull Request and Bacheca issue are created."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)

    try:
        assert client is not None
        spec = await probe_unknown_chain(chain, token, url, error, client=client)
        slug = spec["slug"]
        host, _origin, _s, _sym = extract_chain_identity(chain, token, url or spec.get("origin") or "")

        prs = _load_auto_prs_map()
        if slug in prs:
            existing = prs[slug]
            _ensure_bacheca_issue(spec, host, token, existing)
            return existing

        repo = os.environ.get("GITHUB_REPO", "D3g3n3r4t0r/DegenView").strip() or "D3g3n3r4t0r/DegenView"
        gh_token = os.environ.get("GITHUB_API_TOKEN", "").strip()
        branch = f"auto/chain-support-{slug}"
        compare_url = f"https://github.com/{repo}/compare/main...{branch}?expand=1"

        pr_url: str | None = None
        pr_number: int | None = None
        if gh_token:
            try:
                pr_url, pr_number = await _open_github_pr(
                    spec=spec,
                    host=host,
                    branch=branch,
                    repo=repo,
                    gh_token=gh_token,
                    client=client,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to open GitHub auto-PR for %s: %s", slug, exc)

        record = {
            "slug": slug,
            "chain": chain or "layer",
            "token": token or slug,
            "symbol": spec["symbol"],
            "url": url or spec.get("origin") or "",
            "adapter": spec["adapter"],
            "family": spec["adapter"],
            "endpoints": spec["endpoints"],
            "branch": branch,
            "pr_url": pr_url or compare_url,
            "pr_number": pr_number,
            "status": "opened" if pr_number else "queued",
            "message": f"Branch {branch} pronto per introdurre il supporto nativo a {spec['symbol']} ({spec['adapter']})",
            "created_at": int(time.time()),
        }
        issue_id = _ensure_bacheca_issue(spec, host, token, record)
        if issue_id:
            record["issue_id"] = issue_id

        prs[slug] = record
        _save_auto_prs_map(prs)
        return record
    finally:
        if own_client and client is not None:
            await client.aclose()
