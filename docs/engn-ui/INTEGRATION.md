# ENGN UI — implementation contract

This is implementation code, not a moodboard. Lorenzo explicitly requested that Claude integrate the delivered code as-is and reproduce the preview exactly. Do not regenerate the UI from this document or substitute a different component library.

## Visual fidelity

LATEST SCOPE: desktop only. Lorenzo explicitly froze mobile. New stylesheets are gated at min-width:1100px; preserve this gate. Do not apply the earlier mobile concept. Scout naming and truthful loading feedback remain shared product behavior. Verify mobile against the original baseline before merging.

Reference: [desktop preview with synthetic data](desktop-reference.png).

Preserve the delivered layout, spacing, typography, palette, borders, cube proportions, motion timing and responsive behavior. Keep stylesheet order: existing app.css, engn-system.css, ui.css, ui-refinements.css. Landing uses engn-system.css then engn-landing.css. The source files are authoritative; screenshots are supplementary references with synthetic data.

Any proposed visual deviation requires Lorenzo's approval. A technical integration adjustment must not change the appearance or existing financial behavior. Check the desktop at 1440 × 1000 and the chosen mobile behavior at 390 × 844. Do not use a narrow browser panel to judge the desktop version.

## Design decisions

- Restrained dark green workspace, mint accents, serif headings and compact data typography.
- Desktop sidebar and adjacent research detail pane; preserve existing routing and DOM hooks.
- Compact leaderboard symbols, thin neon slit and subtle 3px float. Real names and scores lead the hierarchy.
- Scout is the product-facing agent identity. DeepSeek can remain the technical provider and internal identifier.
- Preserve reduced-motion behavior and visible keyboard focus.

## Integration boundaries

Preserve all data sources, token registration, rank ordering, navigation IDs, forms, wallet actions, authentication and transaction logic. Do not copy synthetic preview fixtures into production. The local preview rejects all mutation requests and does not prove trading or wallet flows work against the backend.

Backend changes only add asset hashing/versioned URLs, including the new stylesheets. Avoid replacing this with unversioned assets, which can leave returning users on stale CSS.

## Acceptance

Compare landing, Memes, Gems Top and Database, Strategies, Scout, Profile, detail and dialogs. Check text wrapping, sidebar/dock placement, focus visibility and horizontal overflow. Confirm production data and authenticated flows in staging before merge; never execute a financial transaction simply to verify a visual change.

This branch does not authorize automatic deployment. The existing main branch deploys on merge, so review and validate first.
