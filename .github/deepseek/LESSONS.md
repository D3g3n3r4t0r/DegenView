# Lessons from your past tasks

Each line is a mistake you made in this repository and was corrected in
review. Read them before answering: the same mistake again is a failed task.

## Editing blocks
- Write the bare path after SEARCH (`frontend/x.js`), never `path=…`, quotes, or the example `path/to/file` (#176, #177).
- A SEARCH must match exactly one place. `@layer skin {` appears 24 times in app.css: to add CSS at the end of a file use an APPEND block (#188, #190).
- Every file the task names as new must be created with an empty SEARCH. #188 imported `nozoom.js` without writing it: the whole app would have been blank.
- Never leave placeholder or example files in the answer (#178, #182).

## Tests
- When you change a behaviour, search `backend/tests/` for the function you changed and update the old tests that assert the old behaviour (#189 broke `test_system.py`).
- Test data must look real: strategies do not trade on candles with high == low == close and constant volume. Give candles a range and varying volume (#200).
- Assert what the task measured, not a guess: if the task gives measured numbers, use them.

## Stored results
- If a change alters numbers computed from saved data, bump the version constant that triggers the rebuild (`SYSTEM_VERSION` in alert_track.py) and fetch enough data for it (#189).

## Logic
- Per-kind settings stay per kind: gem alerts are judged with the gem system, not the meme one (#178).
- "One at a time" in a task means one at a time: dropping whole blocks of a list can overshoot (#182).

## Frontend
- No trade, no data: show "—", never a green `0%` (#190, #191, #201). A null percent is not zero.
- The initial state must match what is on screen: a pre-selected chip means the list is already sorted by it (#201).
- A function you call must be in scope where you call it. app.js is one big closure with inner functions: check where it is defined before calling it from a new place (#203, `setArea`).
- If the page's own boot later loads something over your change (the main site opens the saved ticker, BTC), hook your code into that boot step instead of running before it (#203).
- `window.open` must run synchronously inside the tap. After an `await`, iOS blocks it: open the window first, set its URL afterwards (#203).
- Phone inputs under 16px make iOS zoom the page; keep form fields at 16px or more (#188).
- Icons must read on the dark background: thin dark-brown strokes vanish; use the gold fill or light strokes of at least 2px (#211).
- A CSS grid needs one column per child: `.pf-cash` had 5 children in 4 columns and the last button wrapped onto its own row (#214).
- Before deleting a constant or function, search the file for every use of it: #216 removed `NAMES` while `onClick` still read it.
- Every function you call must be imported: #190 called `strategyTrade` in detail.js without importing it, so the token page broke.
- "Never show X" means every place X can reach the screen, including labels passed through (`al.system.label` printed "Trend HF" in the event list, #216).
- `threading.Lock` is not re-entrant: never call a function that takes the same lock (e.g. `profiles.get`) while holding it — the tests hang forever (#226).
- #226 repeated #190: `hideToken` used in detail.js without an import. Before finishing, list every function you call in each file you touched and check its import line.
