# DeepSeek studies

Claude asks DeepSeek for deep studies through this folder; the server
(`backend/app/notify/deepseek_studies.py`) reads `requests/` on `main` every
5 minutes, attaches the gem finder's dossier of the tokens named, asks
DeepSeek and keeps the exchange in `backend/data/deepseek_studies.json`.

One request per file, `requests/<id>.md` (id = file stem, e.g. `001-gem-models`):

```
# Title
tokens: solana:<mint>, base:0x<address>
follow_up: 001-gem-models
max_tokens: 6000

The question, as long as it needs to be.
```

- Header lines are optional and end at the first blank line.
- `tokens`: projects whose full dossier is attached (market, pillars, rules
  verdict, judge and code review, site text); at most 8.
- `follow_up`: continue that study; its prompt and answer go in as earlier turns.
- `max_tokens`: answer length, default 4000, capped at 8000.
- Editing a file (new git sha) asks again. At most 20 calls a day; a failed
  call is retried after 1 hour, 3 tries in all.

Answers (public, read-only):

```
curl -s https://liquidityengine.app/api/deepseek/studies
curl -s https://liquidityengine.app/api/deepseek/studies/<id>
```
