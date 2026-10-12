# Opensource UI — design catalogue for a vanilla JS/CSS port

- **Source:** https://github.com/bidyut10/opensourceui (live site: opensourceui.in/components), by Bidyut Kundu
- **License:** MIT — free for personal and commercial use. Attribution appreciated: keep a credit line such as "Some UI patterns adapted from Opensource UI by Bidyut Kundu (MIT)" near any ported code, and keep the MIT notice if you copy substantial portions.
- **Catalogued:** 2026-10-12, from a local clone. 210 `.tsx` files under `components/` in 32 top-level folders (209 components + 1 icon helper file, `docks/Icons.tsx`). Root `PRODUCT.md` and `AGENTS.md` were read; there is no root `DESIGN.md` — its role is played by `skills/opensource-ui/references/design.md`, which was read as well, together with `app/globals.css` and `lib/cn.ts`.
- **Stack of the original:** Next.js 16, React 19, Tailwind CSS v4 (`@import "tailwindcss"`, `@theme`, `starting:` variant), `lucide-react` icons, `next/image`, `next/link`. **No Framer Motion or other animation library anywhere.** All motion is CSS transitions, Tailwind `animate-*` keyframes, two inline `<style>` keyframes, one Web Animations API call and a few `requestAnimationFrame` timers.

## How to read this file

1. **Design language**: the tokens that recur across the library (colours, type, radii, borders, shadows, backgrounds, glass, motion), already translated from Tailwind to plain CSS.
2. **Styles**: the 210 files grouped into 10 visual families. Each has a short description, a `:root` block of custom properties you can paste, and its member list.
3. **Component index**: one entry per file, grouped by source folder: `file name — what it is · style family · ★ if relevant to a mobile crypto/trading dashboard`, followed by the 1–3 distinctive techniques with exact values. Folder intros state what all files in that folder share, so entries list only what differs.
4. **Porting notes**: Tailwind → CSS translation table, dependencies, state/JS patterns, accessibility patterns worth keeping.

Conventions: colours are given as the hex values Tailwind v4's palette approximates (`neutral-900` = `#171717`); Tailwind v4 actually emits `oklch()`, but the hex values are visually identical. `★` marks components most relevant to a mobile trading dashboard (tables, wallet, buttons, inputs, dropdowns, notifications, loaders, docks, widgets, backgrounds, text effects, underlines). Spacing is Tailwind's 4px grid (`p-4` = 16px, `size-44` = 176px). "Tailwind `x`" quotes the original utility where it helps you find it in the source.

Caution: many demo components imitate real brands (Apple iOS banners and widgets, Google Calendar, Vercel, Stripe, X/Twitter, LinkedIn, Instagram, Facebook, Threads, Discord, GitHub, Adobe/Spotify icons). Port the layout and techniques, not the logos, names or trade dress.

---

## 1. Design language

The library's own brief (`skills/opensource-ui/references/design.md`, `PRODUCT.md`) says: neutral stage, ink on paper, Instrument Serif + Geist, flat by default, focus shown by border colour and never by rings, no purple, no glow, no glassmorphism, base + `md:` breakpoints only, WCAG AA, respect `prefers-reduced-motion`. The **site chrome** follows that brief strictly. The **components** are demos and are looser: they use glass, glows, gradients and (rarely) violet. What follows is what the components actually do.

### 1.1 Palettes

**Neutral ink scale (the backbone; Tailwind `neutral`).** Used by about 85% of components for text, borders and fills.

| token | hex | typical use |
|---|---|---|
| neutral-950 | `#0a0a0a` | darkest surface (player, menu board), strongest heading |
| neutral-900 | `#171717` | primary text, selected day/option, focus border, dark key |
| neutral-800 | `#262626` | primary button fill, dark borders on dark cards |
| neutral-700 | `#404040` | body text on light, secondary dark fill |
| neutral-600 | `#525252` | secondary text |
| neutral-500 | `#737373` | muted text, hints, `<th>` |
| neutral-400 | `#a3a3a3` | placeholders, meta, timestamps, eyebrow labels |
| neutral-300 | `#d4d4d4` | disabled text, idle icons, dashed rules |
| neutral-200 | `#e5e5e5` | default input / table border |
| neutral-100 | `#f5f5f5` | hairline card border, row dividers, tray fill |
| neutral-50 | `#fafafa` | hover row, recessed fill, light key face |
| white | `#ffffff` | card surface |

**Carbon / midnight dark bases** (backgrounds, dark cards and widgets):
`#050505` (deepest vignette stop), `#080808`, `#0A0B0E`, `#0A0C0F`, `#0A0D10`, `#0B0B0B`, `#0C0C0C` (pomodoro, carbon spotlight), `#0D0D0D` (terminal), `#0E0A0B` (rose noir), `#100C0A` (ember), `#061014` (teal depth), `#101218`, `#12151A`, `#141414`, `#1C1C1C` (spotlight centre), `#1C1C1E` (iOS dark label, mascot eyes), `#000000` (mascot face tiles, device bezels).
Typical dark ramp: `#1C1C1C → #121212 → #0C0C0C → #050505` (radial, centre top).

**Paper / cream light bases** (editorial cards and warm backgrounds):
`#FFFFFF`, `#FFFEFB`, `#FFFEF9` (document), `#FFFEF8` (postcard), `#FFFDF7`, `#FFFDF5`, `#FFFDF0` (notepad), `#FFFCF7`, `#FFFBF9`, `#FFFAF5`, `#FFF9F2`, `#FAF8F5` (placard), `#FAF8F2` (receipt), `#F7F4EF` (mat), `#F6F2EB` (editorial paper, used 4×), `#F4F4EA`, `#F8F6F1`, `#F7F3ED` (linen), `#F4EDE4` (sand), `#F3F0EA` (terrazzo), `#F2F2F2`, `#E8E6E1` (soft spotlight), `#4A2525` (oxblood editorial).
Warm greys for text on paper: stone `#57534E #78716C #A8A29E`, olive `#5C5A4A #A39E76 #E6E2BC`, sepia `#3D3530 #8A7E70 #A09080 #B0A595`.

**Accent families** (demo accents; each family appears in light pastel form for backgrounds and saturated form for state):
- Emerald / green (success, "added", positive, online): `#10b981` (emerald-500), `#059669` (600, done keys), `#047857` (700, text), `#34d399` (400, online dots), `#ecfdf5` (50); iOS `#34C759`; GitHub heat `#9be9a8 #40c463 #30a14e #216e39`.
- Teal / cyan / sky (aurora, ring gradients, info): `#2DD4BF #14B8A6 #0D9488 #0F766E`, `#22D3EE #06B6D4 #0891B2`, `#38BDF8 #0EA5E9 #0284C7`, pastels `#A5F3FC #99F6E4 #6EE7B7 #A7F3D0 #7DD3FC`. Signature ring gradient: `#14b8a6 → #06b6d4`.
- Rose / red (danger, like, delete, error): `#f43f5e` (rose-500), `#e11d48` (600), `#be123c` (700), `#fb7185` (400), `#fda4af` (300, error borders), `#fecdd3` (200), `#fff1f2` (50); red `#ef4444 #dc2626 #f87171 #fef2f2`; iOS `#FF3B30 #FF453A`.
- Amber / orange (saved, warning, ember, highlight): `#f59e0b #fbbf24 #fcd34d #fde68a #fffbeb #b45309 #d97706`, orange `#FB923C #F97316 #EA580C #FDBA74`, iOS `#FF9500`, tomato `#E85D4C`, dimple-switch on `#f3b519`.
- Lime / yellow (mascots, sticky note): `#A3E635 #BEF264 #E9FF95 #D4F84C #D9F26D #FACC15 #FDE047`.
- Blue (rare): `#2874F0`, `#2563eb → #0f766e` (wallet pass), `#5865F2` (Discord), `#6CA8FF` (recorder mascot).
- Violet (rare, against the house rule): `#A78BFA #C4B5FD` (DND mascot), purple-300/400 default for wavy annotations, `#9f93b8 #e2d9f3` (sticker).

### 1.2 Typography

- **Stacks:** sans `Geist, ui-sans-serif, system-ui, sans-serif` (176 uses of `font-sans`); mono `"Geist Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` (71 uses); serif `"Instrument Serif", ui-serif, Georgia, Cambria, "Times New Roman", Times, serif` (19 uses: editorial headings, captions in italic, the file-upload headline, OTP title). iOS-imitation widgets use `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", sans-serif`. Sticky note: `"Segoe Script","Bradley Hand","Snell Roundhand","Apple Chalkboard",cursive`.
- **Sizes:** the UI runs small. Arbitrary pixel sizes by frequency: 10px (117×), 11px (63×), 9px (39×), 13px (24×), 12px (19×), 8px (16×), 7px, 6px. Scale steps: 12px (`text-xs`) labels/meta, 14px (`text-sm`) body/inputs/titles, 16px, 18px, 24px (`text-2xl`) card numbers, 30px, 48px (`text-5xl`) hero stats, 72px (`text-7xl`) iOS date.
- **Weights:** 400 body; 500 labels, menu rows, keys; 600 titles, primary buttons; 700 a few stats/badges; **200–300 for big numerals** (`font-extralight`/`font-light`: countdown, steps, temperature, stopwatch, pomodoro, recorder) — the library's signature for numbers.
- **Letter-spacing:** tight `-.025em` (33×, headings and body), wide `.025em` (23×), wider `.05em` (11×), widest `.1em` (18×); eyebrow/mono labels go further: `.14em .15em .16em .18em .2em .22em .25em .28em .3em`. Big numerals: `-.03em` to `-.05em`.
- **Uppercase labels (the "eyebrow"):** `font: 500–600 10px/1 mono or sans; text-transform:uppercase; letter-spacing:.1em–.25em; color:#a3a3a3`. Used on almost every card, ticket, placard, receipt and widget.
- **Mono use:** timestamps, IDs (`#DS2026-0042`, `MBR-2048`), keyboard shortcuts in `<kbd>`, OTP digits, prices on receipts, terminal, URL bars, file-type chips, stat labels.
- **Numbers:** `font-variant-numeric: tabular-nums` on every changing number (counts, prices, timers, table amounts, calendar days).
- **Other:** `text-shadow:0 1px 0 rgba(255,255,255,.8)` letterpress on light keys; `-webkit-line-clamp:2/3` on notification bodies; `text-overflow:ellipsis` (`truncate`) everywhere in rows; `writing-mode:vertical-rl` for ticket stubs.

### 1.3 Radii

By frequency: `9999px` pills/circles (215×), `8px` (74×), `12px` (55×), `6px` (52×), `16px` (45×), `24px` (29×), `4px` (`rounded` + `rounded-sm`, 25×), `2px` (`rounded-xs` and arbitrary, a handful). Specials: `1.75rem` (28px, mascot/pomodoro tiles), `1.25rem` (20px, iOS notifications), `.625rem` (10px, iOS app tile), `18px` (cinder button), `22px` (iOS calendar), `2rem`/`3rem` (folder cards), `100%` (ellipse bands/dunes), organic blobs `42% 58% 64% 36%`, `58% 42% 38% 62%`, `36% 64% 58% 42%`, `60% 40% 55% 45% / 55% 45% 55% 45%`, petal `100% 100% 20% 100%`. Concentric radii are computed: inner = outer − padding (`calc(1.35rem - .625rem)`, `calc(.75rem - 1px)`).
Rule of thumb used by the library: controls 8px, keys 8–12px, menus/panels 12px, cards 16px, widget tiles 24px, forms 24px, pills 9999px; editorial/paper cards use 0–4px (square corners are part of the "print" look).

### 1.4 Borders

- Hairline card: `1px solid #f5f5f5` (white cards) or `#e5e5e5` (tables, inputs, editorial).
- Inputs: `1px solid #e5e5e5`, focus `#171717`, error `#fda4af`; OTP/switch tracks use `2px`.
- Dark cards: `1px solid #262626` (`neutral-800`).
- Glass: `1px solid rgba(255,255,255,.2)` (dock), `rgba(255,255,255,.25–.3)` (overlay panels), `rgba(255,255,255,.7)` (iOS banner).
- Dashed: perforations and rules `1px dashed #e5e5e5 / #d4d4d4 / #404040`; drop-zone `1px dashed #e5e5e5`; stamps `2px dashed #b4b1ac`; stitches `1px dashed rgba(196,184,170,.8)`.
- Accent stripe: `border-left:2px solid` for callouts (rose/emerald) and active sort option — despite the brief's "no side-stripe" rule.
- Double: sheen pill `1px double rgba(51,51,51,.08)`.
- Stamp: `2px solid #f43f5e` rotated `-12deg`.
- Neo-brutal: `1px solid #171717` with a solid offset shadow.

### 1.5 Shadow recipes (plain CSS)

Tailwind defaults used (v4 values):
```css
--shadow-xs: 0 1px 2px 0 rgba(0,0,0,.05);
--shadow-sm: 0 1px 3px 0 rgba(0,0,0,.1), 0 1px 2px -1px rgba(0,0,0,.1);
--shadow-md: 0 4px 6px -1px rgba(0,0,0,.1), 0 2px 4px -2px rgba(0,0,0,.1);
--shadow-lg: 0 10px 15px -3px rgba(0,0,0,.1), 0 4px 6px -4px rgba(0,0,0,.1);
--shadow-lg-5: 0 10px 15px -3px rgba(0,0,0,.05), 0 4px 6px -4px rgba(0,0,0,.05); /* shadow-lg shadow-black/5 — the default card/widget shadow */
--shadow-xl-10: 0 20px 25px -5px rgba(0,0,0,.1), 0 8px 10px -6px rgba(0,0,0,.1);  /* shadow-xl shadow-black/10 — docks, spotlight */
--shadow-2xl: 0 25px 50px -12px rgba(0,0,0,.25);
--shadow-2xl-40: 0 25px 50px -12px rgba(0,0,0,.4);                              /* terminal */
```

Library-specific recipes (exact, multi-layer):
```css
/* Raised light key (bookmark, download, follow, like) */
--key-light: 0 0 0 1px rgba(0,0,0,.06), 0 1px 1px rgba(0,0,0,.1), 0 2px 4px rgba(0,0,0,.08),
             inset 0 1px 2px rgba(255,255,255,.4), inset 0 -2px 4px rgba(0,0,0,.08);
--key-light-pressed: 0 0 0 1px rgba(0,0,0,.06), 0 1px 1px rgba(0,0,0,.06),
             inset 0 1px 2px rgba(0,0,0,.08), inset 0 2px 4px rgba(0,0,0,.04), inset 0 -1px 2px rgba(0,0,0,.05);
/* Universal 3D button, light face (three-d-button) */
--bevel-light: 0 1px 1px rgba(0,0,0,.08), 0 2px 4px rgba(0,0,0,.1), 0 6px 12px rgba(0,0,0,.08),
             inset 0 1px 2px rgba(255,255,255,.35), inset 0 -2px 4px rgba(0,0,0,.08);
--bevel-light-pressed: 0 1px 1px rgba(0,0,0,.05), inset 0 1px 2px rgba(0,0,0,.08),
             inset 0 2px 4px rgba(0,0,0,.04), inset 0 -1px 2px rgba(0,0,0,.05);
/* Dark 3D key (#262626 / #171717 face) */
--key-dark: 0 1px 1px rgba(0,0,0,.35), 0 3px 6px rgba(0,0,0,.28), 0 8px 16px rgba(0,0,0,.22),
             inset 0 1px 2px rgba(255,255,255,.14), inset 0 -3px 6px rgba(0,0,0,.55);
--key-dark-pressed: 0 1px 2px rgba(0,0,0,.25), inset 0 2px 6px rgba(0,0,0,.55), inset 0 -1px 1px rgba(255,255,255,.06);
/* Emerald success key (#059669 face) */
--key-success: 0 1px 1px rgba(0,0,0,.2), 0 3px 6px rgba(0,0,0,.18), 0 8px 16px rgba(0,0,0,.14),
             inset 0 1px 2px rgba(255,255,255,.2), inset 0 -3px 6px rgba(0,0,0,.35);
/* Keycap with side bevels (quantity stepper keys) */
--keycap: 0 1px 1px rgba(0,0,0,.12), 0 2px 3px rgba(0,0,0,.1), 0 4px 8px rgba(0,0,0,.06),
             inset 0 1px 0 rgba(255,255,255,.55), inset 0 -2px 3px rgba(0,0,0,.1),
             inset 1px 0 1px rgba(255,255,255,.25), inset -1px 0 1px rgba(255,255,255,.25);
/* Knob sitting in a groove (slide-to-confirm) */
--knob: 0 1px 1px rgba(0,0,0,.12), 0 2px 3px rgba(0,0,0,.12), inset 0 1.5px 0 #fff, inset 0 -2px 3px rgba(0,0,0,.1);
/* Recessed tray (segmented control, stepper, slide track) */
--tray-inset: inset 0 1px 2px rgba(0,0,0,.08), inset 0 2px 4px rgba(0,0,0,.05),
             inset 0 -2px 3px rgba(0,0,0,.06), 0 1px 0 rgba(255,255,255,.9);
/* Pill riding in the tray */
--tray-pill: 0 2px 4px rgba(0,0,0,.15), 0 1px 1px rgba(0,0,0,.08), inset 0 1px 0 rgba(255,255,255,.95), inset 0 -2px 3px rgba(0,0,0,.06);
/* Pressed-in button */
--inset-light: inset 0 2px 4px rgba(0,0,0,.1), inset 0 -1px 1px rgba(255,255,255,.7);
--inset-dark:  inset 0 2px 5px rgba(0,0,0,.55), inset 0 -1px 1px rgba(255,255,255,.08);
/* Neumorphic (on #f5f5f5) */
--neu-raised: 6px 6px 14px rgba(0,0,0,.08), -6px -6px 14px rgba(255,255,255,.9);
--neu-pressed: inset 4px 4px 10px rgba(0,0,0,.08), inset -4px -4px 10px rgba(255,255,255,.85);
/* Floating outline CTA (depth-outline-button) */
--float-outline: 0 0 0 1px rgba(0,0,0,.06), 0 1px 1px rgba(0,0,0,.04), 0 4px 10px rgba(0,0,0,.05),
             0 12px 28px rgba(0,0,0,.05), inset 0 1px 1px rgba(255,255,255,.75), inset 0 -1px 2px rgba(0,0,0,.04);
--float-pill: 0 2px 4px rgba(0,0,0,.06), 0 8px 20px rgba(0,0,0,.08);
--float-pill-dark: 0 2px 4px rgba(0,0,0,.2), 0 8px 20px rgba(0,0,0,.25);
/* Layered card stack (calendars) */
--card-stack: 0 0 0 1px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.05), 0 4px 8px rgba(0,0,0,.06), 0 12px 24px rgba(0,0,0,.04);
/* Menus and popovers */
--menu: 0 20px 50px -12px rgba(0,0,0,.05);
--menu-select: 0 8px 24px -8px rgba(0,0,0,.1);
--menu-inline-open: 0 12px 32px -12px rgba(0,0,0,.1);
/* iOS banner / toast */
--banner: 0 8px 32px -4px rgba(0,0,0,.10);
--toast: 0 4px 24px -2px rgba(0,0,0,.10), 0 0 0 1px rgba(0,0,0,.02);
/* Paper objects */
--polaroid: 0 8px 30px rgba(0,0,0,.12);
--photo-lift: 0 1px 2px rgba(15,23,42,.05), 0 10px 24px rgba(15,23,42,.12), 0 22px 48px -6px rgba(15,23,42,.1);
--frame-wall: 0 16px 34px rgba(15,23,42,.12);
--stack-front: 0 20px 44px -14px rgba(0,0,0,.38);
/* Hard offset (neo-brutal) */
--hard: 4px 4px 0 0 #171717;          /* hard-shadow polaroid, offset is a prop */
--hard-paper: 5px 5px 0 #e6e2bc;      /* notepad; postcard uses 4px 4px 0 #e8e0d0 */
/* Glossy dark buttons */
--cinder: 0 1px 0 rgba(255,255,255,.14), 0 12px 28px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.12);
--linen: 0 1px 0 rgba(255,255,255,.85), 0 6px 14px rgba(120,113,108,.16), inset 0 1px 0 rgba(255,255,255,.65);
/* Glass pill bevel (sheen-pill-button) */
--sheen: inset 2px -2px 1px -1px rgba(255,255,255,.9), inset -2px 2px 1px -1px rgba(255,255,255,.9),
         inset 6px -6px 1px -6px rgba(255,255,255,.55), inset -6px 6px 1px -6px rgba(255,255,255,.55),
         inset 0 0 2px rgba(0,0,0,.8), 0 4px 8px rgba(0,0,0,.2);
/* Coloured glow under round action buttons (stopwatch) */
--glow-green: 0 2px 8px rgba(52,199,89,.28);
--glow-orange: 0 2px 8px rgba(255,149,0,.28);
--glow-red: 0 2px 8px rgba(255,59,48,.25);
/* Neon orb (text-loader, default scheme; cycled with WAAPI) */
--orb-1: inset 0 1px 1px 0 #fff, inset 0 3px 5px 0 #ff5f9f, inset 0 4px 4px 0 #0693ff;
--orb-2: inset 0 1px 1px 0 #fff, inset 0 3px 5px 0 #d60a47, inset 0 4px 4px 0 #fbef19;
--orb-3: inset 0 1px 1px 0 #fff, inset 0 3px 5px 0 #ff5f9f, inset 0 4px 4px 0 #28a9ff;
```
Glyph shadows on icons inside keys: `filter: drop-shadow(0 1px 1px rgba(0,0,0,.22)) drop-shadow(0 2px 3px rgba(0,0,0,.12))`; coloured when active (amber `rgba(245,158,11,.35)/.2`, rose `rgba(244,63,94,.35)/.2`, emerald `rgba(4,120,87,.3)/.15`). Embossed icon in a groove: `drop-shadow(0 1px 0 rgba(255,255,255,.9)) drop-shadow(0 -1px .5px rgba(0,0,0,.12))`.

