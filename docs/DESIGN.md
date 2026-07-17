# Clippper Design System

**Themes:** dark (default) + light · **Implemented in:** `frontend/clippper/src/styles/`

Clippper is a tool for streamers who have a job and thirty minutes. The interface is quiet, flat, and high-contrast: near-black surfaces, one violet action color, and hairline borders doing all the structural work. Nothing decorative competes with the two things that matter on screen — a moment's score and the button that turns it into a clip.

The shape language carries the personality: big-radius containers (24px cards) against small-radius controls (8px buttons). Type is Plus Jakarta Sans throughout with universal −0.02em tracking.

---

## House rules

These are load-bearing. The system reads as designed rather than generated precisely because it refuses the usual shortcuts:

- **No gradients.** Not on backgrounds, buttons, cards, thumbnails, or text.
- **No glows, no neon bloom, no glassmorphism, no backdrop blur.**
- **No drop shadows.** Depth is: flat surface + 1px hairline + radius contrast. That's the whole elevation model.
- **No fake imagery.** The backend stores no thumbnails, so video posters are a flat recessed panel with a film glyph and the file extension — not a decorative stand-in.
- **One accent, rationed.** Violet marks one primary action per viewport, the active nav item, progress fills, and the top-ranked score. Never a page wash, never body text.

## Architecture: semantic tokens

Components style against **semantic** tokens only. Raw hex lives exclusively in the two theme blocks in `tokens.css`. This is what lets one stylesheet serve both themes.

```
src/styles/
  tokens.css      the two themes + type/space/shape scales
  base.css        reset, element defaults, text helpers
  components.css  buttons, cards, pills, shell, form controls, states
  pages.css       screen-specific layout + responsive rules
```

`App.css` imports the four in that order; nothing else imports CSS.

| Token | Dark | Light | Role |
|-------|------|-------|------|
| `--canvas` | `#0d0c12` | `#ffffff` | Page background |
| `--surface-1` | `#17151f` | `#ffffff` | Cards, sidebar, raised panels |
| `--surface-2` | `#211e2c` | `#f4f4f2` | Recessed: thumbnails, tracks, segmented controls |
| `--surface-hover` | `#262232` | `#eeeeee` | Hover fill |
| `--border` | `#2b2837` | `#e0e0db` | The hairline — the only elevation device |
| `--border-strong` | `#3d3950` | `#c9c9c2` | Emphasis borders, dropzone |
| `--text-heading` | `#f6f5fa` | `#21164c` | Headings |
| `--text-body-color` | `#d5d2df` | `#353241` | Body |
| `--text-muted` | `#8b8799` | `#5f5f69` | Meta, helper copy, timecodes |
| `--accent` | `#7c5cff` | `#592eff` | The single action color |
| `--accent-quiet` | `#241d47` | `#f0ecff` | Active nav fill, glyph tiles |
| `--state-motion` | `#2ed6ff` | `#0090b8` | In motion: uploading, analyzing, queued, rendering |
| `--state-good` | `#a2ea13` | `#4b7a00` | Done: uploaded, ready |
| `--state-bad` | `#ff5f70` | `#d2384a` | Failed, destructive |
| `--state-feature` | `#f843c2` | `#b81a8a` | Moment type chips |

The light theme is the original white-surface identity mapped onto the same names, so it stays a real theme rather than an inverted afterthought. Light-theme state colors are darkened from their dark-theme values to hold contrast on white.

### Theme switching

`index.html` runs a tiny inline script before first paint that reads `localStorage['clippper-theme']` (default `dark`) onto `<html data-theme>`, so reloads never flash. `src/theme/ThemeProvider.jsx` owns the React state and writes both the attribute and storage; `themeContext.js` exports `useTheme()` separately so the provider file stays fast-refresh clean. Clerk's modals get matching `appearance` variables in `ClerkProviderWithRoutes.jsx` — update those alongside any token change.

## Type & space

| Role | Token | Size |
|------|-------|------|
| Display (hero) | `--text-display` | 3.5rem / 800 |
| Page title | `--text-h1` | 2.25rem / 700 |
| Section | `--text-h2` | 1.5rem / 700 |
| Card title | `--text-h3` | 1.125rem / 600 |
| Body | `--text-body` | 1rem / 400 |
| UI, buttons | `--text-sm` | 0.875rem / 600 |
| Meta, chips, eyebrow | `--text-xs` | 0.75rem |

Space scale is 4px-based: `--space-1` … `--space-20` (4 → 80). Timecodes, IDs, and format labels use `--font-mono` at `--text-xs` in `--text-muted`.

| Element | Radius |
|---------|--------|
| Hero frame | `--radius-frame` 40px |
| Cards / panels | `--radius-card` 24px |
| Inner rows | `--radius-row` 16px |
| Inputs | `--radius-input` 12px |
| Buttons | `--radius-control` 8px |
| Pills / badges | `--radius-pill` 200px |

## Components

- **App shell** (`AppLayout`) — desktop: fixed 248px sidebar (brand, nav, account + theme toggle pinned bottom). ≤768px: sticky top bar + fixed bottom tab bar, so nav stays thumb-reachable.
- **Buttons** — `.button-primary` (filled accent, one per viewport), `.button-secondary` (hairline), `.button-ghost`, `.button-danger` (red text/border, never a filled wash).
- **Status pill** (`StatusPill`) — stadium outline + dot, transparent fill. One vocabulary for videos and clips; the dot pulses only for in-motion states. `uploaded`/`processing` both render as "analyzing" because that distinction is backend bookkeeping, not user-facing.
- **Card** (`.card`) — `--surface-1`, hairline, 24px radius, 24px padding.
- **Video card** (`VideoCard`) — flat placeholder poster, filename, size/date, contextual action (Find clips / Resume upload) and a quiet delete.
- **Moment card** (`MomentCard`) — time range, type chip, title, reason, four score chips (hook/shareable/complete/visual) plus the final score in a 52px square badge — accent-bordered for rank 1 only. Options row carries the format picker, captions toggle, and Generate.
- **Score display** — the detector emits 0..1 floats (`backend/app/tasks/detect.py`); the UI always renders them ×100 as integers.
- **Clip render card** (`ClipRenderCard`) — owns its own polling; shows an indeterminate track while queued/rendering, then player + Download.
- **Segmented control** (`.segmented`) — format picker, upload content type. Selected = `--surface-1` chip on the `--surface-2` track.
- **Empty state** (`EmptyState`) — dashed hairline, glyph tile, headline, one helper sentence, optional action.
- **Skeletons** (`.skeleton`) — flat `--skeleton` fill with an opacity pulse. No shimmer sweep.

## Microcopy

Friendly, encouraging, concise — write like a person who respects the reader's evening. "We'll handle the boring stuff." "You're one click away from 5 clips." "Finding your best moments…" Errors say what happened and what to do next; never expose a stack trace or a raw status where a sentence works.

## Adding a screen

Start from the tokens and the components above. If a case isn't covered, follow the hierarchy: **neutral surface → hairline → accent for the one action**. If you reach for a gradient, a shadow, or a second accent, the answer is more space or a stronger hairline instead.
