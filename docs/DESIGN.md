# Clippper Design System
> impressionist museum behind frosted glass — adapted from the "Adora" style reference

**Theme:** light · **Implemented in:** `frontend/clippper/src/App.css` (CSS custom properties on `:root`)

Clippper wraps a precise video-clipping interface inside an impressionist gallery: white cards and crisp panels sit on canvas-white backgrounds with soft oil-paint pastel washes bleeding behind product visuals (never behind text). The color story is white-surface discipline broken by a single vivid violet for action, plus pastel accents used as small confetti, not washes. Shapes are confidently rounded — cards at 40px, badges stadium-rounded, buttons gently rounded at 8px. Typography is Plus Jakarta Sans throughout (the PolySans display face from the reference is substituted with Plus Jakarta at 700–800, per the reference's own substitution rule), with universal −0.02em tracking pulling the system tight.

---

## Color tokens

| Name | Value | Token | Role in Clippper |
|------|-------|-------|------|
| Electric Violet | `#592eff` | `--color-electric-violet` | The single saturated action color: filled primary buttons (Upload, Resume, Export, Cut clip), progress-bar fills, active nav border, focused input border |
| Midnight Plum | `#21164c` | `--color-midnight-plum` | Display/headline text — near-black with a violet undertone that ties to the action color |
| Obsidian Charcoal | `#353241` | `--color-obsidian-charcoal` | Body text, icon strokes, strong structural borders |
| Slate Smoke | `#5f5f69` | `--color-slate-smoke` | Muted/secondary text, helper copy, metadata (timecodes, video IDs) |
| Pearl Mist | `#e0e0db` | `--color-pearl-mist` | Hairline borders on every card, button, input — the system's only elevation device |
| Soft Concrete | `#eeeeee` | `--color-soft-concrete` | Recessed fills: secondary button hover, disabled controls, progress tracks, metric tiles |
| Pure White | `#ffffff` | `--color-pure-white` | Page canvas, card surfaces, nav pill, button text on violet |
| Sky Tint | `#bcf2ff` | `--color-sky-tint` | Decorative pastel — painterly washes behind the hero preview frame |
| Lime Spritz | `#dfff9d` | `--color-lime-spritz` | Decorative pastel — washes, squiggle underline fills |
| Cotton Candy | `#ffaae6` | `--color-cotton-candy` | Decorative pastel — washes, the hero squiggle underline |
| Neon Cyan | `#2ed6ff` | `--color-neon-cyan` | Badge outline for **in-motion states**: uploading, initializing, processing, rendering |
| Lime Pop | `#a2ea13` | `--color-lime-pop` | Badge outline for **positive states**: uploaded, ready, success |
| Magenta Pulse | `#f843c2` | `--color-magenta-pulse` | Badge outline for energetic/feature highlights (moment type chips) |
| Signal Red *(Clippper extension)* | `#d2384a` | `--color-signal-red` | Functional error text/badges and destructive buttons only — the reference has no error color; keep it as quiet outline treatments, never a wash |

**Behavior rules:** the page stays ~87% achromatic. Violet is rationed to one filled CTA per viewport plus active states — never a background wash, never text-on-white decoration. Pastels are decoration only (washes, squiggles); never button fills or text colors. Vivid badge colors live only in stadium-pill outlines and matching label text.

## Typography

One family: **Plus Jakarta Sans** (Google Fonts, loaded in `index.html`). Universal letter-spacing **−0.02em**.

| Role | Size / line-height | Weight | Token |
|------|------|--------|-------|
| display (hero) | 68px / 1.1 | 800 | `--text-display` |
| heading-lg (page titles) | 58px / 1.1 | 700 | `--text-heading-lg` |
| heading (section) | 38px / 1.1 | 700 | `--text-heading` |
| heading-sm (panel titles) | 32px / 1.1 | 700 | `--text-heading-sm` |
| subheading | 20px / 1.6 | 600 | `--text-subheading` |
| body | 18px / 1.6 | 400 | `--text-body` |
| body-sm (UI, buttons, nav) | 16px / 1.6 | 500 | `--text-body-sm` |
| caption (badges, meta) | 14px / 1.6 | 500 | `--text-caption` |

Headlines in Midnight Plum, never pure black. Timecodes and IDs use the mono stack (`--font-mono`) at caption size in Slate Smoke.

## Spacing & shape

Base unit 4px; scale `4 8 12 16 20 24 32 40 48 60 100` (tokens `--spacing-*`). Page max-width **1200px**, section gap **80px**, card padding **32px**, element gap **12px**.

| Element | Radius | Token |
|---------|--------|-------|
| Cards / panels | 40px | `--radius-cards` |
| Product frame (hero preview) | 64px | `--radius-productframe` |
| Nav pill | 40px | `--radius-navpill` |
| Buttons | 8px | `--radius-buttons` |
| Inputs | 12px | `--radius-inputs` |
| Badges / status pills | 200px | `--radius-badges` |
| Inner rows (table rows, list items) | 16px | `--radius-rows` |

**Elevation:** no drop shadows. Depth = 1px Pearl Mist hairline + generous radius + white-on-white layering. If a shadow is ever unavoidable, rgba neutral at 4–8% max.

## Components (Clippper mapping)

- **Floating nav pill** (`.dashboard-topbar`, Home `.top-bar` inner) — white pill, 40px radius, hairline border, never a full-bleed bar. Logo lockup left (violet mark + Midnight Plum wordmark, Jakarta 600), nav links center (Charcoal 16px/500, active gets a violet underline border), Clerk user button / violet CTA right.
- **Primary button** (`.button-primary`) — filled `#592eff`, white text, 8px radius, 10px 20px padding, no border. One per viewport.
- **Secondary/ghost button** (`.button-secondary`, `.button-ghost`) — transparent, 1px Pearl Mist border, Charcoal text.
- **Danger button** (`.button-danger`) — ghost treatment with Signal Red text/border; destructive actions never get a filled wash.
- **Status badge** (`.upload-status`, `.videos-table-row mark`) — stadium pill, transparent fill, 1px chromatic outline + matching text: cyan = in motion, lime = done, red = error, smoke = idle.
- **Panel / card** (`.dashboard-panel`) — white, hairline, 40px radius, 32px padding. Inner rows at 16px radius with hairline.
- **Product showcase frame** (`.clip-preview` on Home) — 64px-radius white frame sitting on painterly pastel washes that bleed behind it. Washes never sit behind text blocks.
- **Squiggle underline** (`.squiggle`) — hand-drawn SVG wave under 1–2 words of a display headline only (cotton-candy pink). Never under body copy or UI labels.
- **Progress** (`.upload-progress-track`) — Soft Concrete track, violet fill, pill-rounded.
- **Inputs** (`.agent-input`, `.clip-input-row input`, selects) — white, hairline, 12px radius; focus thickens border to 1.5px violet, no glow ring.

## Do / Don't

**Do**
- One filled violet CTA per viewport; violet also marks active nav and progress fills.
- Display headings in Midnight Plum at 700–800 with −0.02em tracking.
- 40px+ radius on containers, 8px on controls — that contrast *is* the system.
- Keep pastels behind imagery/frames and in squiggles only.
- Separate sections with space (80px), not rules; hairlines live inside cards.

**Don't**
- No violet text or violet page tints; no pastel button fills or pastel text.
- No pure `#000` body text; use Charcoal.
- No drop-shadow stacks; no third typeface or serif.
- No painterly wash behind reading content.
- Don't mix sharp cards with rounded buttons — big-radius containers, small-radius controls, always.

## Surfaces

| Level | Name | Value | Use |
|-------|------|-------|-----|
| 0 | Page canvas | `#ffffff` | Page background |
| 1 | Elevated card | `#ffffff` + hairline | Panels, nav pill, tables |
| 2 | Recessed | `#eeeeee` | Secondary fills, tracks, metric tiles |
| 3 | Atmospheric wash | pastels, blurred | Behind the hero product frame only |

## Quick start (already in App.css)

```css
:root {
  --color-electric-violet: #592eff;
  --color-midnight-plum: #21164c;
  --color-obsidian-charcoal: #353241;
  --color-slate-smoke: #5f5f69;
  --color-pearl-mist: #e0e0db;
  --color-soft-concrete: #eeeeee;
  --color-pure-white: #ffffff;
  --color-sky-tint: #bcf2ff;
  --color-lime-spritz: #dfff9d;
  --color-cotton-candy: #ffaae6;
  --color-neon-cyan: #2ed6ff;
  --color-lime-pop: #a2ea13;
  --color-magenta-pulse: #f843c2;
  --color-signal-red: #d2384a;

  --font-sans: 'Plus Jakarta Sans', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
  --font-mono: ui-monospace, 'Cascadia Code', SFMono-Regular, Consolas, monospace;

  --radius-cards: 40px;
  --radius-productframe: 64px;
  --radius-navpill: 40px;
  --radius-buttons: 8px;
  --radius-inputs: 12px;
  --radius-badges: 200px;
  --radius-rows: 16px;

  --page-max-width: 1200px;
  --section-gap: 80px;
  --card-padding: 32px;
  --element-gap: 12px;
}
```

When building any new screen or component, start from these tokens and the component mappings above; if a case isn't covered, follow the reference hierarchy: neutral → violet action → pastel decoration.