### 1.6 Background recipes

All are absolutely positioned, `pointer-events:none`, `z-index:-1` layers inside a `position:relative; isolation:isolate; overflow:hidden` parent. Full per-file values are in the index (§3, background-gradient / background-pattern); the reusable building blocks:

```css
/* Grain (closing layer on 23 of 26 gradient backgrounds; not halftone-pop, linen-weave, paper-fold) */
.grain { background-image: radial-gradient(circle at center, #000 1px, transparent 1px); background-size: 4px 4px; opacity: .03; }
/* dark version */  /* radial-gradient(circle at center, rgba(255,255,255,.7) 1px, transparent 1px) 4px; opacity:.03–.04 */

/* Vignette */
.vignette { background-image: radial-gradient(circle at center, transparent 42%, rgba(0,0,0,.55) 100%); }

/* Carbon spotlight (dark) */
.bg-carbon {
  background:
    radial-gradient(circle at 50% 0%, rgba(255,255,255,.07) 0%, transparent 46%),   /* .14 at opacity .5 */
    radial-gradient(circle at 50% 12%, #1C1C1C 0%, #121212 36%, #0C0C0C 68%, #050505 100%);
}

/* Aurora (light or dark): a blurred wrapper of blurred blobs */
.aurora { position:absolute; inset:-24px; filter:blur(24px); }
.aurora > i { position:absolute; border-radius:50%; filter:blur(64px); }
/* light: #E9FF95 .8 / #59E39C .7 / #1EC9D8 .65 / #2874F0 .55 on #FFFEFB
   dark:  #2DD4BF .22 / #22D3EE .18 / #34D399 .16 / #38BDF8 .14 on #0A0C0F */

/* Mesh grid (dark midnight) */
.mesh {
  background-image: linear-gradient(to right, rgba(148,163,184,.10) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(148,163,184,.10) 1px, transparent 1px);
  background-size: 28px 28px; opacity: .14;
}

/* Arc bands rising from the bottom edge */
.arc { position:absolute; bottom:-28%; left:50%; width:150%; height:92%; transform:translateX(-50%); border-radius:100%;
  background: radial-gradient(ellipse 120% 88% at 50% 100%, rgba(56,189,248,.52) 0%, rgba(45,212,191,.44) 18%,
              rgba(245,158,11,.38) 40%, rgba(244,63,94,.30) 62%, rgba(255,252,247,0) 82%); }

/* Halftone dot field */
.halftone { background-image: radial-gradient(circle, #FB7185 1.2px, transparent 1.2px); background-size: 7px 7px; opacity: .35; }

/* Graph paper / dots / hatch / ruled lines (background-pattern) */
.graph  { background: #fff linear-gradient(to right, rgba(0,0,0,.05) 1px, transparent 1px) 0 0/20px 20px,
                      linear-gradient(to bottom, rgba(0,0,0,.05) 1px, transparent 1px) 0 0/20px 20px; }
.dots   { background: #fafafa radial-gradient(circle, #e8e8e8 1px, transparent 1px) 0 0/12px 12px; }
.hatch  { background: #fff repeating-linear-gradient(45deg, #f5f5f5 0, #f5f5f5 1px, transparent 0, transparent 50%) 0 0/12px 12px; }
.ruled  { background-image: repeating-linear-gradient(to bottom, transparent 0, transparent 21px, rgba(0,0,0,.07) 21px, rgba(0,0,0,.07) 22px); }

/* Paper fold crease */
.fold { background: linear-gradient(128deg, transparent 42%, rgba(120,113,108,.10) 49.5%, rgba(255,255,255,.55) 50.5%, transparent 58%); }

/* Scalloped / perforated edge (receipt, circle-cut frame) — an 8px strip outside the box */
.scallop-top { height:8px; background: radial-gradient(circle at 8px 0, transparent 6px, #faf8f2 6px) 0 0/16px 8px; }
```

Image scrims: `linear-gradient(to top, rgba(0,0,0,.8), rgba(0,0,0,.2), transparent)` (magazine cover, team card); player cover `linear-gradient(to top, #0a0a0a, rgba(10,10,10,.4), transparent)`.

### 1.7 Glass / frosted recipes

| where | background | border | backdrop-filter | shadow |
|---|---|---|---|---|
| Dock shell (mac/app dock) | `rgba(255,255,255,.10)` | `1px rgba(255,255,255,.2)` | `blur(12px)` | `--shadow-xl-10` |
| Dock on light page (editor/presence/spotlight) | `rgba(255,255,255,.5)` | `1px #fafafa` | `blur(12px)` | `--shadow-xl-10` |
| Dock tile | `rgba(255,255,255,.5)` | `1px rgba(255,255,255,.2)` | `blur(24px)` | `0 1px 2px rgba(0,0,0,.05)` |
| Frosted dropdown under a dock | `rgba(255,255,255,.9)` | `1px #fafafa` | `blur(12px)` | `--shadow-xl-10` |
| iOS notification banner | `rgba(255,255,255,.9)` | `1px rgba(255,255,255,.7)` | `blur(24px)` | `0 8px 32px -4px rgba(0,0,0,.1)` |
| Toast | `rgba(255,255,255,.95)` | `1px rgba(229,229,229,.8)` | `blur(24px)` | `--toast` |
| Info panel over a photo | `rgba(255,255,255,.15)` | `1px rgba(255,255,255,.25)` | `blur(24px)` | — |
| Round icon button over a photo | `rgba(255,255,255,.2)` (hover `.3`) | `1px rgba(255,255,255,.3)` | `blur(12px)` | — |
| Badge pill over a photo | `rgba(255,255,255,.15)` | `1px rgba(255,255,255,.2)` | `blur(12px)` | — |
| Browser mockup "glass" theme | `rgba(255,255,255,.4)` chrome | `1px rgba(212,212,212,.5)` | `blur(8px)` | — |
| Sheen pill | `rgba(255,255,255,.08)` + `filter:brightness(1.05)` | `1px double rgba(51,51,51,.08)` | `blur(5px)` | `--sheen` |

Tailwind blur scale for reference: `blur-sm` 8px, `blur-md` 12px, `blur-lg` 16px, `blur-xl` 24px, `blur-2xl` 40px, `blur-3xl` 64px (same values for `backdrop-blur-*`).

### 1.8 Motion

- **Durations** by frequency: 200ms (77×), 300ms (66×), 150ms (24×), 500ms (19×), then 340/280/260ms (iOS banner enter/exit), 700ms (image zoom, flips, ring), 250ms, 400ms, 1000ms (timer ring), 4000ms (breathing).
- **Easings:** `ease-out` (51×); `cubic-bezier(.25,.46,.45,.94)` "ease-out-quad" for content entering (18×); `cubic-bezier(.32,.72,0,1)` iOS-sheet curve for all button state changes (16×); `--ease-smooth: cubic-bezier(.22,1,.36,1)` (house token, docks, segmented slide, menus, 17× incl. arbitrary); `cubic-bezier(.4,0,.6,1)` for exits (9×); spring `cubic-bezier(.34,1.56,.64,1)` for icon pops; soft spring `cubic-bezier(.34,1.2,.64,1)` for the wallet flip; `linear` for hold-to-delete fill and timer rings.
- **Hover lifts:** dock icon `translateY(-8px) scale(1.25)` with `transform-origin:bottom`; dock/tool tiles `scale(1.1)`; presence pill `scale(1.02)`; card front `translateY(-4px)`; images `scale(1.05)` (500ms) or `scale(1.1)` (700ms) inside `overflow:hidden`; play buttons `scale(1.05)`; prism button `scale(1.02)` / active `scale(.98)`; keys `active: translateY(1px)`; calendar cells and widget buttons `active: scale(.95)`; tooltips rise 2px while fading in.
- **Enter animations without JS:** CSS `@starting-style` (Tailwind `starting:`) — e.g. menus `opacity:0; transform:translateY(-4px) scale(.96); filter:blur(3px)` → normal over 300ms `cubic-bezier(.22,1,.36,1)`; re-keying an element (new `key`) replays it (calendar month change, countdown digits).
- **State machine via data attributes:** notifications use `data-phase="open|closing|closed"` and style `[data-phase=closing]{transform:translateY(-8px);opacity:0;transition-duration:260ms}`, then unmount on a timer equal to the exit duration.
- **Crossfade label swap:** stack labels in one grid cell, outgoing `opacity 0` in 200ms, incoming `opacity 1` in 300ms with 200ms delay.
- **Keyframes in use:** Tailwind `spin` (9×), `pulse` (13×: skeletons, cursors, letter waves), `ping` (1×, autosave dot); inline `testimonial-fade` (`from{opacity:0;transform:translateY(6px)}`), `wallet-flip-shadow` (box-shadow breathing 3s); globals.css `caret-blink`, `wave-hand` (rotate −12deg), `showcase-fade-in` (translateY(3px)), `watch-ring-draw-*` (stroke-dasharray 0→N), `showcase-progress` (scaleX .12→.96), `showcase-art-zoom` (scale 1.07), `ipod-bar` (scaleY .28→1), `code-panel-shift` (background-position 0%→100%).
- **Reduced motion:** 28 of 210 files include explicit `motion-reduce:` / `motion-safe:` / `matchMedia('(prefers-reduced-motion: reduce)')` handling — 19 of the 22 buttons (not like, quantity-stepper, slide-to-confirm), the loaders (apple-hello stops cycling, text-loader freezes the orb, spinners stop), frames (skeleton pulse only under `motion-safe`), copy-email. The rest (dropdown entries, notifications, widgets, wallet flip, testimonial) do not guard; add a global rule when porting:
  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important;
                             transition-duration: .01ms !important; scroll-behavior: auto !important; }
  }
  ```

### 1.9 Focus, states, density

- Focus: `outline: 2px solid #171717; outline-offset: 2px` on `:focus-visible` for buttons (amber `#fcd34d`/`#d97706` or sky on themed buttons, rose `#e11d48` on destructive); inputs never use rings — `border-color:#171717` on `:focus`. Custom controls built on a hidden real input use `:has(:focus-visible)` on the wrapper.
- Disabled: `opacity:.4` (buttons) / `.5–.6`; inputs `background:#fafafa; color:#a3a3a3; cursor:not-allowed`.
- Error: border `#fda4af`, text `#e11d48` 12px, tinted fill `rgba(255,241,242,.4)`.
- Density: rows 32–40px, inputs 40px (44px in forms), keys 40px (36/48 for sm/lg), icon buttons 28–40px, widget tiles 176px, cards 256–384px wide.
- Responsive: base (mobile) + `md:` (≥768px) only; tables hide secondary columns below 768px; one custom 500px breakpoint in resource-links-panel.

---

## 2. Styles

Ten visual families. Each block is a starting palette for a scope class (`.theme-carbon { … }`) or for `:root`. Values are taken from the member components; where members differ, the most common value is used and alternatives are noted. Membership counts add up to 210.

### 2.1 Carbon spotlight dark (20)

Near-black surfaces with a soft top spotlight, a vignette and a faint white grain; content in white / 40–60% white; one accent (emerald, amber, tomato or teal) used sparingly; mono for times and IDs; big numerals light-weight. The most natural base for a dark trading dashboard: `dark-carbon-spotlight-background` or `dark-midnight-mesh-background` behind `#0a0a0a`/`#171717` cards.

```css
:root {
  --bg: #0c0c0c;
  --bg-gradient: radial-gradient(circle at 50% 12%, #1c1c1c 0%, #121212 36%, #0c0c0c 68%, #050505 100%);
  --bg-spot: radial-gradient(circle at 50% 0%, rgba(255,255,255,.14) 0%, transparent 46%); /* layer at opacity .5 */
  --bg-vignette: radial-gradient(circle at center, transparent 42%, rgba(0,0,0,.55) 100%);
  --grain: radial-gradient(circle at center, rgba(255,255,255,.7) 1px, transparent 1px) 0 0 / 4px 4px; /* opacity .03 */
  --mesh: linear-gradient(to right, rgba(148,163,184,.10) 1px, transparent 1px) 0 0 / 28px 28px,
          linear-gradient(to bottom, rgba(148,163,184,.10) 1px, transparent 1px) 0 0 / 28px 28px; /* opacity .14 */
  --surface: #0a0a0a;          /* player, menu board, cinema ticket */
  --surface-2: #171717;        /* widgets, stubs */
  --surface-3: #262626;        /* tracks, chips, borders */
  --border: #262626;
  --border-soft: rgba(38,38,38,.8);
  --text: #ffffff;
  --text-2: #d4d4d4;
  --text-muted: #737373;
  --text-faint: #525252;
  --text-dim: rgba(255,255,255,.4);
  --accent: #10b981;           /* progress, cmd prompt #34d399 */
  --accent-warm: #fcd34d;      /* prices, seats #fbbf24 */
  --accent-alert: #ef4444;     /* record, live */
  --accent-tomato: #e85d4c;    /* pomodoro ring */
  --accent-info: #38bdf8;      /* terminal ok lines */
  --radius-card: 16px;         /* widgets 24px, menu board 24px */
  --shadow-card: 0 10px 15px -3px rgba(0,0,0,.1), 0 4px 6px -4px rgba(0,0,0,.1);
  --shadow-deep: 0 18px 40px rgba(0,0,0,.28);
  --font-mono: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
```

Members: `background-gradient/dark-arc-bands-background.tsx`, `background-gradient/dark-aurora-background.tsx`, `background-gradient/dark-carbon-spotlight-background.tsx`, `background-gradient/dark-ember-background.tsx`, `background-gradient/dark-ink-field-background.tsx`, `background-gradient/dark-midnight-mesh-background.tsx`, `background-gradient/dark-rose-noir-background.tsx`, `background-gradient/dark-teal-depth-background.tsx`, `audio/music-player-card.tsx`, `audio/now-playing-bar.tsx`, `folder/opensource-folder-tab-card.tsx`, `gallery/film-strip-card.tsx`, `loaders/apple-hello-loader.tsx`, `others/terminal-log-card.tsx`, `text/cafe-menu-board-card.tsx`, `text/cinema-ticket-card.tsx`, `widgets/audio-recorder-widget.tsx`, `widgets/daily-activity-calendar-widget.tsx`, `widgets/flight-arrival-widget.tsx`, `widgets/pomodoro-widget.tsx`

### 2.2 Carbon dark luxe (5)

Glossy black and metal: stacked gradients for a lacquered face, an inner top highlight, a coloured light source (ember, cyan flare, teal glow) bleeding from one edge. For hero CTAs and premium cards (balance card), not for dense UI.

```css
:root {
  --shell: linear-gradient(180deg, #3a3a3a 0%, #1d1d1d 48%, #101010 100%);
  --face-sheen: linear-gradient(180deg, rgba(255,255,255,.1) 0%, rgba(255,255,255,.02) 28%, rgba(0,0,0,.2) 100%);
  --ember: radial-gradient(circle 70px at 50% 115%, rgba(251,146,60,.55), rgba(225,29,72,.22), transparent 72%);
  --prism-shell: radial-gradient(circle 80px at 80% -10%, #ffffff, #181b1b);
  --prism-core: radial-gradient(circle 80px at 80% -50%, #777777, #0f1111);
  --prism-flare: radial-gradient(circle 60px at 0% 100%, #3fe9ff, #0000ff80, transparent);
  --card-dark: linear-gradient(to bottom right, #262626, #171717, #000);
  --glow-teal: rgba(20,184,166,.3);   /* 160px circle, filter: blur(50px) */
  --glow-cyan: rgba(6,182,212,.2);    /* 192px circle, filter: blur(60px) */
  --chip-gold: linear-gradient(to bottom right, #fcd34d, #f59e0b);
  --text: #f5f5f5;
  --text-label: rgba(255,255,255,.3);
  --shadow: 0 1px 0 rgba(255,255,255,.14), 0 12px 28px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.12);
  --radius: 18px;                     /* prism 16px outer / 14px core */
  --focus: #fcd34d;
}
```

Members: `buttons/cinder-latch-button.tsx`, `buttons/prism-depth-button.tsx`, `loaders/text-loader.tsx`, `mockups/apple-watch-mockup-card.tsx`, `users/credit-card-glass.tsx`

### 2.3 Mascot face tiles (8)

Black 176px tiles with a 28px radius and a cartoon face (big coloured circle peeking up from the bottom, two dots for eyes) under a thin dial; each function owns one colour pair. Playful, readable at a glance; a good template for single-metric gauges (fear/greed, RSI, funding) on mobile.

```css
:root {
  --tile-bg: #000;
  --tile-size: 176px;
  --tile-radius: 1.75rem;
  --tile-shadow: 0 10px 15px -3px rgba(0,0,0,.05), 0 4px 6px -4px rgba(0,0,0,.05);
  --eye: #1c1c1e;
  --text: #ffffff;
  --text-off: rgba(255,255,255,.4);          /* #FFFFFF66 icons when off */
  --text-meta: rgba(255,255,255,.45);
  --dial-r: 56;                               /* SVG units, centre 88,84 */
  /* mascot / accent pairs */
  --battery: #a3e635;  --battery-low: #fb923c;
  --bluetooth: #14b8a6; --bluetooth-accent: #22d3ee;
  --dnd: #a78bfa;      --dnd-accent: #c4b5fd;
  --heart: #fb7185;    --heart-accent: #fda4af;
  --recorder: #6ca8ff; --recorder-accent: #ff453a;
  --sleep: #38bdf8;    --sleep-accent: #7dd3fc;
  --torch: #facc15;    --torch-accent: #fde047;
  --status-ok: rgba(52,199,89,.5);
}
```

Members: `widgets/battery-face-widget.tsx`, `widgets/bluetooth-face-widget.tsx`, `widgets/compass-widget.tsx`, `widgets/dnd-face-widget.tsx`, `widgets/heart-rate-widget.tsx`, `widgets/recorder-face-widget.tsx`, `widgets/sleep-score-widget.tsx`, `widgets/torch-face-widget.tsx`

### 2.4 Tactile 3D keys / soft UI (19)

Physical keycaps: light faces `#fafafa`/`#f5f5f5` or dark `#262626`/`#171717`, multi-layer outer drop shadows plus inset top highlight and inset bottom shade; pressing swaps to inset shadows (the key sinks); recessed trays hold sliding pills and knobs. State changes in 200–300ms on the iOS curve; labels crossfade; icons carry their own drop-shadow. The richest and most portable family — directly usable for dashboard buttons, segmented timeframe pickers, steppers and confirm sliders.

```css
:root {
  --key-face: #fafafa;
  --key-face-pressed: #f5f5f5;
  --key-face-dark: #262626;     /* hover #404040, active #171717 */
  --key-text: #404040;          /* hover #171717 */
  --key-success: #059669;
  --key-danger: #e11d48;
  --key-saved-bg: #fffbeb;  --key-saved-text: #b45309;  --key-saved-icon: #f59e0b;
  --key-liked-bg: #fff1f2;  --key-liked-text: #e11d48;  --key-liked-icon: #f43f5e;
  --tray: #f5f5f5;
  --tray-pill: #ffffff;
  --radius-key: 8px;            /* lg keys 12px, pills 9999px */
  --h-sm: 36px; --h-md: 40px; --h-lg: 48px;
  --shadow-key: 0 0 0 1px rgba(0,0,0,.06), 0 1px 1px rgba(0,0,0,.1), 0 2px 4px rgba(0,0,0,.08),
                inset 0 1px 2px rgba(255,255,255,.4), inset 0 -2px 4px rgba(0,0,0,.08);
  --shadow-key-pressed: 0 0 0 1px rgba(0,0,0,.06), 0 1px 1px rgba(0,0,0,.06),
                inset 0 1px 2px rgba(0,0,0,.08), inset 0 2px 4px rgba(0,0,0,.04), inset 0 -1px 2px rgba(0,0,0,.05);
  --shadow-key-dark: 0 1px 1px rgba(0,0,0,.35), 0 3px 6px rgba(0,0,0,.28), 0 8px 16px rgba(0,0,0,.22),
                inset 0 1px 2px rgba(255,255,255,.14), inset 0 -3px 6px rgba(0,0,0,.55);
  --shadow-key-dark-pressed: 0 1px 2px rgba(0,0,0,.25), inset 0 2px 6px rgba(0,0,0,.55), inset 0 -1px 1px rgba(255,255,255,.06);
  --shadow-tray: inset 0 1px 2px rgba(0,0,0,.08), inset 0 2px 4px rgba(0,0,0,.05),
                inset 0 -2px 3px rgba(0,0,0,.06), 0 1px 0 rgba(255,255,255,.9);
  --shadow-tray-pill: 0 2px 4px rgba(0,0,0,.15), 0 1px 1px rgba(0,0,0,.08),
                inset 0 1px 0 rgba(255,255,255,.95), inset 0 -2px 3px rgba(0,0,0,.06);
  --glyph-shadow: drop-shadow(0 1px 1px rgba(0,0,0,.22)) drop-shadow(0 2px 3px rgba(0,0,0,.12));
  --letterpress: 0 1px 0 rgba(255,255,255,.8);
  --ease-key: cubic-bezier(.32,.72,0,1);
  --ease-slide: cubic-bezier(.22,1,.36,1);
  --ease-pop: cubic-bezier(.34,1.56,.64,1);
  --focus-ring: 2px solid #171717;   /* outline-offset 2px */
}
```

