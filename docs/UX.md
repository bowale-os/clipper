# Clippper UX Blueprint

> Decisions locked 2026-07-13 with the founder: neutral persona (no content-type-specific voice), **upload-first home**, review optimized for **triage speed**, **desktop-first** but mobile-usable. Visual language: [DESIGN.md](DESIGN.md).

## The user and their four moments

A solo creator (streamer, podcaster, sports editor — served equally) with hours-long recordings. They are not video editors; they want the machine to find the good parts. Every screen serves one of four moments, each with one dominant need:

| Moment | Need | Screen | Design consequence |
|---|---|---|---|
| Upload | **Trust** | Dashboard | Progress with real numbers; interruption framed as recoverable (amber + Resume, never red); cancel always available |
| Waiting | **Transparency** | Videos list (→ processing detail later) | Status pills that update; "you can leave" messaging; no manual-refresh-as-primary-interaction once polling lands |
| Review | **Triage speed** | Moments page | Ranked cards, the AI's one-line *why* on every card, score visible, one primary action per card; trim/precision is a secondary affordance, never in the way of keep-or-skip judgment |
| Retrieval | **Findability** | Videos + clips | Human language ("Your videos", "Ready to review"), never API vocabulary; clips survive refresh |

## Information architecture

```
/            Landing (signed-out) → sign in/up
/dashboard   HOME: upload card (+ resume target) | upload guide rail
/videos      Library: all videos grouped by state, with per-state actions
/videos/:id/moments        Review: ranked moment triage
/videos/:id/clips          Manual clip editor (power path)
/videos/:id/moments/:i/clip  Clip result / download
```

Navigation is the floating pill (Dashboard · Videos) + user button. Two items only until the clips library gets its own page.

## Per-screen intent

### Dashboard (home, upload-first)
The upload card is the hero. States: idle → selected → uploading (progress + cancel) → done (link to the video). Resume mode replaces the picker prompt with *Re-select "{filename}" to resume*. The side rail explains what happens after upload — it's the trust-builder for first-time users, drop it once processing status is visible in-app.

### Videos (library)
Grouped by state in priority order: **Ready** (primary action: Review moments) → Processing → Errors → Uploading (Resume/Discard) → Uploaded. Copy is human: "Your videos", "No videos yet — upload one from the dashboard." Status is a stadium pill (cyan = in motion, lime = done, red = error). The Refresh button is an interim crutch: it dies when 3s polling ships with the pipeline.

### Moments (review — the product's core screen)
Optimized for a 2-minute triage of ~20 moments:
- Cards ranked by score, score pill visible, timecode range + duration visible.
- The **why** (LLM's reason) on every card — trust comes from the machine showing its work.
- One primary action per card ("Get clip" today; becomes Keep/Dismiss + Export when `PATCH /moments/:id` and the render pipeline exist).
- Instant preview on click (seek the source `<video>` via presigned URL — zero render) — next build step.
- Trim precision lives behind the preview (drag handles/nudge), never between the user and their keep-or-skip judgment.

### Roadmap of UX debt (in build order)
1. **Processing transparency** — status pills polling `GET /videos/:id`, stage + % once the pipeline reports it. Kills all Refresh buttons.
2. **Inline preview on the moments page** — presigned source URL + seek; removes the create-clip-to-see-anything detour.
3. **Keep/Dismiss triage actions** — needs `PATCH /moments/:id`; keyboard shortcuts (K/D/J/K) after that.
4. **Clips library page** — `GET /videos/:id/clips`; clips stop vanishing on refresh.
5. Boundary drag-handles on preview; export presets (9:16, captions).

## Copy rules
- Name things by what the user recognizes, never how the system is built. ("Your videos", not "GET /videos/"; "Ready to review", not "analyzed".)
- Errors say what went wrong and what to do next. Interruptions that lose nothing are never styled as errors.
- One verb per button, outcome-named: Upload, Resume, Review moments, Get clip, Download.
