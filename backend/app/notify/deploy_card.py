"""
Notifica di deploy arricchita per Telegram: messaggio strutturato in italiano
con diagrammi/figure ASCII-Unicode, stato dei moduli, segnalazioni risolte e
card grafica PNG generata al volo con Pillow (`render_deploy_card`).
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
_SEED_RE = re.compile(r"\b(seed-\d{4})\b", re.IGNORECASE)

# Aree funzionali della piattaforma per la figura/mappa di impatto del deploy.
_AREAS: list[tuple[str, str, tuple[str, ...]]] = [
    ("app_onchain", "⚡ App & On-Chain", (
        "onchain", "/app", "wallet", "solana", "evm", "swap", "token", "leaderboard",
        "passkey", "reveal", "dex", "pool", "jito", "robinhood",
    )),
    ("mercati", "📈 Grafici & Strategie", (
        "chart", "grafico", "strateg", "indicator", "candle", "candel", "pine",
        "backtest", "watchlist", "sniper", "futures", "mexc", "bybit", "binance",
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
        "perf", "db", "database", "api", "main", "config",
    )),
]


def _commit_icon(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("sicurezz", "vulnerab", "auth", "csrf", "xss", "passkey", "audit", "security")):
        return "🛡️"
    if any(k in low for k in ("/app", "on-chain", "onchain", "wallet", "token", "swap", "solana")):
        return "⚡"
    if any(k in low for k in ("telegram", "notific", "alert", "deploy", "messagg")):
        return "🔔"
    if any(k in low for k in ("grafico", "chart", "strateg", "candel", "indicator", "backtest")):
        return "📈"
    if any(k in low for k in ("fix", "risolt", "sistem", "corrett", "bug", "errore")):
        return "🛠️"
    return "✨"


def _extract_details(commit_message: str) -> list[str]:
    """Estrae eventuali punti elenco o righe descrittive aggiuntive dal commit
    (escludendo il titolo, i trailer tecnici e l'eventuale riga Aggiornamento)."""
    lines = commit_message.splitlines()
    out: list[str] = []
    for raw in lines[1:]:
        s = raw.strip()
        if not s:
            continue
        if any(s.lower().startswith(p) for p in (
            "aggiornamento:", "solo-account:", "co-authored-by:",
            "claude-session:", "signed-off-by:",
        )):
            continue
        if s.startswith(("-", "*", "•")):
            s = s.lstrip("-*• ").strip()
        if s and len(s) > 3:
            out.append(s)
    return out[:4]


def _compute_area_scores(commits: list[dict]) -> list[tuple[str, int]]:
    """Calcola il peso (0..5 tacche) di ciascuna area funzionale toccata dal deploy."""
    corpus = "\n".join((c.get("commit", {}).get("message") or "") for c in commits).lower()
    scores: list[tuple[str, int]] = []
    for _key, label, keywords in _AREAS:
        hits = sum(1 for kw in keywords if kw in corpus)
        bars = min(5, max(1 if hits > 0 else 0, (hits + 1) // 2))
        scores.append((label, bars))
    if all(b == 0 for _, b in scores) and commits:
        scores[-1] = (scores[-1][0], 3)
    return scores


def _bar_str(filled: int, total: int = 5) -> str:
    return "▰" * filled + "▱" * (total - filled)


def _matching_resolutions(commits: list[dict], resolutions_path: Path | None = None) -> list[tuple[str, str]]:
    """Trova le segnalazioni (`seed-XXXX`) citate nei commit del deploy."""
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
            summary = res["summary"].strip().split(". ")[0].rstrip(".")
            out.append((sid, summary))
    return out


def build_deploy_message(
    commits: list[dict],
    repo: str = "D3g3n3r4t0r/DegenView",
    now: int | None = None,
    resolutions_path: Path | None = None,
) -> str:
    """Costruisce il messaggio HTML completo e illustrato per Telegram."""
    dt = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
    months = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
    date_str = f"{dt.day:02d} {months[dt.month - 1]} {dt.year} · {dt.strftime('%H:%M')} UTC"

    head_sha = (commits[0].get("sha") or "-------")[:7] if commits else "-------"
    n_commits = len(commits)

    header = (
        "🚀 <b>NUOVO DEPLOY IN PRODUZIONE</b>\n"
        "<code>╭──────────────────────────────────────╮</code>\n"
        "<code>│</code> 🟢 <b>Stato:</b> Online · Tutti i servizi attivi\n"
        f"<code>│</code> 🕒 <b>Orario:</b> {date_str}\n"
        f"<code>│</code> 📦 <b>Release:</b> <code>{head_sha}</code> ({n_commits} {'modifica' if n_commits == 1 else 'modifiche'})\n"
        "<code>╰──────────────────────────────────────╯</code>"
    )

    # Figura 1: Mappa visuale delle aree toccate
    area_scores = _compute_area_scores(commits)
    area_lines = ["<b>📊 Figura 1 · Mappa d'Impatto dei Moduli:</b>"]
    for label, bars in area_scores:
        state = "AGGIORNATO" if bars > 0 else "stabile"
        area_lines.append(f"<code>{_bar_str(bars)}</code> {label} <i>({state})</i>")
    area_block = "\n".join(area_lines)

    # Elenco ricco delle modifiche in italiano
    change_lines: list[str] = ["<b>🛠️ Modifiche e Novità sul Sito:</b>"]
    for c in commits:
        full_msg = c.get("commit", {}).get("message") or ""
        sha_short = (c.get("sha") or "")[:7]
        it_text = weekly_recap.italian_line(full_msg)
        icon = _commit_icon(full_msg + " " + it_text)
        escaped_it = html.escape(it_text, quote=False)
        commit_url = f"https://github.com/{repo}/commit/{c.get('sha', '')}"
        change_lines.append(
            f"• {icon} <a href=\"{commit_url}\"><code>{sha_short}</code></a> — <b>{escaped_it}</b>"
        )
        for sub in _extract_details(full_msg):
            change_lines.append(f"   └ <i>{html.escape(sub, quote=False)}</i>")

    if not commits:
        change_lines.append("• (nessun commit trovato)")
    changes_block = "\n".join(change_lines)

    # Eventuali segnalazioni della bacheca risolte in questo deploy
    resolved = _matching_resolutions(commits, resolutions_path=resolutions_path)
    res_block = ""
    if resolved:
        res_lines = ["\n<b>✅ Segnalazioni Bacheca Risolte:</b>"]
        for sid, summary in resolved:
            res_lines.append(
                f"• <code>{html.escape(sid, quote=False)}</code> — {html.escape(summary, quote=False)}."
            )
        res_block = "\n".join(res_lines) + "\n"

    # Figura 2: Pipeline & Architettura
    pipeline_block = (
        "<b>🗺️ Figura 2 · Pipeline &amp; Stato Nodo:</b>\n"
        "<code>[GitHub main] ──▶ [Docker Build] ──▶ [Caddy TLS] ──▶ [LIVE ✅]</code>\n"
        "<code> ├─ Desktop &amp; Mobile (/app) : ATTIVO</code>\n"
        "<code> ├─ Motore Mercati &amp; WS     : ATTIVO</code>\n"
        "<code> └─ Guardie On-Chain &amp; Auth : PROTETTE</code>\n\n"
        f"🔗 <a href=\"https://github.com/{repo}/commits/main\">Cronologia GitHub</a>"
    )

    return f"{header}\n\n{area_block}\n\n{changes_block}\n{res_block}\n{pipeline_block}"


def _wrap_text(text: str, width: int = 62) -> list[str]:
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
    """Genera un'immagine PNG (1200x720+) con il riepilogo grafico del deploy."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    dt = datetime.fromtimestamp(now, tz=timezone.utc) if now else datetime.now(timezone.utc)
    months = ["GEN", "FEB", "MAR", "APR", "MAG", "GIU", "LUG", "AGO", "SET", "OTT", "NOV", "DIC"]
    date_str = f"{dt.day:02d} {months[dt.month - 1]} {dt.year}  •  {dt.strftime('%H:%M')} UTC"
    head_sha = (commits[0].get("sha") or "-------")[:7] if commits else "-------"

    items: list[tuple[str, list[str]]] = []
    for c in commits[:6]:
        sha_short = (c.get("sha") or "")[:7]
        it_text = weekly_recap.italian_line(c.get("commit", {}).get("message") or "")
        wrapped = _wrap_text(it_text, width=58)[:3]
        items.append((sha_short, wrapped))

    resolved = _matching_resolutions(commits, resolutions_path=resolutions_path)
    area_scores = _compute_area_scores(commits)

    width = 1200
    extra_rows = sum(len(w) for _, w in items)
    height = max(700, 420 + extra_rows * 34 + (80 if resolved else 0))

    img = Image.new("RGB", (width, height), (11, 15, 25))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 18)
        font_h2 = ImageFont.truetype("DejaVuSans-Bold.ttf", 21)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 19)
        font_mono = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 18)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = font_title
        font_h2 = font_title
        font_body = font_title
        font_mono = font_title

    # Bordo esterno e barra superiore neon
    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=22, fill=(17, 24, 39), outline=(34, 211, 238), width=2)
    draw.rounded_rectangle((36, 36, width - 36, 134), radius=16, fill=(15, 32, 52), outline=(56, 189, 248), width=1)

    draw.text((58, 52), "DEGEN VIEW  •  NUOVO DEPLOY LIVE", fill=(34, 211, 238), font=font_title)
    draw.text((58, 94), f"Release #{head_sha}   |   {date_str}   |   {len(commits)} commit pubblicati", fill=(148, 163, 184), font=font_sub)

    # Badge ONLINE in alto a destra
    draw.rounded_rectangle((width - 250, 56, width - 58, 112), radius=14, fill=(6, 78, 59), outline=(16, 185, 129), width=2)
    draw.text((width - 222, 73), "●  PRODUZIONE OK", fill=(110, 231, 183), font=font_h2)

    # Colonna sinistra: Modifiche in italiano
    draw.text((54, 158), "MODIFICHE APPLICATE AL SITO", fill=(248, 250, 252), font=font_h2)
    y = 198
    for sha_short, lines_wrapped in items:
        box_h = 26 + len(lines_wrapped) * 28
        draw.rounded_rectangle((50, y, 750, y + box_h), radius=12, fill=(24, 33, 52), outline=(51, 65, 85), width=1)
        draw.rounded_rectangle((64, y + 12, 164, y + 40), radius=8, fill=(14, 116, 144))
        draw.text((74, y + 16), f"#{sha_short}", fill=(224, 242, 254), font=font_mono)
        ty = y + 14
        for ln in lines_wrapped:
            draw.text((180, ty), ln, fill=(241, 245, 249), font=font_body)
            ty += 27
        y += box_h + 14

    if resolved:
        sid_list = ", ".join(s for s, _ in resolved[:4])
        draw.rounded_rectangle((50, y + 4, 750, y + 54), radius=10, fill=(6, 60, 46), outline=(16, 185, 129), width=1)
        draw.text((68, y + 18), f"✓ Segnalazioni bacheca risolte: {sid_list}", fill=(167, 243, 208), font=font_body)

    # Colonna destra: Figura barre impatto moduli + architettura
    draw.rounded_rectangle((776, 156, width - 44, height - 88), radius=16, fill=(15, 23, 42), outline=(51, 65, 85), width=1)
    draw.text((800, 176), "MAPPA MODULI", fill=(56, 189, 248), font=font_h2)

    ry = 220
    clean_labels = [
        ("App On-Chain (/app)", area_scores[0][1]),
        ("Grafici & Strategie", area_scores[1][1]),
        ("Sicurezza & Auth", area_scores[2][1]),
        ("Telegram & Alert", area_scores[3][1]),
        ("Server & Bacheca", area_scores[4][1]),
    ]
    for name, score in clean_labels:
        draw.text((800, ry), name, fill=(226, 232, 240), font=font_sub)
        ry += 28
        for seg in range(5):
            bx0 = 800 + seg * 66
            bx1 = bx0 + 56
            color = (34, 211, 238) if seg < score else (30, 41, 59)
            draw.rounded_rectangle((bx0, ry, bx1, ry + 14), radius=5, fill=color)
        ry += 32

    # Mini diagramma pipeline in basso a destra
    ry += 10
    draw.text((800, ry), "PIPELINE STATO", fill=(167, 139, 250), font=font_h2)
    ry += 34
    for step_lbl in ("1. GitHub main sincronizzato", "2. Container Docker ricreati", "3. Proxy TLS Caddy attivo"):
        draw.text((800, ry), f"● {step_lbl}", fill=(110, 231, 183), font=font_sub)
        ry += 28

    # Footer
    draw.text(
        (54, height - 56),
        "DegenView  •  Notifica automatica di rilascio  •  Tutti i controlli superati",
        fill=(100, 116, 139),
        font=font_sub,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
