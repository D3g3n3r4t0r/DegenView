"""
Notifica di deploy concisa ed editoriale per Telegram: un singolo messaggio
compatto con le modifiche essenziali, i moduli toccati e una card grafica PNG
in stile Design 01 (`render_deploy_card`).
"""

from __future__ import annotations

import html
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.notify import weekly_recap

_RESOLUTIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "resolutions.json"
# seed-NNNN, and since 23/10 seed-NNNN + the account letter (g, l: CLAUDE.md).
_SEED_RE = re.compile(r"\b(seed-\d{4}[a-z]?)\b", re.IGNORECASE)

_AREAS: list[tuple[str, str, tuple[str, ...]]] = [
    ("app_onchain", "⚡ App & On-Chain", (
        "onchain", "/app", "wallet", "solana", "evm", "swap", "token", "leaderboard",
        "passkey", "reveal", "dex", "pool", "jito", "robinhood", "settor", "sector",
    )),
    ("mercati", "📈 Grafici & Strategie", (
        "chart", "grafico", "strateg", "indicator", "candle", "candel", "pine",
        "backtest", "watchlist", "sniper", "futures", "mexc", "bybit", "binance", "desktop", "mobile",
    )),
    ("sicurezza", "🛡️ Sicurezza & Auth", (
        "sec", "sicurezz", "auth", "login", "cookie", "csrf", "xss", "rate",
        "vulnerab", "audit", "guest", "ospite", "traversal", "lock",
    )),
    ("notifiche", "🔔 Telegram & Alert", (
        "telegram", "notify", "notific", "alert", "recap", "deploy", "push", "bot",
    )),
    ("core", "⚙️ Server & Bacheca", (
        "server", "docker", "caddy", "issue", "bacheca", "seed-", "cantiere",
        "perf", "db", "database", "api", "main", "config", "self-heal", "autoripristin",
    )),
]


def _commit_icon(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("sicurezz", "vulnerab", "auth", "csrf", "xss", "passkey", "audit", "security")):
        return "🛡️"
    if any(k in low for k in ("/app", "on-chain", "onchain", "wallet", "token", "swap", "solana", "settor")):
        return "⚡"
    if any(k in low for k in ("telegram", "notific", "alert", "deploy", "messagg")):
        return "🔔"
    if any(k in low for k in ("grafico", "chart", "strateg", "candel", "indicator", "backtest", "desktop", "design")):
        return "📈"
    if any(k in low for k in ("fix", "risolt", "sistem", "corrett", "bug", "errore", "ripristin")):
        return "🛠️"
    return "✨"


def _short_text(text: str, limit: int = 115) -> str:
    s = " ".join((text or "").split())
    if len(s) <= limit:
        return s
    cut = s[: limit - 1].rsplit(" ", 1)[0]
    return (cut or s[: limit - 1]).rstrip(".,;:") + "…"


