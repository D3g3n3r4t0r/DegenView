# $ENGN crypto-asset white paper — DRAFT

> Draft following the structure of Annex I to Regulation (EU) 2023/1114
> (MiCA), for crypto-assets other than asset-referenced tokens and e-money
> tokens. Not reviewed by a lawyer, not notified, not approved. Fields marked
> **[TBD]** need the offeror's data. Do not publish in this state.

## Mandatory statements (MiCA art. 6)

This crypto-asset white paper has not been approved by any competent
authority in any Member State of the European Union. The offeror of the
crypto-asset is solely responsible for the content of this white paper.

This white paper complies with Title II of Regulation (EU) 2023/1114 and, to
the best of the knowledge of the management body, the information presented
is fair, clear and not misleading, and makes no omission likely to affect
its import.

The crypto-asset may lose its value in part or in full, may not always be
transferable, and may not be liquid. It is not covered by investor
compensation schemes under Directive 97/9/EC or deposit guarantee schemes
under Directive 2014/49/EU.

## Summary

$ENGN is a fixed-supply SPL token on Solana that grants holders access
tiers in the Liquidity Engine app, an on-chain wallet with a token scanner,
a project leaderboard and trend-following automation limited to long spot
trades. The token grants no ownership, profit share, voting right over a
company, or claim on revenue. 1,000,000,000 tokens exist; 45% is placed in
a public liquidity pool at launch whose LP tokens are burned.

## Part A — Offeror

| | |
|---|---|
| Name, legal form | **[TBD]** (a legal person is required, MiCA art. 4) |
| LEI | **[TBD]** |
| Registered address, contact | **[TBD]** |
| Management body | **[TBD]** |
| Business activity | Development and operation of the Liquidity Engine software |
| Financial condition (3 years) | **[TBD]** |

## Part B — Issuer (if different)

Same as offeror.

## Part C — Trading platform operator

Not applicable. No admission to trading is requested at launch; the token
is exchanged on a decentralised automated market maker.

## Part D — Project

- **Name:** Liquidity Engine. **Token:** Engine, ticker ENGN.
- **Product (live before the token):** non-custodial-style wallet with
  server-side encrypted, exportable keys; scanner of newly launched tokens
  on Solana, Robinhood Chain and Pump.fun, filtered by liquidity, age,
  anti-rug checks and backtests; leaderboard of microcap projects scored on
  GitHub activity, website and tokenomics; optional automated pilot running
  trend-following strategies, long spot only, with hard limits
  ($20 per buy, $100 per day, market cap below $100k).
- **Team:** **[TBD]**.
- **Milestones:** phase 1 launch; phase 2 holder tiers; phase 3 new
  trend-following strategies, more chains, public track record.
- **Use of funds:** the offeror does not sell tokens for funds outside the
  public pool. SOL paired in the pool (40 SOL) is locked with the burned LP.

## Part E — Offer

| | |
|---|---|
| Type | Public offer by fair launch in a Raydium CPMM pool |
| Tokens offered | 450,000,000 (45%) |
| Initial pool | 450,000,000 ENGN + 40 SOL, LP burned |
| Price | Set by the pool curve, no fixed price, no presale |
| Start | **[TBD]**, at least 20 working days after notification |
| Maximum subscription | None; any wallet may buy from the pool |
| Withdrawal right (art. 13) | Not applicable to purchases from a decentralised pool with no counterparty acting for the offeror; **[legal review]** |
| Excluded jurisdictions | United States and where prohibited |

## Part F — The crypto-asset

- Standard SPL token, 9 decimals, total supply 1,000,000,000.
- Mint authority and freeze authority revoked at creation; metadata
  immutable. No tax, no blacklist, no upgradeable program.
- Allocation and unlock:

| Share | % | Unlock |
|---|---|---|
| Fair launch liquidity | 45 | at launch, LP burned |
| Community and early app users | 15 | airdrop, 6-month linear |
| Ecosystem and strategy rewards | 15 | 36-month linear stream |
| Treasury (2-of-3 multisig) | 10 | 6-month cliff, then 24-month linear |
| Team | 10 | 12-month cliff, then 24-month linear |
| Listings and market making | 5 | locked until first listing |

## Part G — Rights and obligations

Holding thresholds unlock app features: Scout (no token), Sniper
(250,000 ENGN: real-time radar and alerts, full leaderboard), Engine
(1,000,000 ENGN: automated strategies, early access). Thresholds may be
revised by the offeror with 30 days' notice on the project page. No
dividend, interest, buyback or revenue right is attached. The offeror does
not undertake to support the price.

## Part H — Technology

Solana mainnet, SPL Token program. Vesting through a public on-chain
streaming protocol **[TBD provider]**, with stream links on the project
page. Access tiers read the balance of the wallet linked to the app.

## Part I — Risks

- **Market:** very high volatility; the token can go to zero. Low initial
  liquidity amplifies price moves.
- **Product:** the scanner and strategies have no demonstrated edge;
  backtests on real series show results indistinguishable from random
  walks on several pairs. Automated trading can lose money.
- **Custody:** app keys are encrypted and held on the server; a compromise
  of the server could expose them.
- **Technology:** Solana outages, AMM exploits, wallet phishing, fake
  tokens using the same ticker. The only valid address is the one published
  on the project page.
- **Regulatory:** rules on crypto-assets may change and restrict the token
  or the app.
- **Project:** development may stop; the token has no value without the app.

## Part J — Sustainability indicators

Solana uses proof of stake with proof of history. Energy consumption of the
consensus mechanism and the indicators required by the MiCA regulatory
technical standards on sustainability: **[TBD, source data from the Solana Foundation or a
recognised provider]**.