Members: `buttons/add-to-cart-button.tsx`, `buttons/bookmark-save-button.tsx`, `buttons/copy-button.tsx`, `buttons/depth-outline-button.tsx`, `buttons/dimple-switch.tsx`, `buttons/download-button.tsx`, `buttons/follow-button.tsx`, `buttons/hold-to-delete-button.tsx`, `buttons/inset-button.tsx`, `buttons/like-button.tsx`, `buttons/quantity-stepper-button.tsx`, `buttons/segmented-toggle-button.tsx`, `buttons/slate-chip-switch.tsx`, `buttons/slide-to-confirm-button.tsx`, `buttons/soft-pill-button.tsx`, `buttons/soft-ui-button.tsx`, `buttons/three-d-button.tsx`, `buttons/three-d-icon-button.tsx`, `mockups/apple-ipod-mockup-card.tsx`

### 2.5 Neutral product UI (85)

The house style for app surfaces: white cards with `#f5f5f5` hairlines and a 5% `shadow-lg`, neutral ink text, 40px controls with 8px radius, focus by border colour only, 12px menus with a very soft 50px shadow, tabular numbers, small mono meta, uppercase 10px eyebrows. Semantic colours only for state (emerald ok, rose error, amber warning). This is the family to copy for tables, forms, inputs, menus and light widgets.

```css
:root {
  --bg: #ffffff;
  --bg-subtle: #fafafa;
  --bg-muted: #f5f5f5;
  --border: #e5e5e5;
  --border-soft: #f5f5f5;
  --text: #171717;
  --text-strong: #0a0a0a;
  --text-2: #404040;
  --text-muted: #737373;
  --text-faint: #a3a3a3;
  --text-disabled: #d4d4d4;
  --primary: #171717;          /* buttons #262626 in some, forms #0a0a0a */
  --primary-hover: #262626;
  --on-primary: #ffffff;
  --success: #10b981;  --success-strong: #059669;  --success-bg: #ecfdf5;  --success-text: #047857;
  --danger: #f43f5e;   --danger-strong: #e11d48;   --danger-bg: #fff1f2;   --danger-border: #fda4af;  --danger-text: #be123c;
  --danger-menu: #ef4444;  --danger-menu-bg: #fef2f2;
  --warning: #f59e0b;  --warning-text: #d97706;
  --info: #0284c7;
  --radius-control: 8px;       /* forms 6px */
  --radius-menu: 12px;
  --radius-card: 16px;         /* tables 12px, widgets 24px, forms 24px */
  --h-control: 40px;           /* forms 44px */
  --shadow-card: 0 10px 15px -3px rgba(0,0,0,.05), 0 4px 6px -4px rgba(0,0,0,.05);
  --shadow-card-stack: 0 0 0 1px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.05), 0 4px 8px rgba(0,0,0,.06), 0 12px 24px rgba(0,0,0,.04);
  --shadow-menu: 0 20px 50px -12px rgba(0,0,0,.05);
  --shadow-popover: 0 1px 3px rgba(0,0,0,.1), 0 1px 2px -1px rgba(0,0,0,.1);
  --font-sans: Geist, ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --fs-eyebrow: 10px; --ls-eyebrow: .1em;
  --fs-meta: 11px; --fs-row: 12px; --fs-body: 14px;
  --ease: cubic-bezier(.22,1,.36,1);
  --ease-enter: cubic-bezier(.25,.46,.45,.94);
}
```

Members: `audio/music-playlist-card.tsx`, `calender/booking-slot-calendar.tsx`, `calender/date-range-picker-card.tsx`, `calender/event-countdown-card.tsx`, `calender/month-picker-calendar.tsx`, `calender/week-strip-calendar.tsx`, `contact/copy-email.tsx`, `dropdowns/file-menu-dropdown.tsx`, `dropdowns/filter-sort-dropdown.tsx`, `dropdowns/kebab-actions-dropdown.tsx`, `dropdowns/notification-dropdown.tsx`, `dropdowns/share-menu-dropdown.tsx`, `dropdowns/user-menu-dropdown.tsx`, `dropdowns/workspace-switcher-dropdown.tsx`, `forms/contact-form.tsx`, `forms/forgot-password-form.tsx`, `forms/login-form.tsx`, `forms/newsletter-form.tsx`, `forms/signup-form.tsx`, `inputs/checkbox-field-input.tsx`, `inputs/combobox-field-input.tsx`, `inputs/date-field-input.tsx`, `inputs/floating-label-field-input.tsx`, `inputs/input-group-field.tsx`, `inputs/password-field-input.tsx`, `inputs/phone-field-input.tsx`, `inputs/radio-group-field-input.tsx`, `inputs/search-input.tsx`, `inputs/select-field-input.tsx`, `inputs/switch-field-input.tsx`, `inputs/text-field-input.tsx`, `inputs/textarea-field-input.tsx`, `frames/transform-box-frame.tsx`, `frames/transform-plus-frame.tsx`, `gallery/gallery-grid-card.tsx`, `gallery/photo-album-card.tsx`, `loaders/spin-loader.tsx`, `mockups/browser-mockup-card.tsx`, `mockups/laptop-mockup-card.tsx`, `mockups/phone-mockup-card.tsx`, `mockups/tablet-mockup-card.tsx`, `system/analytics/tracker.tsx`, `system/loaders/page-loader-overlay.tsx`, `notifications/chat-bubble-notification-banner.tsx`, `others/progress-ring-card.tsx`, `others/stacked-cards-effect.tsx`, `otp/otp-boxed-input.tsx`, `otp/otp-underline-input.tsx`, `pricing/toggle-pricing-cards.tsx`, `resources/resource-links-panel.tsx`, `socials/discord-chat-card.tsx`, `socials/facebook-post-card.tsx`, `socials/github-contribution.tsx`, `socials/github-repo-card.tsx`, `socials/instagram-post-card.tsx`, `socials/linked-in-post-card.tsx`, `socials/linked-in-profile-card.tsx`, `socials/threads-post-card.tsx`, `socials/twitter-post-card.tsx`, `socials/twitter-profile-card.tsx`, `table/customers-table.tsx`, `table/orders-table.tsx`, `table/recent-transactions-table.tsx`, `table/tasks-table.tsx`, `table/team-members-table.tsx`, `table/users-select-table.tsx`, `users/testimonial-card.tsx`, `wallet/wallet-pass-card.tsx`, `text/keyboard-shortcuts-card.tsx`, `travel/flight-boarding-card.tsx`, `widgets/analog-clock-widget.tsx`, `widgets/blob-profile.tsx`, `widgets/electric-scooter-widget.tsx`, `widgets/focus-breath-widget.tsx`, `widgets/hydration-widget.tsx`, `widgets/ios-calender-widget.tsx`, `widgets/ios-digital-clock-widget.tsx`, `widgets/ios-earbuds-widget.tsx`, `widgets/ios-map-location-widget.tsx`, `widgets/minimal-agenda-widget.tsx`, `widgets/ride-pickup-widget.tsx`, `widgets/step-count-widget.tsx`, `widgets/stopwatch-widget.tsx`, `widgets/voice-assistant-widget.tsx`, `widgets/wifi-toggle-widget.tsx`

### 2.6 Glass & frost (19)

Translucent white over imagery or colour: `rgba(255,255,255,.1–.9)` fills, 1px white borders at 20–70%, `backdrop-filter: blur(12–24px)`, soft black shadows at 10%. Used for docks, iOS-style notification banners, toasts and overlays on photos. On a dark dashboard invert to `rgba(255,255,255,.06–.1)` fills with `rgba(255,255,255,.12)` borders. Always provide an opaque fallback (`@supports not (backdrop-filter: blur(1px))`).

```css
:root {
  --glass-bg: rgba(255,255,255,.10);          /* over imagery */
  --glass-bg-light: rgba(255,255,255,.5);     /* over light pages */
  --glass-bg-solid: rgba(255,255,255,.9);     /* banners, dropdowns */
  --glass-bg-toast: rgba(255,255,255,.95);
  --glass-overlay: rgba(255,255,255,.15);     /* panels on photos */
  --glass-border: rgba(255,255,255,.2);
  --glass-border-strong: rgba(255,255,255,.7);
  --glass-blur: blur(12px);
  --glass-blur-strong: blur(24px);
  --glass-shadow: 0 20px 25px -5px rgba(0,0,0,.1), 0 8px 10px -6px rgba(0,0,0,.1);
  --banner-shadow: 0 8px 32px -4px rgba(0,0,0,.10);
  --toast-shadow: 0 4px 24px -2px rgba(0,0,0,.10), 0 0 0 1px rgba(0,0,0,.02);
  --radius-dock: 16px;
  --radius-banner: 1.25rem;
  --radius-app-tile: .625rem;
  --dock-lift: translateY(-8px) scale(1.25);
  --ease: cubic-bezier(.22,1,.36,1);
  --enter: cubic-bezier(.25,.46,.45,.94);   /* 340ms */
  --exit: cubic-bezier(.4,0,.6,1);           /* 260ms */
  --tooltip-bg: #0a0a0a;
}
```

Members: `buttons/sheen-pill-button.tsx`, `docks/Icons.tsx`, `docks/app-dock.tsx`, `docks/editor-tool-dock.tsx`, `docks/mac-dock.tsx`, `docks/presence-dock.tsx`, `docks/spotlight-bar.tsx`, `gallery/glass-overlay-image-card.tsx`, `notifications/apple-notification-banner.tsx`, `notifications/calendar-reminder-notification-banner.tsx`, `notifications/delivery-notification-banner.tsx`, `notifications/deploy-notification-banner.tsx`, `notifications/email-notification-banner.tsx`, `notifications/incoming-call-notification-banner.tsx`, `notifications/payment-notification-banner.tsx`, `notifications/system-alert-banner.tsx`, `notifications/toast-notification-banner.tsx`, `users/team-member-card.tsx`, `text/magazine-cover-card.tsx`

### 2.7 Paper editorial (30)

Print metaphors on warm off-whites: placards, receipts, tickets, postcards, polaroids, stamps, linen. Square or 4px corners, 1px borders, serif headlines (Instrument Serif, often italic), mono uppercase labels with very wide tracking (.18–.3em), dashed rules, perforations, rotations of −2 to 12deg, paper shadows. For "about", receipts or report pages rather than the live dashboard.

```css
:root {
  --paper: #f6f2eb;
  --paper-2: #faf8f5;          /* placard, contact card */
  --paper-receipt: #faf8f2;
  --paper-doc: #fffef9;
  --paper-post: #fffdf5;
  --paper-mat: #f7f4ef;
  --ink: #171717;
  --ink-2: #404040;
  --ink-muted: #737373;
  --ink-faint: #a3a3a3;
  --stone: #78716c;  --stone-dark: #57534e;  --stone-light: #a8a29e;
  --sepia-text: #3d3530;  --sepia-label: #a09080;
  --rule: #e5e5e5;
  --rule-dashed: 1px dashed #d4d4d4;
  --stamp: #f43f5e;            /* 2px border, rotate(-12deg), text #e11d48 letter-spacing .28em */
  --radius: 4px;            /* rounded-sm in Tailwind v4 */
  --font-serif: "Instrument Serif", ui-serif, Georgia, Cambria, "Times New Roman", serif;
  --font-mono: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --ls-label: .2em;
  --shadow-polaroid: 0 8px 30px rgba(0,0,0,.12);
  --shadow-photo: 0 1px 2px rgba(15,23,42,.05), 0 10px 24px rgba(15,23,42,.12), 0 22px 48px -6px rgba(15,23,42,.1);
  --shadow-wall: 0 16px 34px rgba(15,23,42,.12);
  --scallop: radial-gradient(circle at 8px 0, transparent 6px, var(--paper-receipt) 6px) 0 0 / 16px 8px;
  --linen: repeating-linear-gradient(45deg, rgba(120,98,72,.08) 0 1px, transparent 1px 6px),
           repeating-linear-gradient(-45deg, rgba(120,98,72,.06) 0 1px, transparent 1px 6px);
}
```

Members: `background-gradient/ink-wash-background.tsx`, `background-gradient/linen-weave-background.tsx`, `background-gradient/paper-fold-background.tsx`, `background-gradient/sand-drift-background.tsx`, `background-gradient/soft-spotlight-background.tsx`, `background-gradient/terrazzo-fragment-background.tsx`, `buttons/linen-tab-button.tsx`, `event/event-ticket-card.tsx`, `files/ink-stamp-document-card.tsx`, `files/stacked-folder-card.tsx`, `frames/circle-cut-frame.tsx`, `frames/sticky-note-polaroid-frame.tsx`, `gallery/gallery-wall-card.tsx`, `gallery/museum-placard-card.tsx`, `gallery/photo-contact-sheet-card.tsx`, `gallery/polaroid-image-card.tsx`, `gallery/slow-living-polaroid-card.tsx`, `gallery/stamp-postcard-card.tsx`, `others/thermal-receipt-card.tsx`, `pricing/retail-price-tag-card.tsx`, `profile/contact-profile-card.tsx`, `profile/editorial-staff-profile-card.tsx`, `profile/team-member-profile-grid.tsx`, `profile/user-profile-card.tsx`, `text/daily-motivation-card.tsx`, `text/denim-product-editorial-card.tsx`, `text/drop-cap-editorial-card.tsx`, `text/editorial-quote-card.tsx`, `text/journal-writing-card.tsx`, `travel/travel-postcard-card.tsx`

### 2.8 Grid & grain light (9)

Cool neutral technical surfaces: graph paper, dot grids, hatch, ruled lines, fine grain, frosted mesh. Quiet section fills and empty-state backdrops; the file-upload drop zone borrows the grid and adds corner brackets.

```css
:root {
  --bg: #ffffff;
  --bg-alt: #fafafa;
  --grid-line: rgba(0,0,0,.05);          /* 20px graph paper */
  --grid: linear-gradient(to right, var(--grid-line) 1px, transparent 1px) 0 0 / 20px 20px,
          linear-gradient(to bottom, var(--grid-line) 1px, transparent 1px) 0 0 / 20px 20px;
  --dots: radial-gradient(circle, #e8e8e8 1px, transparent 1px) 0 0 / 12px 12px;
  --hatch: repeating-linear-gradient(45deg, #f5f5f5 0, #f5f5f5 1px, transparent 0, transparent 50%) 0 0 / 12px 12px;
  --ruled: repeating-linear-gradient(to bottom, transparent 0, transparent 21px, rgba(0,0,0,.07) 21px, rgba(0,0,0,.07) 22px);
  --grain-a: radial-gradient(circle, #d4d4d4 1px, transparent 1px) 0 0 / 3px 3px;  /* opacity .55 */
  --grain-b: radial-gradient(circle, #e5e5e5 1px, transparent 1px) 0 0 / 5px 5px;  /* opacity .40 */
  --frost: linear-gradient(135deg, #fafcfd 0%, #f2f8fa 50%, #eaf4f6 100%);
  --frost-grid: rgba(148,163,184,.22);    /* 20px, opacity .5 */
  --bracket: 2px solid #d4d4d4;           /* 20px corner brackets, hover #737373 */
}
```

Members: `background-gradient/frost-mesh-background.tsx`, `background-gradient/rain-prism-background.tsx`, `background-pattern/diagonal-box-pattern.tsx`, `background-pattern/dot-grid-pattern.tsx`, `background-pattern/fine-grain-pattern.tsx`, `background-pattern/graph-paper-pattern.tsx`, `background-pattern/line-grid-pattern.tsx`, `background-pattern/reverse-diagonal-box-pattern.tsx`, `inputs/file-upload-field-input.tsx`

### 2.9 Pastel aurora (10)

Bright, saturated blurred blobs (opacity .55–.8) on near-white, closed by a 3–4% grain; named palettes (lime-aqua aurora, coral, honey, mint, sunset, tropical, cherry petals, sunrise, arc bands). Marketing/hero backdrops; too loud behind data.

```css
:root {
  --base: #fffefb;
  --blob-blur-wrapper: blur(24px);   /* wrapper inset:-24px */
  --blob-blur: blur(64px);
  --aurora: #e9ff95, #59e39c, #1ec9d8, #2874f0;      /* .80 .70 .65 .55 */
  --coral: #fda4af, #fdba74, #fb7185, #fde68a;       /* base #fffbf9 */
  --honey: #fbbf24, #f59e0b, #fb923c, #fecaca;       /* base #fffdf7 */
  --mint: #6ee7b7, #2dd4bf, #22d3ee, #a7f3d0;        /* base #f8fffe */
  --sunset: #fb923c, #facc15, #f43f5e, #f59e0b;      /* base #fffaf5 */
  --tropical: #2dd4bf, #bef264, #38bdf8, #34d399;    /* base #fefffe */
  --arc: rgba(56,189,248,.52) 0%, rgba(45,212,191,.44) 18%, rgba(245,158,11,.38) 40%, rgba(244,63,94,.30) 62%;
  --grain: radial-gradient(circle at center, #000 1px, transparent 1px) 0 0 / 4px 4px; /* opacity .03 */
  --tint-warm-bg: #fffbeb; --tint-warm-border: #fef3c7; --tint-warm-text: #451a03;   /* weather clear */
  --tint-cool-bg: #f0f9ff; --tint-cool-border: #bae6fd; --tint-cool-text: #082f49;   /* weather rain */
}
```
(Lists like `--aurora` are documentation shorthands; split them into one property per colour when used.)

Members: `background-gradient/arc-bands-background.tsx`, `background-gradient/aurora-background.tsx`, `background-gradient/cherry-petal-background.tsx`, `background-gradient/coral-glow-background.tsx`, `background-gradient/honey-ember-background.tsx`, `background-gradient/mint-lagoon-background.tsx`, `background-gradient/sunrise-horizon-background.tsx`, `background-gradient/sunset-bloom-background.tsx`, `background-gradient/tropical-tide-background.tsx`, `others/weather-snapshot-card.tsx`

### 2.10 Hand-made: neo-brutal, halftone, sketch (5)

Offset solid shadows, 1px ink borders, halftone dot fields, hand-drawn SVG annotations roughened by `feTurbulence`. Small doses only: a highlighted number, an empty state, a callout.

```css
:root {
  --ink: #171717;
  --border-ink: 1px solid #171717;
  --hard-shadow: 4px 4px 0 0 #171717;
  --hard-shadow-paper: 5px 5px 0 #e6e2bc;    /* notepad on #fffdf0 */
  --halftone-rose: radial-gradient(circle, #fb7185 1.2px, transparent 1.2px) 0 0 / 7px 7px;   /* .35 */
  --halftone-teal: radial-gradient(circle, #2dd4bf 1.2px, transparent 1.2px) 0 0 / 9px 9px;   /* .30 */
  --halftone-amber: radial-gradient(circle, #f59e0b 1px, transparent 1px) 0 0 / 5px 5px;      /* .22 */
  --mark-wavy: #d8b4fe;        /* purple-300 default; swap for brand */
  --mark-circle: #a5f3fc;      /* cyan-200 */
  --mark-highlight: rgba(253,224,71,.6);
  --mark-cross: #f87171;
  --mark-box: #fb923c;
  --rough-filter: url(#hd-rough);   /* feTurbulence fractalNoise .045 / 2 octaves / seed 4 + feDisplacementMap scale 2.6 */
}
```

Members: `background-gradient/halftone-pop-background.tsx`, `frames/hard-shadow-polaroid-frame.tsx`, `text/notepad-card.tsx`, `underlines/annotated-text.tsx`, `underlines/annotated-text-showcase.tsx`

---

## 3. Component index

Format: **file** — what it is · style family · ★ (dashboard-relevant, with the use in brackets). Indented lines give the distinctive techniques with exact values. Folder intros list what every file in the folder shares. 102 of 210 entries are starred.

**Shortlist for a mobile crypto/trading dashboard** (start here):
- Tables: `table/orders-table` (sortable headers), `table/recent-transactions-table` (signed amounts + pagination), `table/users-select-table` (bulk select), shared shell in the table intro.
- Buttons: `buttons/three-d-button` (reference key recipes), `segmented-toggle-button` (timeframes), `slide-to-confirm-button` and `hold-to-delete-button` (irreversible actions), `copy-button` (addresses), `quantity-stepper-button`, `bookmark-save-button` (watchlist).
- Inputs: `inputs/input-group-field` (amount + suffix), `combobox-field-input` (token search), `search-input`, `switch-field-input`, `radio-group-field-input` (order type), `otp/otp-boxed-input` (2FA).
- Dropdowns: `filter-sort-dropdown`, `notification-dropdown`, `kebab-actions-dropdown` (inline, no clipping on mobile), `workspace-switcher-dropdown` (account switcher).
- Notifications: `notifications/toast-notification-banner`, `payment-notification-banner`, `system-alert-banner`.
- Docks: `docks/app-dock` (bottom nav), `docks/spotlight-bar` (⌘K search).
- Loaders: `loaders/spin-loader`, `loaders/text-loader`, `system/loaders/page-loader-overlay`, frames' skeleton pattern.
- Widgets: `widgets/pomodoro-widget` (countdown ring), `battery-face-widget` (gauge), `step-count-widget` (KPI), `stopwatch-widget`, `others/progress-ring-card`, `socials/github-contribution` (heatmap).
- Wallet: `wallet/wallet-pass-card` (flip + QR), `users/credit-card-glass` (balance card).
- Backgrounds: `dark-carbon-spotlight-background`, `dark-midnight-mesh-background`, `dark-teal-depth-background`, `background-pattern/*`.
- Text effects / underlines: `underlines/annotated-text` (highlight a figure), `text/keyboard-shortcuts-card` (`<kbd>` style).


### background-gradient (26)