def _compute_area_scores(commits: list[dict]) -> list[tuple[str, int]]:
    corpus = "\n".join((c.get("commit", {}).get("message") or "") for c in commits).lower()
    scores: list[tuple[str, int]] = []
    for _key, label, keywords in _AREAS:
        hits = sum(1 for kw in keywords if kw in corpus)
        bars = min(5, max(1 if hits > 0 else 0, (hits + 1) // 2))
        scores.append((label, bars))
    if all(b == 0 for _, b in scores) and commits:
        scores[-1] = (scores[-1][0], 3)
    return scores


def _matching_resolutions(commits: list[dict], resolutions_path: Path | None = None) -> list[tuple[str, str]]:
    target = resolutions_path or _RESOLUTIONS_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []

    mentioned: list[str] = []
    for c in commits:
        msg = c.get("commit", {}).get("message") or ""
        for m in _SEED_RE.findall(msg):
            sid = m.lower()
            if sid not in mentioned:
                mentioned.append(sid)

    out: list[tuple[str, str]] = []
    for sid in mentioned:
        res = raw.get(sid)
        if isinstance(res, dict) and (res.get("summary") or "").strip():
            summary = _short_text(res["summary"].strip().split(". ")[0].rstrip("."), 90)
            out.append((sid, summary))
        else:
            out.append((sid, ""))
    return out


def build_deploy_message(
    commits: list[dict],
    repo: str = "D3g3n3r4t0r/DegenView",
    now: int | None = None,
    resolutions_path: Path | None = None,
) -> str:
    """Costruisce un messaggio Telegram corto, pulito e immediato (< 800 caratteri)."""
    dt = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
    months = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
    date_str = f"{dt.day:02d} {months[dt.month - 1]} · {dt.strftime('%H:%M')} UTC"

    head_sha = (commits[0].get("sha") or "-------")[:7] if commits else "-------"
    area_scores = _compute_area_scores(commits)
    active_areas = [label for label, bars in area_scores if bars > 0]

    lines: list[str] = [
        f"🚀 <b>Deploy live</b> · <code>{head_sha}</code> · {date_str}",
    ]
    if active_areas:
        lines.append("📦 " + " · ".join(active_areas[:3]))
    lines.append("")

    for c in commits[:6]:
        full_msg = c.get("commit", {}).get("message") or ""
        sha_short = (c.get("sha") or "")[:7]
        it_text = _short_text(weekly_recap.italian_line(full_msg), 110)
        icon = _commit_icon(full_msg + " " + it_text)
        escaped_it = html.escape(it_text, quote=False)
        commit_url = f"https://github.com/{repo}/commit/{c.get('sha', '')}"
        lines.append(f"• {icon} <a href=\"{commit_url}\"><code>{sha_short}</code></a> {escaped_it}")

    if not commits:
        lines.append("• (nessun commit trovato)")

    resolved = _matching_resolutions(commits, resolutions_path=resolutions_path)
    if resolved:
        sids = ", ".join(f"<code>{html.escape(sid, quote=False)}</code>" for sid, _ in resolved[:5])
        lines.append(f"\n✅ <b>Bacheca:</b> {sids}")

    return "\n".join(lines)


def _wrap_text(text: str, width: int = 58) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def render_deploy_card(
    commits: list[dict],
    now: int | None = None,
    resolutions_path: Path | None = None,
) -> bytes | None:
    """Genera una card PNG compatta in stile Design 01 (Warm Paper & Forest Ink)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    dt = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
    months = ["GEN", "FEB", "MAR", "APR", "MAG", "GIU", "LUG", "AGO", "SET", "OTT", "NOV", "DIC"]
    date_str = f"{dt.day:02d} {months[dt.month - 1]} {dt.year} · {dt.strftime('%H:%M')} UTC"
    head_sha = (commits[0].get("sha") or "-------")[:7] if commits else "-------"

    items: list[tuple[str, list[str]]] = []
    for c in commits[:5]:
        sha_short = (c.get("sha") or "")[:7]
        it_text = _short_text(weekly_recap.italian_line(c.get("commit", {}).get("message") or ""), 110)
        wrapped = _wrap_text(it_text, width=54)[:2]
        items.append((sha_short, wrapped))

    resolved = _matching_resolutions(commits, resolutions_path=resolutions_path)
    area_scores = _compute_area_scores(commits)

    width = 1120
    extra_rows = sum(len(w) for _, w in items)
    height = max(480, 260 + extra_rows * 36 + (56 if resolved else 0))

    # Palette Design 01: Warm Paper (#efeae0), Card (#f8f5ef), Forest Ink (#2f3a32), Sage (#c9d4c0), Moss (#2f7a4a)
    img = Image.new("RGB", (width, height), (239, 234, 224))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 16)
        font_h2 = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 17)
        font_mono = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 16)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = font_title
        font_h2 = font_title
        font_body = font_title
        font_mono = font_title

    # Card container
    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=24, fill=(248, 245, 239), outline=(200, 191, 174), width=2)
    # Header bar in Forest Ink (#2f3a32)
    draw.rounded_rectangle((36, 36, width - 36, 116), radius=18, fill=(47, 58, 50))
    draw.text((58, 48), "DEGEN·VIEW  —  DEPLOY LIVE", fill=(243, 239, 230), font=font_title)
    draw.text((58, 82), f"#{head_sha}  ·  {date_str}  ·  {len(commits)} {'modifica' if len(commits) == 1 else 'modifiche'}", fill=(201, 212, 192), font=font_sub)

    # Pill badge in Sage (#c9d4c0)
    draw.rounded_rectangle((width - 210, 54, width - 56, 98), radius=22, fill=(201, 212, 192))
    draw.text((width - 186, 66), "● ONLINE", fill=(47, 58, 50), font=font_h2)

    # Left column: concise commit cards
    y = 136
    for sha_short, lines_wrapped in items:
        box_h = 22 + len(lines_wrapped) * 25
        draw.rounded_rectangle((40, y, 730, y + box_h), radius=14, fill=(239, 234, 224), outline=(224, 217, 203), width=1)
        draw.rounded_rectangle((52, y + 10, 142, y + 36), radius=12, fill=(47, 58, 50))
        draw.text((62, y + 14), f"#{sha_short}", fill=(243, 239, 230), font=font_mono)
        ty = y + 12
        for ln in lines_wrapped:
            draw.text((156, ty), ln, fill=(47, 58, 50), font=font_body)
            ty += 24
        y += box_h + 10

    if resolved:
        sid_list = ", ".join(s for s, _ in resolved[:5])
        draw.rounded_rectangle((40, y + 2, 730, y + 44), radius=12, fill=(201, 212, 192))
        draw.text((56, y + 12), f"✓ Bacheca: {sid_list}", fill=(47, 58, 50), font=font_body)

    # Right column: Module impact bars
    draw.rounded_rectangle((752, 136, width - 40, height - 40), radius=18, fill=(239, 234, 224), outline=(224, 217, 203), width=1)
    draw.text((774, 154), "MODULI AGGIORNATI", fill=(47, 58, 50), font=font_h2)

    ry = 190
    clean_labels = [
        ("App & On-Chain", area_scores[0][1]),
        ("Grafici & Strategie", area_scores[1][1]),
        ("Sicurezza & Auth", area_scores[2][1]),
        ("Telegram & Alert", area_scores[3][1]),
        ("Server & Bacheca", area_scores[4][1]),
    ]
    for name, score in clean_labels:
        draw.text((774, ry), name, fill=(47, 58, 50), font=font_sub)
        ry += 24
        for seg in range(5):
            bx0 = 774 + seg * 56
            bx1 = bx0 + 48
            color = (47, 122, 74) if seg < score else (216, 209, 195)
            draw.rounded_rectangle((bx0, ry, bx1, ry + 10), radius=5, fill=color)
        ry += 24

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
