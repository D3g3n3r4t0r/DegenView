# Model gems, second pass: fresh data and the reviewer's corrections
tokens: robinhood:0xd293291060334D42E5DBEa6fb854C231AF527777, solana:G5W6LwkLeoj6rZqBP1y3KT8k6Cz6rXGJmMNU3TArXtXw, robinhood:0xa934bA4F59070149d37A93F8A002Af79BAe35563, robinhood:0x727701F88f09Fed71eb217Bcea88b3F314CF7079, robinhood:0x459476869aF797Eb9061B41fA04dE46A60FBeDBD, solana:XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump
follow_up: 001-gem-models
max_tokens: 8000

Your study 001 was reviewed line by line and is NOT usable yet. Reasons:
- It was built on stale pillar scores. PFWA's "empty page", GRID 29% and BV7X 41% "single wallet" (those were contracts: pools, vesting), BV7X "GitHub link without a repository" (it links working repos) were all bugs in our pipeline, now fixed. The dossiers below are recomputed today, every pillar fresh, with the top 10 holders labelled contract or wallet.
- "Domain registered before the token" is NOT a red flag: serious projects exist before their token. Do not use it.
- Thresholds like "holders >= 1500" or "LP locked >= 90%" were not derived from these projects' data; several of the five would fail them. Every number you propose must be satisfied by at least four of the five, and you must show the values.
- AUREON's SDK (github.com/buildaureon/aureon-sdk) was ignored, and a site we cannot read (JavaScript) is unknown, not weak.
- Your answer was cut at the token limit. Be dense: no repetition, no preamble.

Kept from 001 (confirm or refute with today's data): named, verifiable technical primitives (x402, LayerZero, ERC-8004, EAS, Turnkey, Umbra, Lean/STARK proofs) are the common thread; missing public code lowers confidence but does not exclude; the judge's "avoid" on STEALF was too harsh.

Answer in this order, compactly:
1. One table row per project (six, DREGG included): cap, liquidity/cap, age, wallet top1 and top10 (contracts excluded), contracts %, code (repo, last commit, stars or "private"), product live (evidence), named primitives found, our current verdict, right or wrong in one phrase.
2. The profile of a serious gem as 5-10 measurable signals. For each: the exact dossier field or text pattern, the threshold, the values of the six projects, must-have or bonus.
3. Which current checks to change and how (current rule -> new rule, with numbers), and which checks are right and must stay.
4. What must still exclude a project (memecoins, copies, rugs, parody names, wrappers), stated as checks, so that the changes in 3 do not let them in.
5. Search: 10-20 concrete search queries or sources (keywords, launchpads, chains, GitHub topics) that would surface more projects with this profile.
Mark every claim the dossiers do not support as "unverified".