All 26 share one skeleton: a root `position:relative; isolation:isolate; overflow:hidden; background:<base>`, then absolutely positioned `pointer-events:none; inset:0; z-index:-1` layers, and almost always a final **grain** layer (`radial-gradient(circle at center,<ink> 1px,transparent 1px)` tiled at 3–6px, opacity 0.02–0.05). Blob recipes put the blobs inside a wrapper with `inset:-24px; filter:blur(24px)` (Tailwind `-inset-6 blur-xl`) and give each blob `border-radius:50%; filter:blur(64px)` (`blur-3xl`). Pure CSS, no JS, no animation. Every one is a ★ candidate for a dashboard page background; the dark ones are the most directly reusable.

- **arc-bands-background.tsx** — Light "rainbow arc": three stacked elliptical radial bands rising from the bottom edge on warm off-white. · Style: Pastel aurora · ★
  - base `#FFFCF7`, wash `linear-gradient(180deg,#FFFCF7 0%,#FFF8F0 100%)`
  - band 1: `bottom:-28%; left:50%; height:92%; width:150%; translate:-50% 0; border-radius:100%; background:radial-gradient(ellipse 120% 88% at 50% 100%,rgba(56,189,248,.52) 0%,rgba(45,212,191,.44) 18%,rgba(245,158,11,.38) 40%,rgba(244,63,94,.30) 62%,rgba(255,252,247,0) 82%)`; band 2 same at .28/.24/.20/.16 with `filter:blur(40px)`; band 3 white `rgba(255,255,255,.55)` with `blur(64px)`
- **aurora-background.tsx** — Light aurora: 4 blurred blobs (lime, green, cyan, blue). · Pastel aurora · ★
  - base `#FFFEFB`; blobs `#E9FF95` .80 (top -20% left -10%, 70%), `#59E39C` .70, `#1EC9D8` .65, `#2874F0` .55; grain `#000` 4px .035
- **cherry-petal-background.tsx** — Pink field scattered with 7 petal shapes. · Pastel aurora
  - petals: `border-radius:100% 100% 20% 100%`, rotated -30..32deg, 40–56px wide, colours `#FDA4AF #FB7185 #FECDD3 #F43F5E`, opacity .30–.60, `blur(.5px)`; base `radial-gradient(circle at 50% 0%,#FFE8EC 0%,#FFF7F8 48%,#FFF1F3 100%)`; grain `#9F1239` 6px .03
- **coral-glow-background.tsx** — Warm coral/peach aurora. · Pastel aurora
  - base `#FFFBF9`; blobs `#FDA4AF` .75, `#FDBA74` .70, `#FB7185` .60, `#FDE68A` .65
- **dark-arc-bands-background.tsx** — Dark twin of arc-bands. · Carbon spotlight dark · ★
  - base `#0A0B0E`, wash `linear-gradient(180deg,#101218 0%,#0A0B0E 100%)`; band alphas .34/.28/.22/.18 then .18/.15/.12/.10; top band white .08; grain `rgba(255,255,255,.7)` 4px .04
- **dark-aurora-background.tsx** — Dark teal/cyan aurora. · Carbon spotlight dark · ★
  - base `#0A0C0F`, wash `linear-gradient(180deg,#12151A 0%,#0A0C0F 55%,#06080A 100%)`; blobs `#2DD4BF` .22, `#22D3EE` .18, `#34D399` .16, `#38BDF8` .14 (blur 64px); grain `#FFF` 4px .04
- **dark-carbon-spotlight-background.tsx** — Near-black with a soft top spotlight and vignette. · Carbon spotlight dark · ★ (best neutral dashboard backdrop)
  - `radial-gradient(circle at 50% 12%,#1C1C1C 0%,#121212 36%,#0C0C0C 68%,#050505 100%)` + `radial-gradient(circle at 50% 0%,rgba(255,255,255,.14) 0%,transparent 46%)` at opacity .5 + vignette `radial-gradient(circle at center,transparent 42%,rgba(0,0,0,.55) 100%)` + grain white .7 4px .03
- **dark-ember-background.tsx** — Dark with amber/rose embers rising from below. · Carbon spotlight dark
  - base `#100C0A`, `radial-gradient(circle at 50% 120%,#1A1210 0%,#100C0A 48%,#080605 100%)`; blobs `#F59E0B` .20, `#FB923C` .16, `#F43F5E` .14, `#FBBF24` .12 in a `inset:-32px; blur(40px)` wrapper
- **dark-ink-field-background.tsx** — Dark with three grey organic ink blots. · Carbon spotlight dark
  - blots `border-radius:42% 58% 64% 36%` (and 58/42/38/62, 36/64/58/42), `#525252` .16, `#404040` .12, `#737373` .10, wrapper `blur(40px)`
- **dark-midnight-mesh-background.tsx** — Dark slate with a double grid (28px + 7px) and teal/sky glows. · Carbon spotlight dark · ★ (trading-terminal look)
  - base `linear-gradient(145deg,#101418 0%,#0A0D10 52%,#06080A 100%)`; grid `linear-gradient(to right,rgba(148,163,184,.10) 1px,transparent 1px),linear-gradient(to bottom,rgba(148,163,184,.10) 1px,transparent 1px)` size 28px opacity .14; fine grid .08 at 7px opacity .06; glows `#2DD4BF` .16 / `#38BDF8` .14 / `#34D399` .12 in `inset:-32px; blur(64px)`; vignette `transparent 54% → rgba(0,0,0,.42)`
- **dark-rose-noir-background.tsx** — Dark wine with rose glows. · Carbon spotlight dark
  - `radial-gradient(circle at 30% 20%,#181014 0%,#0E0A0B 50%,#080608 100%)`; blobs `#FB7185` .14, `#F43F5E` .12, `#FDA4AF` .10, `#BE123C` .12; vignette `transparent 58% → rgba(0,0,0,.4)`
- **dark-teal-depth-background.tsx** — Deep teal ocean. · Carbon spotlight dark · ★
  - `linear-gradient(160deg,#0A1820 0%,#061014 45%,#030A0D 100%)`; blobs `#0D9488` .22, `#0891B2` .18, `#14B8A6` .14, `#22D3EE` .12; extra `radial-gradient(circle at 80% 20%,rgba(45,212,191,.08) 0%,transparent 42%)`
- **frost-mesh-background.tsx** — Icy light grid with mint glows. · Grid & grain light
  - `linear-gradient(135deg,#FAFCFD 0%,#F2F8FA 50%,#EAF4F6 100%)`; grid slate .22 @20px opacity .5 + .16 @4px opacity .3; blobs `#A5F3FC` .35, `#6EE7B7` .28, `#99F6E4` .22; grain `#0F172A` 6px .03
- **halftone-pop-background.tsx** — Cream with three halftone dot fields (rose, teal, amber) and a cream vignette. · Hand-made (neo-brutal / halftone / sketch)
  - `radial-gradient(circle,#FB7185 1.2px,transparent 1.2px)` 7px .35 (top-right 72%), `#2DD4BF` 1.2px 9px .30 (bottom-left), `#F59E0B` 1px 5px .22; vignette `radial-gradient(circle at center,transparent 62%,rgba(255,249,242,.85) 100%)`; base `linear-gradient(135deg,#FFF9F2,#FFF4E8)`
- **honey-ember-background.tsx** — Honey/amber aurora. · Pastel aurora
  - base `#FFFDF7`; `#FBBF24` .78, `#F59E0B` .70, `#FB923C` .58, `#FECACA` .68; grain `#78350F` 4px .034
- **ink-wash-background.tsx** — Light sumi-e: warm-grey organic blots. · Paper editorial
  - `radial-gradient(circle at 50% 0%,#FFFFFF 0%,#FAFAF8 55%,#F5F5F2 100%)`; blots `#A8A29E` .18, `#78716C` .14, `#57534E` .12, `#A8A29E` .16 (`blur(40px)` wrapper); grain `#292524` 5px .025
- **linen-weave-background.tsx** — Beige linen: crossed 45/-45deg hairlines + 24px grid. · Paper editorial
  - `repeating-linear-gradient(45deg,rgba(120,98,72,.08) 0px,rgba(120,98,72,.08) 1px,transparent 1px,transparent 6px),repeating-linear-gradient(-45deg,rgba(120,98,72,.06) 0 1px,transparent 1px 6px)` opacity .6; base `linear-gradient(180deg,#FAF6F0 0%,#F3EDE4 48%,#EFE8DE 100%)`
- **mint-lagoon-background.tsx** — Mint/teal aurora. · Pastel aurora
  - base `#F8FFFE`; `#6EE7B7` .75, `#2DD4BF` .68, `#22D3EE` .62, `#A7F3D0` .72; grain `#0F766E` 5px .028
- **paper-fold-background.tsx** — Paper with a diagonal fold crease. · Paper editorial
  - crease: `linear-gradient(128deg,transparent 42%,rgba(120,113,108,.10) 49.5%,rgba(255,255,255,.55) 50.5%,transparent 58%)` over `linear-gradient(160deg,#FCFBF8 0%,#F3F0E8 48%,#ECE7DD 100%)`; white 32px grid .35/.25 at opacity .5
- **rain-prism-background.tsx** — Cool grey with angled rain streaks and a prism band. · Grid & grain light
  - streaks `repeating-linear-gradient(108deg,rgba(255,255,255,.55) 0 1px,transparent 1px 14px)` .25 + `repeating-linear-gradient(102deg,rgba(148,163,184,.35) 0 1px,transparent 1px 9px)` .20; prism `linear-gradient(90deg,transparent 0%,rgba(45,212,191,.16) 24%,rgba(251,113,133,.14) 52%,rgba(56,189,248,.16) 78%,transparent 100%)` .35; base `linear-gradient(180deg,#F4F7FA 0%,#DDE6EE 58%,#C8D5E0 100%)`
- **sand-drift-background.tsx** — Sand dunes from elliptical blobs. · Paper editorial
  - dunes `border-radius:100%`, `#E8C9A8` .70, `#DDB892` .55, `#C9A882` .45 with `blur(8px)`; base `linear-gradient(180deg,#FAF4EC 0%,#F0E4D6 52%,#E8D8C8 100%)`; grain `#8B7355` 3px .05
- **soft-spotlight-background.tsx** — Warm grey studio spotlight. · Paper editorial
  - `radial-gradient(circle at 50% 18%,#FFFFFF 0%,#F7F6F3 38%,#E8E6E1 72%,#D6D3CE 100%)`; vignette `transparent 48% → rgba(41,37,36,.12)`
- **sunrise-horizon-background.tsx** — Peach-to-aqua sky with a sun disc. · Pastel aurora
  - `linear-gradient(180deg,#FFF8F3 0%,#FFE8D8 42%,#FFD9C8 68%,#C8E8EE 100%)`; hills `#FFB38A` .55, `#FF8F6B` .45, `#7DD3C7` .40 (`blur(40px)`); sun 112px `#FFF1DC` .9 `blur(12px)`
- **sunset-bloom-background.tsx** — Orange/yellow/rose aurora. · Pastel aurora
  - base `#FFFAF5`; `#FB923C` .72, `#FACC15` .68, `#F43F5E` .55, `#F59E0B` .62
- **terrazzo-fragment-background.tsx** — Terrazzo: 10 rotated rounded chips. · Paper editorial
  - chips 28–80px, `rotate(-28..42deg)`, radii 6/8px or 50%, colours `#D9C4A9 #F43F5E #99F6E4 #A8A29E #FCD34D #2DD4BF #D6D3D1 #FB923C #78716C #5EEAD4` at .35–.80
- **tropical-tide-background.tsx** — Teal/lime/sky aurora. · Pastel aurora
  - base `#FEFFFE`; `#2DD4BF` .72, `#BEF264` .75, `#38BDF8` .65, `#34D399` .60

### background-pattern (6)

Single-element patterns, light neutrals only. Pure CSS. ★ all (cheap section fills; invert the colours for dark mode).

- **diagonal-box-pattern.tsx** — 45deg hairline hatch. · Grid & grain light · `background:#fff repeating-linear-gradient(45deg,#f5f5f5 0,#f5f5f5 1px,transparent 0,transparent 50%) 0 0/12px 12px`
- **dot-grid-pattern.tsx** — Dot grid. · Grid & grain light · `background:#fafafa radial-gradient(circle,#e8e8e8 1px,transparent 1px) 0 0/12px 12px`
- **fine-grain-pattern.tsx** — Two dot layers as paper grain. · Grid & grain light · `#d4d4d4` 1px @3px opacity .55 + `#e5e5e5` 1px @5px opacity .40 on `#FAFAFA`
- **graph-paper-pattern.tsx** — 20px graph paper. · Grid & grain light · `linear-gradient(to right,rgba(0,0,0,.05) 1px,transparent 1px),linear-gradient(to bottom,rgba(0,0,0,.05) 1px,transparent 1px)` size 20px on `#fff`
- **line-grid-pattern.tsx** — Ruled notebook lines. · Grid & grain light · `repeating-linear-gradient(to bottom,transparent 0,transparent 21px,rgba(0,0,0,.07) 21px,rgba(0,0,0,.07) 22px)` over `linear-gradient(168deg,#fefefe 0%,#f4f4f4 52%,#fafafa 100%)`
- **reverse-diagonal-box-pattern.tsx** — Same hatch at -45deg.

### buttons (22)

Shared mechanics: `font-family:sans; font-weight:600 (500 on small keys); user-select:none; outline:none` + `:focus-visible{outline:2px solid #171717; outline-offset:2px}`; transitions on `background-color,box-shadow,color` 200ms (300ms for stateful ones) `cubic-bezier(.32,.72,0,1)`; `:disabled{pointer-events:none;opacity:.4}`; every transition has a `prefers-reduced-motion` off switch. Stateful buttons stack all labels in one grid cell (`grid-area:1/1`) and crossfade: outgoing `opacity:0` in 200ms, incoming `opacity:1` in 300ms with `transition-delay:200ms` — width never jumps. Icons likewise stack in a fixed 16px slot. A visually hidden `aria-live="polite"` span announces the new state. All ★ (buttons are in scope for the dashboard).

- **add-to-cart-button.tsx** — Dark raised key: idle → sunken "Adding…" with spinner → emerald "Added" key, auto-reset. · Tactile 3D keys · ★
  - idle = **Dark key raised** recipe on `#262626` (hover `#404040`, active `#171717` + **Dark key pressed**); loading keeps pressed shadow, text `#d4d4d4`; added `#059669` with emerald raised recipe (see Design language §Shadows). `height:48px; min-width:176px; border-radius:12px; padding:0 20px`. Timers 1200ms / 1600ms. `aria-busy`, `aria-disabled`.
- **bookmark-save-button.tsx** — Light key toggling "Save"→"Saved" with amber filled bookmark. · Tactile 3D keys · ★ (watchlist star)
  - **Light key raised/pressed** recipes; saved `background:#fffbeb; color:#b45309`; icon `transform:scale(1.1); fill:#f59e0b` with `filter:drop-shadow(0 1px 1px rgba(245,158,11,.35)) drop-shadow(0 2px 4px rgba(245,158,11,.2))`, spring easing `cubic-bezier(.34,1.56,.64,1)` 300ms. `aria-pressed`.
- **cinder-latch-button.tsx** — Charcoal pill with an orange ember glow rising from the bottom and a centre groove. · Carbon dark luxe
  - shell `linear-gradient(180deg,#3a3a3a 0%,#1d1d1d 48%,#101010 100%)`; ember layer (bottom 70%) `radial-gradient(circle 70px at 50% 115%,rgba(251,146,60,.55),rgba(225,29,72,.22),transparent 72%)`; face sheen `linear-gradient(180deg,rgba(255,255,255,.1) 0%,rgba(255,255,255,.02) 28%,rgba(0,0,0,.2) 100%)`; groove `1px rgba(255,255,255,.1)` across the middle; `border-radius:18px; box-shadow:0 1px 0 rgba(255,255,255,.14),0 12px 28px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.12)`; hover `filter:brightness(1.1)`, active `translateY(1px)`; focus outline `#fcd34d`.
- **copy-button.tsx** — Keycap that writes to clipboard and crossfades to a green check. · Tactile 3D keys · ★ (copy address / tx hash)
  - `box-shadow:0 0 0 1px rgba(0,0,0,.06),0 1px 1px rgba(0,0,0,.12),0 2px 3px rgba(0,0,0,.12),inset 0 -2px 3px rgba(0,0,0,.08)`; pressed `0 0 0 1px rgba(0,0,0,.06),0 1px 1px rgba(0,0,0,.06),inset 0 1px 1px rgba(0,0,0,.06),inset 0 2px 3px rgba(0,0,0,.03),inset 0 -2px 3px rgba(0,0,0,.05)`; label `text-shadow:0 1px 0 rgba(255,255,255,.8)` (letterpress); icon glyph shadow `drop-shadow(0 1px 1px rgba(0,0,0,.22)) drop-shadow(0 2px 3px rgba(0,0,0,.12))`, copied `rgba(4,120,87,.3)/.15`. `navigator.clipboard.writeText` in try/catch, confirmation shown even on failure; reset 1600ms.
- **depth-outline-button.tsx** — White outlined CTA with layered float depth (sm/md/lg). · Tactile 3D keys · ★
  - rest `0 0 0 1px rgba(0,0,0,.06),0 1px 1px rgba(0,0,0,.04),0 4px 10px rgba(0,0,0,.05),0 12px 28px rgba(0,0,0,.05),inset 0 1px 1px rgba(255,255,255,.75),inset 0 -1px 2px rgba(0,0,0,.04)`; hover `0 0 0 1px rgba(0,0,0,.08),0 2px 4px rgba(0,0,0,.05),0 8px 16px rgba(0,0,0,.07),0 20px 40px rgba(0,0,0,.06),inset 0 1px 1px rgba(255,255,255,.8),inset 0 -1px 2px rgba(0,0,0,.05)`; active `0 0 0 1px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.04),inset 0 2px 4px rgba(0,0,0,.08),inset 0 1px 0 rgba(255,255,255,.6)` + `translateY(1px)`; sizes h 36/40/48, radius 8/12/12, `letter-spacing:.025em`.
- **dimple-switch.tsx** — Skeuomorphic toggle with a square dimpled knob (12 dots), turns amber. · Tactile 3D keys · ★
  - sized in `em` from `font-size:24px`; frame `linear-gradient(to bottom,#d5d5d5,#e8e8e8); border-radius:8px; padding:2px; box-shadow:0 1px 1px rgba(255,255,255,.6)`; track `1.5em×3em; #e8e8e8; border-radius:6px; box-shadow:inset 0 0 .0625em .125em rgba(255,255,255,.2),inset 0 0 .0625em .125em rgba(0,0,0,.4)`, checked `#f3b519`; knob `1.375em; border-radius:.3125em; box-shadow:inset 0 -.0625em .0625em .125em rgba(0,0,0,.1),inset 0 -.125em .0625em rgba(0,0,0,.2),inset 0 .1875em .0625em rgba(255,255,255,.3),0 .125em .125em rgba(0,0,0,.5)`, slides `left:.0625em→1.5625em` 400ms linear; dots 2px `radial-gradient(circle at 50% 0,#f5f5f5,#c4c4c4)` in a 3-col grid. Real `<input type=checkbox>` stretched invisibly over the control (`appearance:none; opacity:0`), `peer-checked` drives styles; focus ring via `:has(:focus-visible)`.
- **download-button.tsx** — Light key: arrow → spinner (sunken) → emerald "Downloaded". · Tactile 3D keys · ★ (export CSV)
  - Light raised/pressed recipes; done `#059669` + `0 1px 1px rgba(0,0,0,.25),0 3px 6px rgba(0,0,0,.2),0 6px 12px rgba(0,0,0,.15),inset 0 1px 2px rgba(255,255,255,.22),inset 0 -3px 6px rgba(0,0,0,.35)`; 1400ms/1800ms.
- **follow-button.tsx** — Dark pill "Follow" ↔ light "Following" pill. · Tactile 3D keys · ★ (watch/unwatch)
  - `border-radius:9999px; height:40px`; dark state `#171717` Dark raised; following `#fafafa; color:#525252` Light raised; 300ms.
- **hold-to-delete-button.tsx** — Press-and-hold: a rose fill wipes left→right, label counter-translates so it looks clipped by the moving edge. · Tactile 3D keys · ★ (destructive confirm, e.g. cancel order)
  - fill `#e11d48` `translateX(-100%→0)` linear for holdMs (1100ms default), its inner content `translateX(100%→0)` simultaneously; release eases back 300ms ease-out. Bevels on a separate overlay above the fill: holding `inset 0 1px 0 rgba(255,255,255,.25),inset 0 2px 4px rgba(0,0,0,.25),inset 0 -2px 3px rgba(0,0,0,.2)`. Keyboard: Space/Enter keydown starts, keyup cancels. `touch-action:none`. `width:224px; height:48px; radius:12px`.
- **inset-button.tsx** — Recessed / pressed-in button, light & dark. · Tactile 3D keys · ★
  - light `#f5f5f5; color:#404040; box-shadow:inset 0 2px 4px rgba(0,0,0,.1),inset 0 -1px 1px rgba(255,255,255,.7)`, active `inset 0 3px 6px rgba(0,0,0,.14),inset 0 -1px 1px rgba(255,255,255,.5)`; dark `#262626; color:#f5f5f5; inset 0 2px 5px rgba(0,0,0,.55),inset 0 -1px 1px rgba(255,255,255,.08)`, active `inset 0 3px 8px rgba(0,0,0,.65),inset 0 -1px 1px rgba(255,255,255,.06)`.
- **like-button.tsx** — Pill with heart that pops and bursts 7 particles; shows a count. · Tactile 3D keys
  - particles 6px dots `#FB7185` from centre to offsets (0,-22)(18,-14)(22,4)(13,20)(-13,20)(-22,4)(-18,-14), `scale(1→.2)` 500ms ease-out triggered by rAF; heart `fill:#f43f5e; scale(1.1)` spring; liked bg `#fff1f2; color:#e11d48`; count `font-variant-numeric:tabular-nums`.
- **linen-tab-button.tsx** — Beige fabric tab with dashed stitching top and bottom. · Paper editorial (craft)
  - body `linear-gradient(180deg,#f8f4ee 0%,#ebe4d8 55%,#dfd6c8 100%)`; weave `repeating-linear-gradient(90deg,rgba(120,113,108,.04) 0 1px,transparent 1px 4px),repeating-linear-gradient(0deg,rgba(120,113,108,.03) 0 1px,transparent 1px 5px)`; stitches `border-top:1px dashed rgba(196,184,170,.8)` inset 12px/6px; `border:1px solid #d4cbc0; border-radius:8px; box-shadow:0 1px 0 rgba(255,255,255,.85),0 6px 14px rgba(120,113,108,.16),inset 0 1px 0 rgba(255,255,255,.65)`.
- **prism-depth-button.tsx** — Black glossy button with a white top-right flare and a cyan/blue edge flare. · Carbon dark luxe
  - shell (2px ring) `radial-gradient(circle 80px at 80% -10%,#ffffff,#181b1b)`, `border-radius:16px; padding:2px`; core `radial-gradient(circle 80px at 80% -50%,#777777,#0f1111); border-radius:14px; padding:14px 25px`; veil `radial-gradient(circle 60px at 0% 100%,#00e1ff1a,#0000ff11,transparent)`; rim glow `box-shadow:0 0 20px #ffffff38`; edge flare `radial-gradient(circle 60px at 0% 100%,#3fe9ff,#0000ff80,transparent)` with `box-shadow:-10px 10px 30px #0051ff2d`; hover `scale(1.02)`, active `scale(.98)`; `font-size:1.4rem`.
- **quantity-stepper-button.tsx** — − count + inside a recessed tray, keys are raised. · Tactile 3D keys · ★ (amount stepper)
  - tray = **Inset tray** recipe `#f5f5f5; border-radius:12px; padding:4px; height:44px`; keys 40px wide: `0 1px 1px rgba(0,0,0,.12),0 2px 3px rgba(0,0,0,.1),0 4px 8px rgba(0,0,0,.06),inset 0 1px 0 rgba(255,255,255,.55),inset 0 -2px 3px rgba(0,0,0,.1),inset 1px 0 1px rgba(255,255,255,.25),inset -1px 0 1px rgba(255,255,255,.25)`; disabled key `background:transparent; box-shadow:none; color:#d4d4d4`; count tabular-nums with `aria-live`.
- **segmented-toggle-button.tsx** — iOS-style segmented control with sliding white pill (2–5 options). · Tactile 3D keys · ★ (1H/1D/1W timeframe switch)
  - tray Inset tray recipe; pill `background:#fff; border-radius:8px; box-shadow:0 2px 4px rgba(0,0,0,.15),0 1px 1px rgba(0,0,0,.08),inset 0 1px 0 rgba(255,255,255,.95),inset 0 -2px 3px rgba(0,0,0,.06)`; pill width `calc((100% - .75rem)/2)` for 2 (`-1rem)/3`, `-1.25rem)/4`…), moved with `translateX(calc(N*100% + N*.25rem))`, 500ms `cubic-bezier(.22,1,.36,1)`; `role=tablist/tab`.
- **sheen-pill-button.tsx** — Glassy pill (default 60px tall) with double hairline border, inner bevel highlights and a blurred diagonal light band. · Glass & frost
  - shell `border:1px double rgba(51,51,51,.08); background:rgba(255,255,255,.08); backdrop-filter:blur(5px); filter:brightness(1.05); border-radius:9999px; box-shadow:inset 2px -2px 1px -1px rgba(255,255,255,.9),inset -2px 2px 1px -1px rgba(255,255,255,.9),inset 6px -6px 1px -6px rgba(255,255,255,.55),inset -6px 6px 1px -6px rgba(255,255,255,.55),inset 0 0 2px rgba(0,0,0,.8),0 4px 8px rgba(0,0,0,.2)`; light band `linear-gradient(45deg,rgba(255,255,255,.8) 0%,transparent 15%,transparent 85%,rgba(255,255,255,.8) 100%); filter:blur(7px); opacity:.8` (hover blur 9px, scale 1.05); shade veil (size −16px) `border:1px solid rgba(0,0,0,.9); filter:blur(4px)`; rim wire (size −9px) `border:1px solid rgba(255,255,255,.2); blur(1px)`; label `color:#3e3e3e; filter:drop-shadow(0 25px 3px rgba(102,102,102,.15))`; 250ms linear.
- **slate-chip-switch.tsx** — Rounded skeuomorphic switch, slate → sky. · Tactile 3D keys · ★
  - frame `linear-gradient(to bottom,#eceff3,#d9dee5); border-radius:9999px; padding:4px; font-size:20px`; track `1.45em×2.85em #c7ced8; inset 0 1px 3px rgba(0,0,0,.18)`, on `#0ea5e9` + `0 0 0 1px rgba(14,116,144,.25)`; thumb `1.22em #fff; 0 2px 5px rgba(0,0,0,.22),inset 0 1px 0 rgba(255,255,255,.95)`, `translateX(1.35em)` 300ms `cubic-bezier(.22,1,.36,1)`.
- **slide-to-confirm-button.tsx** — Drag a 48px knob across a 288×56 recessed track to confirm; track turns emerald. · Tactile 3D keys · ★ (confirm swap/withdraw on mobile)
  - track Inset tray, `border-radius:9999px; padding:4px; transform:translateZ(0); isolation:isolate` (prevents ghost pixels); knob `0 1px 1px rgba(0,0,0,.12),0 2px 3px rgba(0,0,0,.12),inset 0 1.5px 0 #fff,inset 0 -2px 3px rgba(0,0,0,.1)` with `will-change:transform`, `translate3d(x,0,0)`, snaps back 300ms `cubic-bezier(.32,.72,0,1)`; label opacity `1 - progress*1.4`; confirmed `#059669` + `inset 0 1px 3px rgba(0,0,0,.2),inset 0 -2px 3px rgba(0,0,0,.12)`; icon `filter:drop-shadow(0 1px 0 rgba(255,255,255,.9)) drop-shadow(0 -1px .5px rgba(0,0,0,.12))` (embossed). Pointer events with `touch-action:none`.
- **soft-pill-button.tsx** — Floating pill, light/dark, sm/md/lg. · Tactile 3D keys · ★
  - light `#fff; 0 2px 4px rgba(0,0,0,.06),0 8px 20px rgba(0,0,0,.08)` (active `0 1px 2px rgba(0,0,0,.06),0 3px 8px rgba(0,0,0,.06)`); dark `#262626; 0 2px 4px rgba(0,0,0,.2),0 8px 20px rgba(0,0,0,.25)`; heights 36/40/48, padding 16/20/24.
- **soft-ui-button.tsx** — Neumorphic button on `#f5f5f5`. · Tactile 3D keys
  - `box-shadow:6px 6px 14px rgba(0,0,0,.08),-6px -6px 14px rgba(255,255,255,.9)`; active `inset 4px 4px 10px rgba(0,0,0,.08),inset -4px -4px 10px rgba(255,255,255,.85)`; radius 12/12/16px.
- **three-d-button.tsx** — Universal 3D key, variants solid / soft / muted, sizes sm/md/lg/icon. · Tactile 3D keys · ★ (reference implementation of the key recipes)
  - solid `#262626` + Dark raised/pressed; soft `#fafafa` + Light raised/pressed; muted `#f5f5f5; color:#404040` (hover `rgba(229,229,229,.8)`).
- **three-d-icon-button.tsx** — 40×40 square version of the above (default variant soft), requires `aria-label`. · Tactile 3D keys · ★

### audio (3)

- **music-player-card.tsx** — 288px dark player: cover image fading into `#0a0a0a`, title/artist, emerald progress bar with white thumb, prev/play/next. · Carbon spotlight dark
  - card `background:#0a0a0a; border-radius:16px; box-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1)` (Tailwind `shadow-lg`); cover fade `linear-gradient(to top,#0a0a0a,rgba(10,10,10,.4),transparent)`; progress track 4px `#262626` fill `#10b981`, thumb 10px white; times mono 9px `#525252`; play button 40px white circle, hover `scale(1.05)`.
- **music-playlist-card.tsx** — White playlist card: 64px cover, mono uppercase type label, track rows with number→play icon swap on hover, playing row tinted emerald. · Neutral product UI
  - rows `padding:10px 16px; divide 1px #fafafa`, hover `#fafafa`, playing `rgba(236,253,245,.8)` + title `#047857`; label `font:10px mono; letter-spacing:.05em; text-transform:uppercase; color:#a3a3a3`.
- **now-playing-bar.tsx** — 320px dark mini-bar (artwork, title, controls, 64px progress shown ≥768px). · Carbon spotlight dark · ★ (compact dark bar pattern; dock-like)
  - `background:#0a0a0a; border:1px solid #262626; border-radius:16px; padding:12px`.

### calender (5)

Shared: white card `border:1px solid #f5f5f5; border-radius:16px`, elevation either `shadow-lg` tinted `rgba(0,0,0,.05)` or the **Card stack** recipe `0 0 0 1px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.05),0 4px 8px rgba(0,0,0,.06),0 12px 24px rgba(0,0,0,.04)`. Navigation re-keys the grid so it re-enters with CSS `@starting-style` (Tailwind `starting:`): `opacity:0; translateX(±8px)` → visible in 300ms `cubic-bezier(.25,.46,.45,.94)` (direction follows the arrow pressed). Day cells 36px circles, `tabular-nums`; selected `#171717`/`#262626` with white text; today `#f5f5f5` fill or `box-shadow:0 0 0 1px rgba(23,23,23,.3)`; weekday headers 10px uppercase `letter-spacing:.025em`.

- **booking-slot-calendar.tsx** — Google-Calendar-style picker: week strip + 2-column time-slot grid; taken slots struck through; past week disabled. · Neutral product UI
  - slots `height:36px; border-radius:8px; background:#fafafa`, selected `#262626`, taken `color:#d4d4d4; text-decoration:line-through; cursor:not-allowed`; slot grid enters `translateY(4px)`; inline multicolour Google Calendar SVG.
- **date-range-picker-card.tsx** — Month grid where first tap = start, second = end, range cells filled `#f5f5f5` square, endpoints `#171717` circles. · Neutral product UI · ★ (P&L date range)
  - in-range `border-radius:0; width:100%`; endpoints `border-radius:9999px`; `:active{transform:scale(.95)}`; status line "Jun 3 – pick end".
- **event-countdown-card.tsx** — 224px card with live days/hrs/min, numbers re-enter on change. · Neutral product UI · ★ (countdown to listing/unlock)
  - digits `font-size:24px; font-weight:300; tabular-nums`, keyed so each change replays `@starting-style{opacity:0; translateY(4px)}` 500ms; eyebrow 11px uppercase `#a3a3a3`.
- **month-picker-calendar.tsx** — Single-date month calendar. · Neutral product UI
- **week-strip-calendar.tsx** — 7-day strip with selected filled circle and a 4px dot under it. · Neutral product UI · ★ (mobile date strip)

### contact (1)

- **copy-email.tsx** — Inline underlined email link that copies on click with a dark tooltip "Click to copy" → "Copied". · Neutral product UI · ★ (copy wallet address inline)
  - link `text-decoration-color:#d4d4d4; text-underline-offset:2px` → hover `#737373`; tooltip `background:#171717; color:#fff; font-size:11px; border-radius:6px; padding:4px 8px`, arrow `border:4px solid transparent; border-top-color:#171717`; enters `translateY(2px)→0` 150ms `cubic-bezier(.22,1,.36,1)`; `role=tooltip`; fallback copy via hidden `<textarea>` + `execCommand("copy")` (`position:fixed; left:-9999px`).

### event (1)

- **event-ticket-card.tsx** — 384px horizontal ticket: image stub with date overlay tinted teal, perforation (dashed 1px line + two 16px white notches), mono ticket id. · Paper editorial (ticket)
  - stub overlay `rgba(19,78,74,.4)`; perforation `border-left:1px dashed #e5e5e5` + circles at `top:-8px/bottom:-8px; left:-8px; background:#fff`; eyebrow mono 10px `letter-spacing:.1em; color:#0d9488`.

### files (2)

- **ink-stamp-document-card.tsx** — Cream document card with a rotated rose "APPROVED" ink stamp. · Paper editorial
  - `background:#fffef9; border:1px solid #e5e5e5; border-radius:12px`; stamp `transform:rotate(-12deg); border:2px solid #f43f5e; border-radius:6px; padding:6px 12px`, text `10px bold; letter-spacing:.28em; color:#e11d48; uppercase`; ref mono `letter-spacing:.18em`.
- **stacked-folder-card.tsx** — Three photo cards fanned (0, -3.5deg, -7deg); hovering a zone brings that card to the front. · Paper editorial (photo)
  - cards `border:7px solid #fff; border-radius:2rem`; shadows front `0 20px 44px -14px rgba(0,0,0,.38)`, middle `0 12px 28px -10px rgba(0,0,0,.3)`, back `0 10px 24px -10px rgba(0,0,0,.28)`; transition `top,left,width,height,transform,box-shadow` 400ms `cubic-bezier(.22,1,.36,1)`; invisible fixed-width hit-zone buttons so the cards can move without changing hover target.

### folder (1)

- **opensource-folder-tab-card.tsx** — 352px black device-like card: image on top, a dark folder-tab shape (tab + SVG curve) overlapping, white stats ("116 Components"). · Carbon spotlight dark
  - `border:8px solid #000; border-radius:3rem; background:#000`; folder body `#262626` with `border-radius:0 1.35rem 2.35rem 2.35rem`, tab `42%×22%` `border-radius:1.35rem 1.15rem 0 0` joined by an SVG curve `fill:currentColor`.

### docks (6)

All docks share the "MacDock frosted shell": `border-radius:16px; border:1px solid rgba(255,255,255,.2)` (or `#fafafa`); `background:rgba(255,255,255,.10)` (over imagery) or `rgba(255,255,255,.5)` (over light pages); `backdrop-filter:blur(12px)` (`backdrop-blur-md`); `box-shadow:0 20px 25px -5px rgba(0,0,0,.1),0 8px 10px -6px rgba(0,0,0,.1)` (`shadow-xl shadow-black/10`); `padding:12px; gap:10px`. Hover motion: icon `transform-origin:bottom; translateY(-8px) scale(1.25)` 300ms `cubic-bezier(.22,1,.36,1)` with `will-change:transform`; tooltip above (`top:-40px`, 10px text, 6px radius) fades in and lifts 2px in 200ms; the same transforms fire on `:focus-visible`. Pure CSS hover — no magnification maths. ★ all (a bottom dock is the mobile nav pattern).

- **Icons.tsx** — Helper, not a component: inline multicolour brand SVGs used by mac-dock (Adobe Photoshop, Spotify, Notion Calendar, Apple Music, App Store, Safari; an Apple Maps icon is commented out). Use: copy only if you need these marks.
- **app-dock.tsx** — Bottom launcher with 4 lucide icons + labels; active tile `#171717`/white, others `#fafafa`; tooltip pill `background:#fecdd3` (rose-200), text `#262626`. `aria-current="page"`. · Glass & frost · ★
- **editor-tool-dock.tsx** — Vertical tool strip (select/draw/generate/audio + rose-200 "All tools" folder button); hover `scale(1.1)`. `background:rgba(255,255,255,.5)`. · Glass & frost · ★ (vertical chart-tool strip)
- **mac-dock.tsx** — The reference dock: absolute frosted backdrop layer behind 6 brand icons; each tile 44px `border:1px solid rgba(255,255,255,.2); background:rgba(255,255,255,.5); backdrop-filter:blur(24px)` with `shadow-xs` tinted 5%; tooltip `#0a0a0a`/white. Renders `<a>` (next/link) or `<button>` when href is "#". · Glass & frost · ★
- **presence-dock.tsx** — Pill (60px tall) of overlapping 44px avatars (`margin-left:-10px; border:2px solid #fff`, tones rose-400/sky-400/amber-400/emerald-400) with 10px online dots `#34d399`, "+N" chip, and a frosted dropdown list (`background:rgba(255,255,255,.9)`, opens `scale(.95)→1` + fade 200ms `transform-origin:top`). Hover `scale(1.02)`. · Glass & frost
- **spotlight-bar.tsx** — ⌘K command bar: frosted input row + `<kbd>` hint (hidden <768px), listbox of actions with shortcut kbds; ArrowUp/Down navigate, Esc closes. · Glass & frost · ★ (token search / command palette)
  - kbd `border:1px solid #f5f5f5; background:#fafafa; border-radius:6px; padding:2px 6px; font-size:10px; color:#737373`; active option `#f5f5f5`; `role=listbox/option`.

### dropdowns (7)

Shared behaviour: `aria-haspopup="menu"`, `aria-expanded`, `role=menu/menuitem(/menuitemradio)`, close on outside `mousedown` and on `Escape`, trigger opens on Enter/Space. Panel recipe: `background:#fff; border:1px solid #f5f5f5; border-radius:12px; padding:4px; box-shadow:0 20px 50px -12px rgba(0,0,0,.05)`. Rows `padding:8px 10px; border-radius:8px; font-size:12px; font-weight:500; color:#404040`, hover `#fafafa`; danger rows `color:#ef4444`, hover `#fef2f2`, icon `#f87171`; separators `<hr>` 1px `#f5f5f5` with 4px margins; shortcuts as `<kbd>` mono 9px `#a3a3a3`. Neutral product UI throughout. ★ all.

- **file-menu-dropdown.tsx** — Context menu (right-click or tap a cyan-200 folder tile) centred over the trigger: Edit/Duplicate/Pin/Move/—/Delete with shortcuts. · ★
- **filter-sort-dropdown.tsx** — "Native select" look: 208px trigger with small label above value + rotating chevron; menu exactly trigger width, `top:calc(100% + 4px)`, `box-shadow:0 8px 24px -8px rgba(0,0,0,.1)`; options mark the active one with `border-left:2px solid #262626` + `#fafafa`. · ★ (sort by volume/mcap)
- **kebab-actions-dropdown.tsx** — Row card with a ⋮ button; menu expands *inside* the same 224px card (no overlay), card gains the panel shadow when open. · ★ (row actions on mobile, avoids clipping)
- **notification-dropdown.tsx** — 40px bell button with `#262626` 16px unread badge (`9+` cap, 8px bold), panel is an inset grey tray `#fafafa; border-radius:12px; padding:8px; width:240px (256px ≥768px)`; unread rows are white cards `border:1px solid #e5e5e5`, read rows transparent; `max-height:208px; overflow-y:auto`; "Clear" action; empty state "Nothing new". · ★ (price-alert inbox)
- **share-menu-dropdown.tsx** — 224px panel with a horizontal rail of brand icons (X, LinkedIn, GitHub, Discord) and a full-width "Copy link" button that flips to "Copied". Uppercase 10px eyebrow `letter-spacing:.025em`. · ★
- **user-menu-dropdown.tsx** — Pill trigger (48px, avatar + name + email + chevron), menu with a 10px rotated-square caret and a soft "spring" entry. · ★
  - entry via `@starting-style{opacity:0; transform:translateY(-4px) scale(.96); filter:blur(3px)}` → `opacity:1; transform:none; filter:blur(0)` over 300ms `cubic-bezier(.22,1,.36,1)`, `transform-origin:top`; caret `top:-5px; rotate(45deg); border:1px solid #f5f5f5; border-right:0; border-bottom:0; background:#fff`; row icons `scale(1.05)` on hover; chevron `rotate(180deg)` when open, `translateY(1px)` on hover.
- **workspace-switcher-dropdown.tsx** — 224px bar trigger (initial tile + name + plan + ChevronsUpDown) expanding inline; active row `#fafafa`; "Create workspace" row with plus. Open shadow `0 12px 32px -12px rgba(0,0,0,.1)`. · ★ (wallet/account switcher)

### forms (5)

Shared: card `background:#fff; border-radius:24px; padding:24px (32px ≥768px); max-width:448px`; title `24px/600; letter-spacing:-.025em; color:#0a0a0a`; subtitle `14px/24px #737373`; labels `14px/500 #171717; margin-bottom:6px`; inputs `height:44px; border:1px solid #e5e5e5; border-radius:6px; padding:0 14px; font-size:14px`, focus = border `#171717` only (no ring), error border `#fda4af` (focus `#fb7185`), error text `12px #e11d48` with `role=alert` and `aria-describedby`; primary submit `height:44px; width:100%; background:#0a0a0a; border-radius:6px; 14px/600 white`, hover `#262626`, busy shows a spinning `Loader2` and "…ing" label, `disabled{opacity:.6}`. Status callouts use `border-left:2px solid` + tinted fill: error `#f43f5e` on `#fff1f2` text `#be123c`; success `#10b981` on `#ecfdf5` text `#047857`. Success screens use `role=status aria-live=polite`. Neutral product UI. Validation is client-side regex + length rules.

- **contact-form.tsx** — Name/email (2 cols ≥768px), subject, message with live character counter (`tabular-nums`, sr-only count for SR), hidden honeypot field `name="company"` (`.sr-only`, `autocomplete=off`). · ★ (bug-report / feedback form)
- **forgot-password-form.tsx** — Email-only reset; success state shows the address in a mono emerald callout and a "Back to sign in" link with chevron. Back link uses `<a>` or `<button>` when href is "#".
- **login-form.tsx** — Email + password with show/hide eye toggle (28px button inside right edge, `aria-label` switches), "Forgot password?" link, remember-me checkbox (`accent-color:#171717`), sign-up prompt. `inputmode=email`, `autocomplete=current-password`.
- **newsletter-form.tsx** — Email + Subscribe in one row ≥768px (stacked on mobile), privacy note linked via `aria-describedby`. · ★ (alert sign-up)
- **signup-form.tsx** — Name, email, password (≥8 chars + number + symbol), confirm, terms checkbox with inline links. `autocomplete=new-password`.

### inputs (14)

Shared field anatomy (the library's "product register"): label `14px/500 #171717` + optional rose `*` (`aria-hidden`), control `height:40px; border:1px solid #e5e5e5; border-radius:8px; background:#fff; padding:0 14px; font-size:14px; color:#171717; placeholder #a3a3a3`, `transition:border-color 200ms`, **focus = `border-color:#171717`, `outline:none; box-shadow:none`** (explicit "no ring" rule); error border `#fda4af` → focus `#fb7185`; disabled `background:#fafafa; color:#a3a3a3; cursor:not-allowed`; hint `12px #737373` and error `12px #e11d48 role=alert`, both wired with `aria-describedby`. Popovers: `margin-top:6px; border:1px solid #e5e5e5; border-radius:8px (12px for calendar); box-shadow:0 1px 3px rgba(0,0,0,.1),0 1px 2px -1px rgba(0,0,0,.1)` (`shadow-sm`); highlighted option `#fafafa`. Neutral product UI. ★ all (inputs in scope).

- **checkbox-field-input.tsx** — Custom 16px checkbox: real input `opacity:0` stacked over a styled box; checked `#171717` + white check; `peer-focus` darkens border; error variant rose. · ★
- **combobox-field-input.tsx** — Filterable combobox (WAI-ARIA 1.2 pattern): `role=combobox aria-autocomplete=list aria-expanded aria-controls aria-activedescendant`, `role=listbox/option`, ArrowUp/Down/Enter/Escape, outside `pointerdown` closes, hidden input for form submit, empty state "No results found.", list `max-height:224px; overflow:auto`, chevron `rotate(180deg)`. · ★ (token picker)
- **date-field-input.tsx** — Button-trigger date picker opening a `role=dialog` month grid (Su–Sa, 36px cells radius 8px, outside-month `#d4d4d4`, selected `#171717`), footer "Today"/"Clear" text buttons; hidden native input for forms; keyboard opens on Enter/Space/ArrowDown. · ★
- **file-upload-field-input.tsx** — 4:3 drop zone with a faint 3×3 grid (`border:1px solid rgba(245,245,245,.9)` cells) and four 20px corner brackets (`border-top:2px solid #d4d4d4; border-left:2px…`, hover `#737373`), centre serif headline ("Drop files here" / "Release to upload"), dark "Browse" button, accepted-type chips (`border-radius:9999px; 10px uppercase; letter-spacing:.025em`). Validates type (`.ext`, `type/*`) and size, image/PDF previews, removable file rows (`rgba(250,250,250,.8)` card, `border:1px solid #f5f5f5; border-radius:12px`, 48px thumb). Dragging: border `#171717`, icon tile `scale(1.05)`. · Grid & grain light
- **floating-label-field-input.tsx** — 48px input whose label sits centred and floats to the top border on focus/value: label `top:50%→0; translateY(-50%); font-size:14px→12px; background:#fff; padding:0 4px`, 200ms ease-out; input `padding-top:16px; padding-bottom:8px; border:#d4d4d4`. · ★
- **input-group-field.tsx** — Input with addon segments: left prefix (`https://`, mono, `background:#fafafa; border-right:1px solid #e5e5e5; padding:0 12px; color:#737373`) and optional suffix; focus via `:focus-within` on the wrapper. · ★ (amount + token-symbol suffix)
- **password-field-input.tsx** — Password with 24px show/hide toggle (hover `#f5f5f5`). · ★
- **phone-field-input.tsx** — Mono dial-code prefix + `type=tel inputmode=tel`; US numbers auto-format `(555) 123-4567`, 15-digit cap. · ★
- **radio-group-field-input.tsx** — Card-style radios in a `<fieldset>/<legend>` with `role=radiogroup`; each option `border:1px solid #e5e5e5; border-radius:8px; padding:12px 14px`, selected `border-color:#171717; background:#fafafa`; 16px ring dot `border:2px` with inner 8px dot `scale(0→1)` 150ms; vertical or horizontal (row ≥768px, `min-width:176px`). · ★ (order type: market/limit)
- **search-input.tsx** — Search with left icon (`padding-left:40px`), clear "×" button, hides WebKit cancel/decoration (`::-webkit-search-cancel-button{display:none}`), resets on parent form `reset`. `type=search role=searchbox`, sr-only label. · ★
- **select-field-input.tsx** — Custom listbox select mirroring a hidden native `<select>` (`tabindex=-1`, sr-only) for forms; keys ArrowUp/Down/Home/End/Enter/Space; same popover recipe. · ★
- **switch-field-input.tsx** — Label + hint left, 44×24 switch right: `role=switch aria-checked`, track `border:2px solid; border-radius:9999px`, off `#f5f5f5/#e5e5e5`, on `#171717`, 16px white thumb `translateX(20px)` 200ms; hidden input `value=on` for forms. · ★ (alert on/off)
- **text-field-input.tsx** — Base text field (the anatomy above). · ★
- **textarea-field-input.tsx** — Textarea `min-height:96px; resize:vertical; line-height:1.625` with counter that turns `#d97706` at the limit. · ★

### frames (5)

Media frames that wrap any `<img>/<video>/<iframe>` child (`.slot img{display:block;width:100%;height:100%;object-fit:cover}`) and show an SVG skeleton with `animation:pulse` (only under `prefers-reduced-motion: no-preference`, Tailwind `motion-safe:`) when empty.

- **circle-cut-frame.tsx** — White mat with scalloped / stamp-perforated edges on all four sides. · Paper editorial
  - edge strips 8px outside the frame: top `background:radial-gradient(circle at 8px 0,transparent 6px,#fff 6px) 0 0/16px 8px`; bottom `circle at 8px 8px`; left `circle at 0 8px` size `8px 16px`; right mirrored. Frame `padding:16px; box-shadow:shadow-md` (`0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -2px rgba(0,0,0,.1)`). Colour configurable.
- **hard-shadow-polaroid-frame.tsx** — Neo-brutal polaroid: 1px `#171717` border, offset solid shadow, mono caption. · Hand-made (neo-brutal / halftone / sketch)
  - `box-shadow:<offset>px <offset>px 0 0 #171717` (offset prop); inner media `border:1px solid #171717; aspect-ratio:3/4`; caption mono 13px `letter-spacing:.025em`, `padding-bottom:36px`.
- **sticky-note-polaroid-frame.tsx** — Polaroid with a rotated lime sticky note clipped on with an SVG paperclip, handwritten text. · Paper editorial
  - note `#d4f84c`, `width:40%; transform:rotate(<n>deg); transform-origin:top right; box-shadow:1px 4px 12px rgba(15,23,42,.16)`; card `box-shadow:0 1px 2px rgba(15,23,42,.05),0 10px 24px rgba(15,23,42,.12),0 22px 48px -6px rgba(15,23,42,.1)`; handwriting stack `"Segoe Script","Bradley Hand","Snell Roundhand","Apple Chalkboard",cursive`; note text 10px `line-height:1.18; -webkit-line-clamp:5`.
- **transform-box-frame.tsx** — Design-tool selection box: 1px lines inset 7px and four 14px white square handles with `#171717` borders; mono caption. · Neutral product UI (editor chrome)
  - handle `box-shadow:0 1px 0 rgba(0,0,0,.05)`; caption 10px mono uppercase `letter-spacing:.16em #a3a3a3`; default `aspect-ratio:16/9; max-width:576px`.
- **transform-plus-frame.tsx** — Same idea with 16px "+" crosshair marks (stroke 2, `shape-rendering:crispEdges`) at the corners and 8px inset edges. · Neutral product UI · ★ (crosshair framing for chart panels)

### gallery (10)

- **film-strip-card.tsx** — 35mm strip: `#171717` band with 8 sprocket holes per side (`6×8px #404040 radius 4px`, `justify-content:space-evenly`), frames 64×80 (80×96 ≥768px) with `2px #262626` borders and mono frame numbers on `rgba(0,0,0,.6)`. · Carbon spotlight dark
- **gallery-grid-card.tsx** — White card: 3-col grid with a 2×2 hero tile, last tile has `rgba(0,0,0,.5)` "+21" overlay; images `scale(1.05)` on hover 500ms. · Neutral product UI
- **gallery-wall-card.tsx** — Framed artwork: white frame `padding:12px; border-radius:4px; box-shadow:0 16px 34px rgba(15,23,42,.12)`, inner mat `#f7f4ef`, serif-italic title, 10px uppercase `letter-spacing:.2em` gallery label. · Paper editorial
- **glass-overlay-image-card.tsx** — 288×320 photo card with frosted info panel and frosted round icon buttons. · Glass & frost
  - panel `border:1px solid rgba(255,255,255,.25); background:rgba(255,255,255,.15); backdrop-filter:blur(24px); border-radius:16px; padding:16px`; icon buttons 32px `border:1px solid rgba(255,255,255,.3); background:rgba(255,255,255,.2); backdrop-filter:blur(12px)`; image hover `scale(1.1)` 700ms; avatar stack `margin-left:-10px`; mono CTA 10px uppercase `rgba(255,255,255,.5)`.
- **museum-placard-card.tsx** — Click-to-flip placard (front: label on `#faf8f5`; back: curator note on slate `#e8edf3`). · Paper editorial
  - container `perspective:1000px`; inner `transform-style:preserve-3d; transition:transform 500ms`, flipped `rotateY(180deg)`; faces `backface-visibility:hidden`; mono 9px uppercase `letter-spacing:.22em`; hover hint fades in.
- **photo-album-card.tsx** — Tap-left/right-third carousel with crossfading images (300ms) and pill pagination dots (`6px` → active `20px #171717`). · Neutral product UI
- **photo-contact-sheet-card.tsx** — 2×2 contact sheet on `#f5f5f5`, `border:1px solid #d4d4d4`, bold 8px frame numbers on `rgba(255,255,255,.9)`, mono uppercase roll label. · Paper editorial
- **polaroid-image-card.tsx** — Polaroid tilted -2deg straightening on hover, image `filter:sepia(.15)` → 0. · Paper editorial
  - `background:#fff; padding:12px 12px 40px; box-shadow:0 8px 30px rgba(0,0,0,.12)`; serif italic caption + mono date.
- **slow-living-polaroid-card.tsx** — Magazine card on oxblood `#4a2525` with a taped polaroid (`rotate(6deg)`) and mono lowercase copy in cream tones (`#efe6dc #e8ddd4 #f3ebe3 #faf5ef`). · Paper editorial (dark warm)
  - tape `#d9c9a3; rotate(-14deg); clip-path:polygon(4% 18%,12% 2%,88% 8%,96% 22%,92% 88%,84% 98%,14% 94%,2% 78%)`; polaroid `box-shadow:0 14px 28px rgba(0,0,0,.32)`; meta 8px mono `letter-spacing:.14em; line-height:1.6`.
- **stamp-postcard-card.tsx** — Postcard: image top, rotated dashed stamp (`2px dashed #b4b1ac` on `#f6f2eb`, `rotate(3deg)`), message/address split by a 1px rule; paper `#fffef8`. · Paper editorial

### loaders (3)

- **apple-hello-loader.tsx** — Black tile cycling greetings (hello, bonjour, hola, ciao, olá, namaste) with fade+rise. · Carbon spotlight dark · ★ (splash / first-load)
  - text `18px; font-weight:200; letter-spacing:-.025em; color:#fff; text-transform:capitalize`; swap every 2600ms with 400ms fade, `opacity:0; translateY(4px)` → visible over 500ms; `role=status aria-live=polite`; listens to `matchMedia('(prefers-reduced-motion: reduce)')` (incl. `change`) and stops cycling. `fill` prop makes it `position:absolute; inset:0`.
- **spin-loader.tsx** — lucide spinner (sm/md/lg) `color:#171717; animation:spin 1s linear infinite`, off under reduced motion; accessible label "Loading". · Neutral product UI · ★
- **text-loader.tsx** — "Searching" text whose letters pulse in a wave next to a glowing rotating orb; variants default / sunset / ocean / neon. · Carbon dark luxe · ★ (AI/search busy state)
  - letters `opacity:.4; animation:pulse 1.8s` with `animation-delay:i*0.09s`; orb 20px circle animated via Web Animations API `node.animate([{transform:'rotate(90deg)',boxShadow:s0},{transform:'rotate(270deg)',boxShadow:s1,offset:.5},{transform:'rotate(450deg)',boxShadow:s2}],{duration:1500,iterations:Infinity,easing:'linear'})`; default shadows `0 1px 1px 0 #fff inset, 0 3px 5px 0 #ff5f9f inset, 0 4px 4px 0 #0693ff inset` → `…#d60a47…#fbef19` → `…#ff5f9f…#28a9ff`; sunset `#fb923c/#f97316`, `#ea580c/#fbbf24`, `#fb923c/#fdba74`; ocean `#22d3ee/#0284c7`, `#06b6d4/#38bdf8`, `#22d3ee/#7dd3fc`; neon `#4ade80/#22d3ee`, `#22c55e/#2dd4bf`, `#4ade80/#38bdf8`. Reduced motion: no animation, static `rotate(270deg)`.

### mockups (6)

Device frames that take arbitrary children as the screen. Mostly decorative; useful for a marketing/landing page, not the dashboard itself.

- **apple-ipod-mockup-card.tsx** — 220px iPod Classic with click wheel (MENU, ⏪ ⏩ ▶❚❚ glyphs at 6–8px), 7 finishes: silver `#e8e8ec`, black `#2a2a2e`, white `#f2f2f6`, pink `#eec0cc`, blue `#a8c8e8`, green `#a8d4a8`, red `#e07070` (wheel and centre one step lighter). · Tactile 3D keys (product)
  - frame `border-radius:1.35rem; padding:.625rem`, screen radius `calc(1.35rem - .625rem)` (concentric radii), screen `box-shadow:inset 0 0 0 1px rgba(0,0,0,.06)`, body `0 8px 24px rgba(0,0,0,.07)`; screen aspect 1.32.
- **apple-watch-mockup-card.tsx** — Detailed Apple Watch (300px, aspect 486/729) in 7 metal finishes, SVG straps with highlight gradients, digital crown with ridges, layered bezel. · Carbon dark luxe (metal)
  - case gradients e.g. black `linear-gradient(135deg,#050505 0%,#383838 16%,#111 38%,#4a4a4a 58%,#090909 82%,#303030 100%)`, silver `linear-gradient(135deg,#727272 0%,#f5f5f5 15%,#a9a9a9 34%,#fafafa 51%,#888 72%,#ededed 87%,#777 100%)`, gold `#967b4c→#ead39a→#c2a665→#f1d99d→#aa8b50→#dfc486→#8b7246`; crown ridges `repeating-linear-gradient(to bottom,#777 0 1px,#ededed 1px 2px)`; bezel `linear-gradient(145deg,#555 0%,#080808 8%,#000 30%,#020202 70%,#333 94%,#080808 100%)` + `inset 0 2px 3px rgba(255,255,255,.16),inset 0 -2px 4px rgba(0,0,0,.9)`; glass glare `linear-gradient(120deg,rgba(255,255,255,.42),transparent 24%,transparent 70%,rgba(255,255,255,.18))`. Ring-draw keyframes live in globals.css (`watch-ring-draw-*`, stroke-dasharray 0→121/163 etc.).
- **browser-mockup-card.tsx** — Browser window with traffic lights (8px `#f87171 #fbbf24 #34d399`), mono 7px URL bar; themes light / dark (`#262626` chrome, `#0a0a0a` content) / glass (`rgba(255,255,255,.4)` chrome + `backdrop-filter:blur(8px)`). Inner radius `calc(.75rem - 1px)`. · Neutral product UI
- **laptop-mockup-card.tsx** — MacBook (280px, 384px ≥768px) with 10 finishes (gray, space gray `#8a8580→#6a6560`, silver, plum `#5a515f→#403948`, copper `#dc9268→#c26f45`, rose, midnight `#34343c→#1c1c22`, starlight, sky, gold `#e8c563→#d4a93f`), base `linear-gradient(to bottom,…)` + notch. · Neutral product UI
- **phone-mockup-card.tsx** — iPhone (256px, aspect 70.6/146.6) with side buttons, Dynamic Island (66×20px black pill, 8px camera `rgba(106,144,200,.2)`), home indicator; 5 finishes (`#4a4254 #d4845a #e4e4e8 #9a9590 #d49aa8`); `cropRatio` shows only the top fraction. · Neutral product UI · ★ (mobile screenshot frame for docs)
  - frame `border-radius:2.6rem; padding:2px` → black `2.5rem` → screen `inset:3.5px; border-radius:2.3rem`.
- **tablet-mockup-card.tsx** — iPad Air (320/380px, aspect 178.5/247.6) with top buttons, camera dot, 8 metallic `linear-gradient(to bottom,…)` finishes, glass sheen `linear-gradient(to top right,transparent,rgba(255,255,255,.06),transparent)`; `box-shadow:0 25px 50px -12px rgba(0,0,0,.25); outline ring 1px rgba(0,0,0,.1)`. · Neutral product UI

### system (2)

Site infrastructure, not visual components.

- **system/analytics/tracker.tsx** — Calls `trackPageView(pathname)` on route change; renders nothing. Not portable (Next.js router + site analytics). · n/a
- **system/loaders/page-loader-overlay.tsx** — Full-screen white overlay (`position:fixed; inset:0; z-index:50; background:#fff`) with a 28px `#171717` spinning lucide `Loader`, `aria-busy=true aria-label=Loading`. · Neutral product UI · ★

### notifications (10)

Shared "iOS banner" recipe: `<output>` element (implicit live region) `width:320px; border-radius:1.25rem; border:1px solid rgba(255,255,255,.7); background:rgba(255,255,255,.9); backdrop-filter:blur(24px); box-shadow:0 8px 32px -4px rgba(0,0,0,.10)`; layout `display:grid; grid-template-columns:2.375rem minmax(0,1fr); column-gap:12px; row-gap:4px; padding:12px 36px 12px 14px`; 38px app tile `border-radius:.625rem` (solid colour + white lucide icon, `shadow-sm` + 1px `rgba(0,0,0,.02)` ring) spanning two rows; title 13px/600 `#171717`; time 11px `#a3a3a3`; body 13px `line-height:1.38; color:#404040; -webkit-line-clamp:2`. Close: 24px round × button top-right, hover `rgba(0,0,0,.05)`.
Motion state machine `data-phase="open|closing|closed"`: enter with `@starting-style{opacity:0; transform:translateY(-10px)}` over 340ms `cubic-bezier(.25,.46,.45,.94)`; closing `translateY(-8px); opacity:0` over 260ms `cubic-bezier(.4,0,.6,1)`, then unmount after `EXIT_MS=260`; a "Show notification" pill (`#f2f2f7`, hover `#e8e8ed`) re-opens it. Glass & frost. ★ all (alerts are in scope; swap the app tile for a token logo / up-down arrow).

- **apple-notification-banner.tsx** — Message from a person: avatar tile, "Sarah: message…". · ★
- **calendar-reminder-notification-banner.tsx** — Red tile `#ef4444` with calendar icon, "Design review starts in 15 minutes". · ★ (unlock/listing reminder)
- **chat-bubble-notification-banner.tsx** — Not glass: 28px avatar + sender label + bubble `background:#f5f5f5; border-radius:16px 16px 16px 6px` (`rounded-2xl rounded-bl-md`), 12px text; close button white circle offset `-4px`; enters `translateY(8px)` 300ms ease-out. · Neutral product UI
- **delivery-notification-banner.tsx** — Flex row (not grid) with 40px `#f0f9ff` tile + `#0284c7` package icon, status/ETA/order id. · ★ (order filled / tx confirmed row)
- **deploy-notification-banner.tsx** — Dark `#171717` tile with inline Vercel triangle; "app-ui is live on production (main)". · ★
- **email-notification-banner.tsx** — Mail: avatar, bold sender, subject, preview clamped to 3 lines. · ★
- **incoming-call-notification-banner.tsx** — Caller card with 44px avatar (`box-shadow:0 0 0 2px #f5f5f5`), 15px name, two full-width pill actions Decline `#ef4444` (hover `#dc2626`) / Accept `#10b981` (hover `#059669`). · ★ (two-action confirm banner)
- **payment-notification-banner.tsx** — Emerald `#10b981` banknote tile; "**$128.00** received from Acme Corp". · ★ (deposit received)
- **system-alert-banner.tsx** — Amber `#fbbf24` warning tile; Settings-style storage warning. · ★ (risk / warning alert)
- **toast-notification-banner.tsx** — Bottom snackbar: `max-width:320px; border-radius:12px; border:1px solid rgba(229,229,229,.8); background:rgba(255,255,255,.95); backdrop-filter:blur(24px); box-shadow:0 4px 24px -2px rgba(0,0,0,.10),0 0 0 1px rgba(0,0,0,.02)`, 20px emerald check dot, optional action link `#0284c7` 13px/600 ("Undo"), slides up from `translateY(12px)`. · ★ (copied / saved toast)

### others (5)

- **progress-ring-card.tsx** — 256px card: 112px SVG ring (r=40, stroke 6, track `#f5f5f5`, gradient stroke `#14b8a6→#06b6d4`) + clickable stage bars (6px tall, `#10b981`/`#14b8a6`/`#e5e5e5`). · Neutral product UI · ★ (portfolio allocation / progress)
  - ring `transform:rotate(-90deg)`, `stroke-dashoffset` animated 700ms ease-out; centre value 24px/300; `role=img` with aria-label; mono 10px uppercase `letter-spacing:.1em` eyebrow; active stage row `#f0fdfa`.
- **stacked-cards-effect.tsx** — Card with two cards peeking behind (`rotate(-6deg)` `#e5e5e5`, `rotate(3deg)` `#f5f5f5`) that fan further on hover (-8deg / 5deg) while the front lifts 4px; 500ms. · Neutral product UI
- **terminal-log-card.tsx** — macOS terminal: `#0d0d0d`, `border:1px solid #262626; border-radius:12px; box-shadow:0 25px 50px -12px rgba(0,0,0,.4)`, traffic lights `#ff5f57 #febc2e #28c840`, mono 11px lines coloured by type (cmd `#34d399`, out `#737373`, ok `#38bdf8`, err `#fb7185`), blinking block cursor `6×12px #34d399 animate-pulse`. · Carbon spotlight dark · ★ (activity / tx log)
- **thermal-receipt-card.tsx** — Mono receipt on `#faf8f2` with torn/scalloped top and bottom edges, dashed rules, bold total, QR icon. · Paper editorial · ★ (trade receipt idea)
  - edges `radial-gradient(circle at 8px 0,transparent 6px,#faf8f2 6px) 0 0/16px 8px` (top) and `circle at 8px 8px` (bottom), 8px strips at `top/bottom:-8px`; store name `11px bold; letter-spacing:.2em`; rules `border-top:1px dashed #d4d4d4`.
- **weather-snapshot-card.tsx** — Weather card, clear (amber `#fffbeb` / `#fef3c7` border / text `#451a03`) or rain (sky `#f0f9ff` / `#bae6fd` / `#082f49`); 48px/300 temperature with raised `°`; 2-cell footer drawn with `gap:1px` over a coloured background (hairline grid trick). · Pastel aurora (tinted)

### otp (2)

- **otp-boxed-input.tsx** — Full OTP flow: icon, serif title "Check your email", masked destination, N boxes, progress dots, resend with countdown. · Neutral product UI · ★ (2FA / withdraw confirm)
  - boxes `48px (56px ≥768px); border:2px solid #f5f5f5; border-radius:12px; background:rgba(250,250,250,.3); font:600 24px mono`; focus `border-color:#171717; background:#fff`; filled `#171717` border; active box `scale(1.05)`; fake caret `2×24px #a3a3a3 animate-pulse`; dots 6px `#e5e5e5` → filled `#171717 scale(1.25)`, active `scale(1.5)`, complete `#10b981`, error `#fb7185`. Behaviour: `autocomplete="one-time-code"` on first box, `inputmode=numeric pattern=[0-9]*` (or alphanumeric uppercase), paste distributes, ArrowLeft/Right/Home/End/Backspace/Delete, `role=group` with `aria-labelledby/-describedby`, error `role=alert`, error wraps group in `1px #fecdd3` border.
- **otp-underline-input.tsx** — Minimal OTP: 40px-wide underline fields `border-bottom:2px solid #e5e5e5` with an animated focus bar `height:2px; background:#171717; transform:scaleX(0→1); transform-origin:center` 300ms on `peer-focus`. · Neutral product UI · ★

### pricing (2)

- **retail-price-tag-card.tsx** — Hanging price tag on a string (`1px #d6d3d1`, 12px grommet), tilted `-2deg`, stone palette (`#fafaf9→rgba(245,245,244,.9)` gradient, text `#57534e/#292524`), struck-through original price, discount badge, 24-bar CSS barcode (`1px` bars alternating `rgba(120,113,108,.7)`/transparent). · Paper editorial
- **toggle-pricing-cards.tsx** — Monthly/Yearly switch (44×24, on `#262626`, thumb `translateX(22px)`) with "-20%" emerald label; three compact plan cards, popular one inverted `#171717` with teal-300 mono badge and teal-400 checks. · Neutral product UI
  - plan cards `flex:1; border:1px solid #f5f5f5; border-radius:12px; padding:12px`, price 18px/300.

### profile (4)

- **contact-profile-card.tsx** — Museum-placard directory entry on `#faf8f5`: mono 9px uppercase labels (`letter-spacing:.18em`) in a `5.5rem 1fr` grid, serif name, `mailto:`/`tel:` links. `<article>`. · Paper editorial
- **editorial-staff-profile-card.tsx** — Numbered roster row: `border-left:2px solid #171717`, mono index "01", serif 24px name, 10px uppercase role `letter-spacing:.16em`, square 56px portrait with 1px border. · Paper editorial
- **team-member-profile-grid.tsx** — `<section>` with mono eyebrow + serif 30px heading, 1→3 column grid of square-cornered bordered cards (`border:1px solid #e5e5e5; padding:20px`), "View profile" link pinned to bottom with `margin-top:auto`. · Paper editorial
- **user-profile-card.tsx** — Author byline card on warm paper `#f6f2eb`, square portrait, mono labels, links with `ArrowUpRight` nudging `translate(1px,-1px)` on hover. · Paper editorial

### resources (1)

- **resource-links-panel.tsx** — Link list rows: 20px icon/letter, "**Name** / description" with a hostname in mono on the right; layout switches at a custom 500px breakpoint (`min-[500px]` / `max-[499px]`); external links `target=_blank rel="noopener noreferrer"`. · Neutral product UI · ★ (useful-links / explorers panel)

### socials (10)

Shared "social card" recipe: `background:#fff; border:1px solid #f5f5f5; border-radius:12px–16px; padding:16px–20px; box-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1)`; avatar placeholder `#262626` circle; meta 10–12px `#a3a3a3`; counts `toLocaleString()`; action rows split by `border-top:1px solid #f5f5f5`. Neutral product UI. These imitate third-party brands (X, Facebook, LinkedIn, Instagram, Threads, Discord, GitHub) — reuse the layout, not the branding.

- **discord-chat-card.tsx** — Mini channel: header with Discord mark `#5865F2`, scrollable message list (`max-height:160px`, scrollbar hidden via `scrollbar-width:none; -ms-overflow-style:none; ::-webkit-scrollbar{display:none}`), composer input `#f5f5f5` (focus `#fafafa`) + `#5865F2` send button; Enter sends. · ★ (chat/notes pattern)
- **facebook-post-card.tsx** — Post with header, text, 144px image, reaction chips (16px blue/rose circles overlapping `margin-left:-4px`), Like/Comment/Share row with hover `#fafafa`.
- **github-contribution.tsx** — GitHub-style 53-week heatmap with year dropdown and a custom hover-only scrollbar. · ★ (activity heatmap: trades per day, volume per day)
  - cells 10×10 `border-radius:2px`, gap 3px (column pitch 13px), levels `#ebedf0 #9be9a8 #40c463 #30a14e #216e39`; each cell is an `<img>` whose `src` is a data-URI SVG rect, so every cell carries a real `alt` ("3 contributions on Jun 4, 2026 — user"); month labels absolutely placed at `week*13px`, weekday labels Mon/Wed/Fri; Less→More legend; year dropdown merges into its menu (`border-radius:6px 6px 0 0`, menu `top:calc(100% - 1px); border-top:0`), with hidden native `<select>` mirror. `LocalScrollHoverArea`: native scrollbar hidden (`scrollbar-width:none`, `margin-bottom:-16px; padding-bottom:16px` clip trick), a 4px `#a3a3a3` thumb computed from scroll metrics fades in on `group-hover` (150ms); listeners `passive:true`. Card `border-radius:24px`.
- **github-repo-card.tsx** — owner/name, visibility pill (`border:1px solid #e5e5e5; border-radius:9999px; 9px`), description, language dot, stars/forks, Star toggle (`#fffbeb`/`#b45309`, icon `fill:#f59e0b`). · ★ (token info card layout)
- **instagram-post-card.tsx** — Story-ring avatar (`linear-gradient(to top right,#facc15,#ec4899,#2563eb)` 2px ring + white 2px gap), image, action icons, likes, caption with blue hashtags, uppercase timestamp.
- **linked-in-post-card.tsx** — Post with link-preview box (`border:1px solid #e5e5e5; background:#fafafa; border-radius:8px; padding:12px`) and 4 stacked icon+label actions.
- **linked-in-profile-card.tsx** — Cover 80px + 64px avatar overlapping (`bottom:-32px; border:4px solid #fff`), Connect (`#262626` pill) / Message (outline pill), 3-stat footer (bold value + 10px uppercase label). · ★ (stat footer pattern)
- **threads-post-card.tsx** — Avatar with a vertical 1px thread line below it, 16:10 media, Like/Reply/Repost/Share counters (`tabular-nums`), like `aria-pressed` filling rose.
- **twitter-post-card.tsx** — Tweet: bold name, handle, text with `#0ea5e9` hashtags, action row coloured on hover (reply sky, repost emerald, like rose).
- **twitter-profile-card.tsx** — Profile with 96px cover, overlapping avatar, Follow pill, location/website/joined meta, following/followers counts.

Note: socials rely on lucide icons and `@/icons/brands/*` SVG marks (GitHub, Discord, X, LinkedIn).

### table (6)

Shared table shell (the closest thing in the library to a dashboard data view): wrapper `width:100%; max-width:448–512px; overflow:hidden; border:1px solid #e5e5e5; border-radius:12px; background:#fff`; header strip `padding:12px 16px; border-bottom:1px solid #f5f5f5` with title `14px/600 #171717` + subtitle `12px #737373`; scroll container `overflow-x:auto` around a `<table>` with `min-width:300–320px; border-collapse:collapse; font-size:14px`; `<th>` `12px/500 #737373; padding:10px 12px` (16px on outer columns); rows `border-top:1px solid #f5f5f5`, hover `rgba(250,250,250,.8)`; cells `padding:12px`; **numbers right-aligned with `font-variant-numeric:tabular-nums`**; secondary columns hidden below 768px (`display:none` → `table-cell` at `md`). Status as 6px dot + 12px label (`#10b981` active, `#d4d4d4` invited). Neutral product UI. ★ all — this is the reference for a mobile token table.

- **customers-table.tsx** — Customer (28px avatar + name + company), plan, last active (≥768px), MRR right-aligned, header total "MRR" with 10px uppercase label; `—` for zero. · ★
- **orders-table.tsx** — Sortable by date / amount / status: header buttons with `ArrowUpDown` (`#d4d4d4`) idle, `ArrowUp/ArrowDown` (`#525252`) active; toggling the same key flips direction, a new key starts `desc`. Customer column hidden <768px. · ★ (sortable columns: price, 24h %, volume)
- **recent-transactions-table.tsx** — Stripe-style list, page size 5 with prev/next 28px icon buttons (`disabled{opacity:.3}`, hover only `:enabled`) and "1–5 of 8"; amounts formatted `+$420` / `−$31.20` (true minus sign U+2212), positives `#171717`, negatives `#737373`; description `max-width:10rem` truncated. · ★ (tx history; swap the grey negative for red/green)
- **tasks-table.tsx** — Checkbox column (16px box, checked `#171717`), done rows `color:#a3a3a3; text-decoration:line-through`, "2 of 6 done" counter, assignee avatar (≥768px). · ★
- **team-members-table.tsx** — Member (32px avatar, name, email), role, status dot, per-row `MoreHorizontal` action button with `aria-label="Actions for …"`, header "Invite" ghost button. · ★
- **users-select-table.tsx** — Bulk select: header checkbox with three states (none / all → check / some → `Minus`), clicking a row toggles it, selected rows `#fafafa`, header shows "N selected". · ★ (watchlist bulk actions)

### users (3)

- **credit-card-glass.tsx** — 320×192 dark card: `linear-gradient(to bottom right,#262626,#171717,#000)` with blurred glows `rgba(20,184,166,.3)` 160px `blur(50px)` (→ .4 on hover, 700ms) and `rgba(6,182,212,.2)` 192px `blur(60px)`, amber chip `linear-gradient(to bottom right,#fcd34d,#f59e0b)`, mono number `18px; letter-spacing:.15em; rgba(255,255,255,.9)`, labels 8px mono `rgba(255,255,255,.3)`, two overlapping 28px circles red/amber at .8. · Carbon dark luxe · ★ (wallet balance card)
- **team-member-card.tsx** — 224×288 photo card: gradient scrim `linear-gradient(to top,rgba(0,0,0,.8),rgba(0,0,0,.2),transparent)`, frosted social buttons sliding in from `translateY(4px)` on hover, bio revealed `translateY(8px)→0` + fade 300ms, image `scale(1.1)` 700ms. · Glass & frost
- **testimonial-card.tsx** — Rotating testimonials: 5 stars `#FFD700`, big faint quote glyph `#f5f5f5`, author row, pill pagination dots + round prev/next. Inline `<style>` keyframes `testimonial-fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}` 0.32s ease-out on each change. Data from `@/lib/home/testimonials` (site-specific). · Neutral product UI

### wallet (1)

- **wallet-pass-card.tsx** — Apple-Wallet-style membership pass that flips on tap: front has a `linear-gradient(to bottom right,#2563eb,#0f766e)` header (mono 10px uppercase pass type, initial tile `rgba(255,255,255,.2)`, 48px avatar), a row of 12 perforation circles (12px white) across the tear line, member ID; back shows a 5×5 CSS "QR" grid (`gap:1px`, dark cells `#171717`, `border-radius:1px`) and the ID in mono. · Neutral product UI (with blue/teal accent) · ★ (wallet / account card, QR for deposit address)
  - container `perspective:1000px`; inner `transform-style:preserve-3d; transition:transform 700ms cubic-bezier(.34,1.2,.64,1)`, `rotateY(180deg)` when flipped; faces `backface-visibility:hidden`; idle "breathing" shadow via inline `@keyframes wallet-flip-shadow{0%,100%{box-shadow:0 10px 30px rgba(0,0,0,.12)}50%{box-shadow:0 18px 40px rgba(0,0,0,.18)}}` 3s ease-in-out infinite (no reduced-motion guard — add one). `aria-label` toggles "Show pass front/back".

### text (10)

- **cafe-menu-board-card.tsx** — Dark menu board `#0a0a0a`, `border:1px solid #262626; border-radius:24px; box-shadow:0 18px 40px rgba(0,0,0,.28)`, amber icon tile `rgba(245,158,11,.15)`/`#fcd34d`, item rows split by `rgba(38,38,38,.8)` rules, prices `#fcd34d` 14px/600. · Carbon spotlight dark · ★ (dark price list rows: name left, price right)
- **cinema-ticket-card.tsx** — Dark ticket `#0a0a0a` with a `#171717` stub on the right: `border-left:1px dashed #404040`, two 16px white notches at top/bottom, vertical text via `writing-mode:vertical-rl; transform:rotate(180deg)`, mono eyebrow `letter-spacing:.25em; color:rgba(245,158,11,.7)`, seats `#fbbf24`. · Carbon spotlight dark
- **daily-motivation-card.tsx** — 384×400 poster on `#f4f4ea`: serif stack 1.85rem `line-height:.92` colour `#2d3e40`, tilted polaroid `rotate(12deg)` with `box-shadow:0 12px 28px rgba(45,62,64,.14)`, lilac sticker pill `background:#e2d9f3; border:4px solid #9f93b8; rotate(-6deg)`. · Paper editorial
- **denim-product-editorial-card.tsx** — Fashion editorial on `#f2f2f2`: two images, serif-italic 11px captions, a rotated (-90deg) dotted leader line with a dotted circle, hand-drawn `LoopArrow` SVG, mono 9px uppercase body `letter-spacing:.04em; line-height:1.65`. · Paper editorial
- **drop-cap-editorial-card.tsx** — Paragraph with a floated 40px drop cap tile (`#171717`, white serif 24px/300, `border-radius:8px`). · Paper editorial
- **editorial-quote-card.tsx** — Quote on `#f6f2eb` with issue eyebrow, one accent word highlighted (`background:rgba(212,212,212,.6); border-radius:4px; padding:0 4px`), rule + right-aligned author. `<blockquote>`. · Paper editorial
- **journal-writing-card.tsx** — Lined notebook textarea: `repeating-linear-gradient(transparent,transparent 27px,#f0f0f0 27px,#f0f0f0 28px)` at `background-position:0 12px` with `line-height:28px` serif text, red margin line `rgba(254,205,211,.8)`, word count, autosave indicator (`animate-ping` amber dot while saving → emerald dot, 900ms debounce, `role=status`). Header strip `#f6f2eb`. · Paper editorial · ★ (trade journal / notes)
- **keyboard-shortcuts-card.tsx** — Shortcut list: rows `#fafafa; border-radius:12px; padding:8px 12px`, keycaps `<kbd>` `height:24px; min-width:24px; border:1px solid #f5f5f5; background:#fff; border-radius:6px; font:500 10px mono; box-shadow:shadow-sm`. · Neutral product UI · ★
- **magazine-cover-card.tsx** — 288×384 image cover with dark scrim, frosted badge pill (`border:1px solid rgba(255,255,255,.2); background:rgba(255,255,255,.15); backdrop-filter:blur(12px); letter-spacing:.1em`), light+bold split headline, round CTA that inverts to white on hover; whole card is a `<button>`. · Glass & frost
- **notepad-card.tsx** — Legal-pad note `#fffdf0`, `border:1px solid #e6e2bc; box-shadow:5px 5px 0 #e6e2bc` (hard offset shadow), olive text `#5c5a4a`/`#a39e76`, mono uppercase heading, square checkboxes `1px #c4bf98`. · Hand-made (neo-brutal, soft)

### travel (2)

- **flight-boarding-card.tsx** — Boarding pass: 80px left stub with vertical label, dashed separator `border-left:1px dashed #e5e5e5`, airport codes 24px/600, dashed route line with plane icon on a white knockout, chips `#f5f5f5` 10px pills, emerald "On Time" pill (`#ecfdf5`/`#059669`). `border-radius:24px`. · Neutral product UI · ★ (A→B swap route layout: TOKEN → TOKEN)
- **travel-postcard-card.tsx** — Vintage postcard `#fffdf5`, `border:1px solid #e8e0d0; box-shadow:4px 4px 0 #e8e0d0`, serif italic title `#3d3530`, mono 10px `letter-spacing:.3em` eyebrow `#a09080`, faint rotated red postmark (`2px solid rgba(248,113,113,.4)`, opacity .3), image `sepia(.2)`. · Paper editorial

### underlines (2)

- **annotated-text.tsx** — Hand-drawn annotations around inline text, 12 variants: `wavy` (default, purple-300), `circle` (cyan-200), `highlight` (yellow-300 @60%, drawn *behind* text), `underline`, `line` (2px straight, neutral-500), `dottedUnderline`, `doubleUnderline`, `strikethrough`, `crossOut` (red-400), `arrow`, `bracket`, `box` (orange-400). · Hand-made (neo-brutal / halftone / sketch) · ★ (highlight a number or a warning in a paragraph)
  - Technique: inline SVG paths with `stroke="currentColor"`, colour set via a text-colour class, positioned absolutely in em units relative to the word (e.g. wavy `bottom:-.4em; left:-2%; height:.7em; width:104%`; circle `inset:-.6em -.55em; width:calc(100% + 1.1em)`), `preserveAspectRatio="none"`, `stroke-width:1.5–3`; roughness from SVG filters defined once: `<filter id="hd-rough"><feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="2" seed="4"/><feDisplacementMap in="SourceGraphic" scale="2.6" xChannelSelector="R" yChannelSelector="G"/></filter>` (soft version: 0.035 / seed 11 / scale 1.5). Dotted underline is pure CSS: `background:radial-gradient(circle,currentColor 1.5px,transparent 1.5px) 0 100%/.5em 100% repeat-x`. Wrapper `position:relative; display:inline-block; white-space:nowrap`; text `z-index:10; color:#0a0a0a`. Static (no draw-on animation).
- **annotated-text-showcase.tsx** — Demo list of 9 variants in a scroll column (hidden scrollbar) + exported usage string. Uses purple-300 for wavy despite the library's no-purple rule. · Hand-made (neo-brutal / halftone / sketch)

### widgets (27)

iOS-home-screen tiles, almost all `176×176px` (`h-44 w-44`). Two shells:
- **Light tile**: `background:#fff; border:1px solid #f5f5f5; border-radius:24px; padding:16px; box-shadow:0 10px 15px -3px rgba(0,0,0,.05),0 4px 6px -4px rgba(0,0,0,.05)` (`shadow-lg shadow-black/5`); eyebrow `10px/600 uppercase letter-spacing:.1em #a3a3a3`; big numbers light-weight (`font-weight:200–300`, `letter-spacing:-.04em`, `tabular-nums`).
- **Mascot face tile** (battery, bluetooth, dnd, heart-rate, recorder, sleep-score, torch, compass): `background:#000; border-radius:1.75rem`, a 176-unit SVG dial (`r=56` centred at 88,84) with a coloured cartoon "mascot" circle (`r≈58`, centred low at y≈142) peeking up from the bottom with simple eyes/mouth, an arc or ring in the accent colour, state text in white / `rgba(255,255,255,.4)`, small lucide icon top-right. Whole tile is a `<button>` toggle where interactive. Palette per tile below.
Clock/timer tiles start with `now = null` and render a grey skeleton bar until mounted (avoids SSR/client mismatch); timers use `requestAnimationFrame`. ★ = useful as a mobile stat tile.

- **analog-clock-widget.tsx** — Live analog clock, variants roman / minimal / numeric: SVG r=46 ring `#f0f0f0`, 12 ticks `#d4d4d4`, hands hour `#171717` (to y=28), minute `#404040` (y=22), second `#ef4444` (y=20) via `transform:rotate(deg 50 50)`, 2px hub. · Neutral product UI
- **audio-recorder-widget.tsx** — Dark `#171717` tile: title/date, 16-ish red `#ef4444` level bars (`width:6px; border-radius:9999px; transition:all 100ms`), mono timer, play/pause circle (`#ef4444` when recording, else `#404040`), `hover scale(1.05) / active scale(.95)`. · Carbon spotlight dark · ★ (mini bar-meter)
- **battery-face-widget.tsx** — Mascot face; lime `#A3E635` healthy, orange `#FB923C` when low (droopy eyes); 68%-of-circle arc `stroke-dasharray:<progress> <circ>` rotated 135deg, track opacity .2; % in 20px/600 tabular. · Mascot face tiles · ★ (gauge pattern: e.g. RSI / fear-greed)
- **blob-profile.tsx** — Avatar clipped to an organic blob `border-radius:60% 40% 55% 45% / 55% 45% 55% 45%`, name with lime `#D9F26D` check. · Neutral product UI
- **bluetooth-face-widget.tsx** — Mascot `#14B8A6`, accent `#22D3EE`; tap toggles On/Off. · Mascot face tiles
- **compass-widget.tsx** — Mascot (violet) under a 60-tick dial with N/E/S/W rotated by `rotate(-heading)`; reads `deviceorientationabsolute`/`deviceorientation` (and `webkitCompassHeading`), requests iOS permission via `DeviceOrientationEvent.requestPermission()` behind an overlay button (`rgba(0,0,0,.5)`); SVG numbers rounded to keep SSR and client identical; status dot `rgba(52,199,89,.5)`. · Mascot face tiles
- **daily-activity-calendar-widget.tsx** — Dark `#171717` month mini-grid: 20px day circles 9px text, active days `#10b981`, highlighted day `#f97316`, month badge pill `#404040`. · Carbon spotlight dark · ★ (streak / trading-days heat)
- **dnd-face-widget.tsx** — Do-Not-Disturb mascot `#A78BFA`, accent `#C4B5FD`, moon icon; off state `rgba(255,255,255,.4)`. · Mascot face tiles
- **electric-scooter-widget.tsx** — 288px horizontal ride summary: image tile `#fafafa` + 3-column stat strip (9px labels / 10px/600 values) under a rule. · Neutral product UI · ★ (3-stat strip)
- **flight-arrival-widget.tsx** — Dark `#171717` tile: "Arrival in 42min" 24px bold, progress bar = solid `#f97316` half + dashed `#525252` half with a 24px plane badge `#262626`/`#fb923c` at the joint. · Carbon spotlight dark
- **focus-breath-widget.tsx** — Breathing circle: 96px `#f5f5f5` disc scales `1 ↔ .75` with `transition:transform 4000ms ease-in-out` every 4s, inner 64px white disc with "INHALE/EXHALE" (`aria-live=polite`). · Neutral product UI
- **heart-rate-widget.tsx** — Mascot `#FB7185`, accent `#FDA4AF`, heart icon; dial glow toggles opacity .22↔.5 for a "pulse"; BPM tabular. · Mascot face tiles
- **hydration-widget.tsx** — 144×240 tall tile (`border-radius:2rem`), "3/8 glasses" 30px/300, SVG bottle (cap `12×10 rx3`, body `40×94 rx18`) clipped fill `#7DD3FC` rising 300ms on tap. · Neutral product UI · ★ (vertical fill gauge)
- **ios-calender-widget.tsx** — iOS date tile: weekday 13px/600 `#FF3B30`, day 72px/500 `letter-spacing:-.05em` black, month 17px `#8E8E93`; entry via `@starting-style{opacity:0;translateY(4px)}` 500ms; radius 22px. · Neutral product UI
- **ios-digital-clock-widget.tsx** — HH:MM 48px bold tabular inside a squircle with 60 tick marks walked along a rounded-rect path (computed point + inward normal). · Neutral product UI
- **ios-earbuds-widget.tsx** — AirPods illustration (SVG gradients `#FFFFFF→#E8E8ED`, `#F5F5F7→#D1D1D6`), 8px connection dot `#22c55e` with sr-only text. · Neutral product UI
- **ios-map-location-widget.tsx** — Stylised SVG map (water/parks/roads, `preserveAspectRatio="xMidYMid slice"`) with centred blue teardrop pin `drop-shadow(0 1px 4px rgba(0,0,0,.12))` and city label; SF Pro font stack. · Neutral product UI
- **minimal-agenda-widget.tsx** — 256px agenda: tap a row to toggle done; strike line is a 1px `rgba(163,163,163,.8)` bar growing `width:0→100%` 500ms ease-in-out at `top:8px` (with fixed `line-height:16px`) so it hugs the text; check fades in emerald. · Neutral product UI · ★
- **pomodoro-widget.tsx** — `#0C0C0C` tile, thin 1.5px ring (track `rgba(255,255,255,.07)`, progress tomato `#E85D4C`, idle `rgba(255,255,255,.32)`) via `stroke-dashoffset` 1000ms linear; mono 28px/300 time `letter-spacing:-.03em`, dim colon `rgba(255,255,255,.3)`; status 10px uppercase `letter-spacing:.14em`; play button `rgba(255,255,255,.07)`; whole tile `active:scale(.98)`. · Carbon spotlight dark · ★ (countdown ring)
- **recorder-face-widget.tsx** — Mascot `#6CA8FF` (mouth opens to "O" while recording), accent `#FF453A`, 26px/200 MM:SS timer driven by rAF. · Mascot face tiles
- **ride-pickup-widget.tsx** — ETA in `#22c55e`, car image, bottom strip `#fafafa` with `border-radius:0 0 24px 24px`. · Neutral product UI
- **sleep-score-widget.tsx** — Mascot `#38BDF8` with closed eyes, accent `#7DD3FC`, duration footer `rgba(255,255,255,.3)`. · Mascot face tiles
- **step-count-widget.tsx** — Typography-led stat card (256px): "Today", 48px/300 number, label, footer with goal and %. · Neutral product UI · ★ (KPI tile)
- **stopwatch-widget.tsx** — MM:SS (32px/200) + centiseconds (15px/300 `#a3a3a3`), status dot `rgba(52,199,89,.55)` running / `.18` idle with matching 1px rings; control pill `#fafafa` + 1px `#f5f5f5` ring holding lap (28px white), play/pause (32px `#34C759` / `#FF9500` with `box-shadow:0 2px 8px rgba(52,199,89,.28)` / `rgba(255,149,0,.28)`), stop (`#FF3B30` + `0 2px 8px rgba(255,59,48,.25)`); `active:scale(.95)`. · Neutral product UI (iOS colours) · ★
- **torch-face-widget.tsx** — Mascot `#FACC15`, accent `#FDE047`, flashlight icon. · Mascot face tiles
- **voice-assistant-widget.tsx** — 16-bar waveform (4px bars, `#171717` active / `#e5e5e5` idle, heights randomised every 100ms; idle 12%, resting 20%), 48px mic button (`#ef4444` when listening). · Neutral product UI
- **wifi-toggle-widget.tsx** — iOS Wi-Fi tile: status dot, 44px icon disc, network name / "No network", 44×24 switch `#34d399` on / `#e5e5e5` off with 20px white thumb `translateX(20px)` 200ms. · Neutral product UI · ★ (toggle tile)

---

## 4. Porting notes (React + Tailwind → vanilla JS/CSS)

### 4.1 Dependencies

- **Animation libraries: none.** No Framer Motion, GSAP, react-spring or similar. Everything is CSS.
- **lucide-react** (101 files): icons only. Use the `lucide` static SVGs (copy the `<svg>` markup, `stroke="currentColor"`, `stroke-width:2`, sizes 10–18px) or any equivalent set.
- **next/image** (44 files): plain `<img loading="lazy" decoding="async">` with `object-fit:cover` on a sized, `position:relative; overflow:hidden` box (the `fill` prop pattern).
- **next/link** (7 files): `<a>`. Several components render a `<button type="button">` instead when `href` is missing or `"#"` — keep that rule.
- **`@/lib/cn`** (205 files) = `twMerge(clsx(...))`: irrelevant once classes are plain CSS; use `classList.toggle(name, condition)`.
- **`@/icons/brands/*`, `docks/Icons.tsx`**: brand SVG marks. Do not port brand marks.
- Site-only, not portable: `system/analytics/tracker.tsx` (`@/lib/analytics/client`, `next/navigation`), `contact/copy-email.tsx` reads `@/lib/site`, `users/testimonial-card.tsx` reads `@/lib/home/testimonials`, `underlines/annotated-text-showcase.tsx` imports `annotated-text`.
- Browser APIs used: `navigator.clipboard.writeText` (with `document.execCommand("copy")` textarea fallback in copy-email), `Element.animate` (text-loader), `requestAnimationFrame` (stopwatch, recorder, like-button particles), `matchMedia('(prefers-reduced-motion: reduce)')` (loaders), `DeviceOrientationEvent` + iOS `requestPermission()` (compass), pointer events with `touch-action:none` (slide-to-confirm, hold-to-delete), drag-and-drop + `File` API (file upload).

### 4.2 Tailwind → plain CSS cheat-sheet

| Tailwind (v4) | CSS |
|---|---|
| `shadow-[0_1px_2px_rgba(0,0,0,0.05),inset_0_1px_0_#fff]` | `box-shadow: 0 1px 2px rgba(0,0,0,.05), inset 0 1px 0 #fff;` — underscores are spaces, commas separate layers |
| `bg-[radial-gradient(circle_at_50%_0%,#fff_0%,#eee_100%)]` | `background: radial-gradient(circle at 50% 0%, #fff 0%, #eee 100%);` |
| `[background-image:…] [background-size:4px_4px]` | the property literally, underscores → spaces |
| `bg-linear-to-b from-A via-B to-C` | `background-image: linear-gradient(to bottom, A, B, C);` (`to-br` = `to bottom right`, `to-tr` = `to top right`) |
| `bg-white/10`, `border-white/20`, `shadow-black/10` | `rgba(255,255,255,.1)`, `rgba(255,255,255,.2)`; for coloured shadows replace the shadow's alpha with `.1` |
| `opacity-22` (v4 any integer) | `opacity: .22` |
| `blur-sm/md/xl/2xl/3xl` | `filter: blur(8px / 12px / 24px / 40px / 64px)` |
| `backdrop-blur-md`, `backdrop-blur-xl` | `backdrop-filter: blur(12px)`, `blur(24px)` (add `-webkit-backdrop-filter`) |
| `rounded-md/lg/xl/2xl/3xl/full` | `6px / 8px / 12px / 16px / 24px / 9999px` (`rounded` = 4px, `rounded-sm` = 4px in v4, `rounded-xs` = 2px) |
| `size-10`, `h-44 w-44` | `width:40px; height:40px`, `176px` (× 4px) |
| `tracking-tight/wide/wider/widest` | `letter-spacing: -.025em / .025em / .05em / .1em` |
| `text-xs/sm/base/lg/xl/2xl` | `12px/16px`, `14px/20px`, `16px/24px`, `18px/28px`, `20px/28px`, `24px/32px` (font-size/line-height) |
| `font-light/extralight` | `300` / `200` |
| `tabular-nums` | `font-variant-numeric: tabular-nums;` |
| `truncate` | `overflow:hidden; text-overflow:ellipsis; white-space:nowrap;` |
| `line-clamp-2` | `display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;` |
| `sr-only` | `position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0;` |
| `duration-200 ease-[cubic-bezier(0.32,0.72,0,1)]` | `transition-duration:200ms; transition-timing-function:cubic-bezier(.32,.72,0,1);` (Tailwind's default `transition` property list = color, background-color, border-color, outline-color, text-decoration-color, fill, stroke, opacity, box-shadow, transform, translate, scale, rotate, filter, backdrop-filter; default 150ms) |
| `transition-[box-shadow,color]` | `transition-property: box-shadow, color;` |
| `delay-200` | `transition-delay: 200ms;` |
| `hover:` / `active:` / `focus-visible:` / `disabled:` | `:hover` (wrap in `@media (hover:hover)` for touch), `:active`, `:focus-visible`, `:disabled` |
| `group-hover:x` / `group-focus-visible:x` | `.group:hover .child { … }` / `.group:focus-visible .child { … }` |
| `peer-checked:x` | `input:checked + .track { … }` or `input:checked ~ .x` (needs sibling order) |
| `has-[:focus-visible]:outline-2` | `label:has(:focus-visible) { outline: 2px solid …; }` |
| `focus-within:border-neutral-900` | `.group:focus-within { border-color:#171717; }` |
| `data-[phase=closing]:opacity-0` | `[data-phase="closing"] { opacity:0; }` |
| `aria-` states | style `[aria-pressed="true"]`, `[aria-expanded="true"]`, `[aria-selected="true"]` directly |
| `starting:opacity-0 starting:-translate-y-1` | `@starting-style { .menu { opacity:0; transform:translateY(-4px); } }` with a `transition` on the element. Supported in Chrome 117+, Safari 17.5+, Firefox 129+; older browsers just skip the animation |
| `motion-reduce:transition-none` / `motion-safe:animate-pulse` | `@media (prefers-reduced-motion: reduce) { … transition:none }` / `@media (prefers-reduced-motion: no-preference) { … animation:pulse … }` |
| `animate-spin` / `animate-pulse` / `animate-ping` | `@keyframes spin{to{transform:rotate(360deg)}}` 1s linear infinite / `@keyframes pulse{50%{opacity:.5}}` 2s cubic-bezier(.4,0,.6,1) infinite / `@keyframes ping{75%,100%{transform:scale(2);opacity:0}}` 1s cubic-bezier(0,0,.2,1) infinite |
| `md:` | `@media (min-width: 768px)` — mobile-first, the only breakpoint the library uses |
| `-space-x-2` | `.stack > * + * { margin-left:-8px; }` |
| `divide-y divide-neutral-50` | `.list > * + * { border-top:1px solid #fafafa; }` |
| `[&::-webkit-scrollbar]:hidden [scrollbar-width:none]` | `.x::-webkit-scrollbar{display:none} .x{scrollbar-width:none}` |
| `perspective-[1000px]`, `[transform-style:preserve-3d]`, `[backface-visibility:hidden]` | same properties in plain CSS |
| `filter-[drop-shadow(...)_drop-shadow(...)]` | `filter: drop-shadow(...) drop-shadow(...);` |
| `ring-1 ring-black/5` | `box-shadow: 0 0 0 1px rgba(0,0,0,.05);` (combine with any other shadow in one declaration) |
| `outline-2 outline-offset-2 outline-neutral-900` | `outline: 2px solid #171717; outline-offset: 2px;` |
| `ease-smooth` | `cubic-bezier(.22,1,.36,1)` (from `@theme` in globals.css) |
| colours `neutral-*`, `emerald-*` … | hex table in §1.1 (Tailwind v4 emits `oklch()`; the hex approximations match) |

Translation tips:
- Hoist the repeated recipes into custom properties (§1.5, §2) and classes (`.key`, `.key--dark`, `.tray`, `.card`, `.menu`, `.banner`), instead of copying long shadows per component.
- Variant maps in the source (`SIZE: {sm, md, lg}`, `VARIANT: {solid, soft, muted}`) become modifier classes or `data-size`/`data-variant` attribute selectors.
- Several components already expose state as data attributes (`data-phase`, `data-state="on|off"`, `data-copied`, `data-size`, `data-layer`). Keep them as the styling hook; the JS only flips attributes.
- Inline `style={{ background: CONST }}` constants (cinder, prism, linen, watch) are already plain CSS strings — copy as-is.
- Animated widths/offsets computed in React (`style={{ width: progress+'%' }}`, `translate3d(x,0,0)`) become `el.style.setProperty('--p', value)` with CSS `width: calc(var(--p) * 1%)`.

### 4.3 Behaviour patterns to re-implement in vanilla JS

- **Timed state machine** (add-to-cart, download, copy, follow): `idle → working → done → idle` with `setTimeout` (default 1200–1600ms); clear timers on teardown; set `aria-busy` while working.
- **Crossfade labels**: render all labels in one grid cell (`display:grid` + children `grid-area:1/1`), toggle `.is-active`; outgoing `transition: opacity 200ms`, incoming `opacity 300ms 200ms`.
- **Hold to confirm**: on `pointerdown`/`keydown(Space|Enter)` add `.holding` (fill transitions `translateX(-100%)→0` linear over `holdMs`) and start a timer; on `pointerup/pointerleave/keyup` cancel and remove the class (eases back in 300ms); on timer end mark done.
- **Slide to confirm**: `pointerdown` → `setPointerCapture`, track `clientX`, clamp `0…trackWidth − knob − 2×pad`, `transform: translate3d(x,0,0)`, label `opacity = 1 − progress*1.4`; release past ~90% → confirmed, else snap back with a 300ms transition. Track needs `isolation:isolate; transform:translateZ(0)`, knob `will-change:transform`.
- **Segmented control**: measure nothing — width `calc((100% − pad − gaps)/n)`, `transform: translateX(calc(i*100% + i*4px))`.
- **Dropdown/menu**: toggle `[aria-expanded]` on trigger and `hidden` on panel; close on outside `pointerdown`/`mousedown` and `Escape`; return focus to the trigger; Enter/Space opens. Inline variants (kebab, workspace switcher) expand inside the same card — better on small screens than an overlay.
- **Combobox / select**: follow the WAI-ARIA combobox and listbox patterns as the source does (`aria-activedescendant`, ArrowUp/Down/Home/End/Enter/Escape); keep a hidden native `<select>`/`<input>` so forms submit.
- **OTP**: one `<input>` per digit with `inputmode=numeric`, `autocomplete="one-time-code"` on the first, `pattern="[0-9]*"`; on `input` move focus forward; on Backspace in an empty box move back; on `paste` distribute characters; announce errors with `role=alert`.
- **Notifications**: `data-phase="open|closing|closed"`, remove the node after the exit duration; use `<output>` or `role=status` so screen readers announce.
- **Re-keyed enter animations**: where React changes a `key` to replay a `starting:` transition (calendar, countdown digits), either replace the node (`el.replaceWith(clone)`) or toggle a class that runs a short `@keyframes`.
- **Clocks/timers**: start with a skeleton, fill on first tick; use `requestAnimationFrame` only while running.
- **Clipboard**: `navigator.clipboard.writeText` inside `try/catch`; show confirmation regardless; reset after 1600ms.

### 4.4 Accessibility patterns worth keeping

- Real form controls under custom visuals: checkbox, radio, switch and dimple/slate switches keep a native `<input>` (`opacity:0; position:absolute; inset:0`) so keyboard, form submission and screen readers work; the visual reacts via `:checked` / `peer-checked`.
- `:focus-visible` outlines (2px, offset 2px) on every interactive element; inputs signal focus by a dark border (contrast ≥3:1 against `#e5e5e5`); focus ring on the wrapper with `:has(:focus-visible)` for hidden inputs.
- Live regions: visually hidden `aria-live="polite"` text for state changes (copied, added, downloading), `role=status` for saving/loading, `role=alert` for field errors, `<output>` for notification banners.
- `aria-pressed` for toggles (bookmark, follow, like, star), `aria-busy` during async work, `aria-current="page"` in docks, `aria-haspopup`/`aria-expanded` on menu triggers, `role=menu/menuitem/menuitemradio`, `role=tablist/tab` for the segmented control, `role=switch` + `aria-checked`, `role=radiogroup` inside `<fieldset>/<legend>`, `role=img` + label on the progress ring, `role=group` + `aria-labelledby` on OTP.
- Every icon-only button has an `aria-label` (prev/next, close, more actions, remove file); decorative icons are `aria-hidden`.
- Hints and errors linked with `aria-describedby`; required marker `*` is `aria-hidden` while the input has `required`.
- Data-URI `<img alt>` cells in the contribution heatmap give each cell an accessible description; mirror this with `role=img aria-label` on each cell or a visually hidden table.
- Honeypot field (`name="company"`, `.sr-only`, `autocomplete=off`, `tabindex=-1` recommended) instead of a CAPTCHA in the contact form.
- `prefers-reduced-motion` respected in buttons, loaders, frames; extend to the rest when porting (snippet in §1.8).
- Gaps to fix when porting: some clickable rows/cards are `<div>` or whole-card `<button>`s with nested controls (magazine cover, gallery cards); low-contrast meta text (`#a3a3a3` on white is ~2.5:1 — use `#737373` for anything essential, as the library's own design.md asks); `user-select:none` on many cards prevents copying values; hover-only affordances (dock tooltips, team-card socials) need a touch/focus equivalent on mobile.

### 4.5 What to watch out for in a dark trading UI

- The library is light-first; only backgrounds, audio, a few cards and widgets are dark. Derive dark tokens from §2.1 (Carbon spotlight dark) and §2.3, and recompute the 3D key shadows for dark faces using the `--key-dark` recipe.
- Semantic colours: the library uses grey for negative amounts (recent-transactions); a trading UI needs explicit up/down colours — reuse emerald `#10b981`/`#34d399` and rose `#f43f5e`/`#fb7185`, paired with a sign or arrow so meaning does not rely on colour.
- Keep `tabular-nums` and right alignment on every numeric column; use the true minus sign `−` (U+2212) as the library does.
- Glass blur is expensive on low-end phones; limit `backdrop-filter` to one fixed element (the dock or header).

