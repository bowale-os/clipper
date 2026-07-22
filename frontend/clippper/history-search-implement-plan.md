# History: one session per video

## Context

Right now the whole signed-in app is a single screen. `Studio.jsx` shows the drop zone, the videos still processing, and then the clips for one video at a time. Picking which video you are looking at is a row of chips that only appears once you have more than one, backed by a plain string in local state. It is not in the URL, so a refresh loses it, and there is no way to link to a video or come back to one.

That works for a user with two videos. It falls apart for a user with thirty. The clips grid belongs to whichever video happens to be selected, so the screen is always showing you one thing while hiding the rest, and finding an older video means scanning a horizontal row of filenames.

The fix is to stop treating "which video" as a filter on one page and start treating each video as its own place. Home becomes the upload page. Every video gets its own address. A sidebar lists them all and is always there.

Two phases. **Phase 1** is the restructure and ships on its own. **Phase 2** adds semantic search on top. Phase 1 is worth having without Phase 2; Phase 2 makes no sense without Phase 1.

---

# Phase 1 — Sessions and the sidebar

## What the user gets

| Route | What is on it |
|---|---|
| `/` | Greeting, drop zone, "Working on it", and the last three videos as cards to jump back into. No clip grid. |
| `/v/:videoId` | One video: its clips, "Cut your own", delete. Linkable, survives refresh, back button works. |

A left sidebar lists every video by title on both routes, with a search box at the top. Clicking a title opens that video's page. The old "Your streams" chip row goes away.

## Backend

Small. The data is already there.

**`backend/app/api/video.py`** — `_video_to_dict` (line 67) gains `clip_count`, so the sidebar and the pickup cards can say "6 clips" without a request per video. Add it to `get_videos` (line 317) as one grouped subquery over `clips` rather than a per-video query:

```python
counts = dict(
    db.execute(
        select(Clip.video_id, func.count(Clip.id))
        .where(Clip.user_id == user.id, Clip.status == "ready")
        .group_by(Clip.video_id)
    ).all()
)
```

Pass the map into `_video_to_dict`. Everything else about the endpoint stays as is, including the grouped-by-status response shape, since `flattenVideos` in `frontend/clippper/src/lib/videos.js` already un-groups it.

No migration needed for Phase 1.

## Frontend

The one architectural decision worth calling out: the sidebar needs the video list on every route, and `useUserVideos` has no cache, so every mount is a fresh request. Rather than introduce the codebase's first Context provider, use a **react-router layout route** that calls the hook once and hands everything down through `<Outlet context={...}>`. Same lifetime as a provider, no new concept, about three lines of plumbing.

### New files

- **`src/components/AppLayout.jsx`** — the shell. Calls `useUserVideos()` once, holds the `flattenVideos` / `readyVideos` / `workingVideos` / `interrupted` memos lifted straight out of `Studio.jsx:67-70`, owns the 15s poll (`Studio.jsx:134-141`), and hoists `useClipRenders()` and `useDeleteVideo()` so both survive navigation between videos. Renders `VideoRail` + `<Outlet context={value}>`. Memoize `value` or every keystroke in the search box re-renders the page.
- **`src/hooks/useAppData.js`** — three lines, wraps `useOutletContext()`.
- **`src/components/VideoRail.jsx`** — `<nav>` + search `<input>` + `NavLink` per video. Takes the full flattened list so processing videos show too, greyed. `NavLink` gives `aria-current="page"` for free.
- **`src/pages/Home.jsx`** — greeting, `DropZone`, "Working on it", and `readyVideos.slice(0, 3)` as pickup cards. The greeting copy has to change: today it counts the active video's ready clips, and there is no active video here. Key it off `workingVideos.length` and `readyVideos.length` instead.
- **`src/pages/Session.jsx`** — the current Studio body: filename heading, Ready grid, "Also worth a look" grid, `ClipPreview`, the `seed` effect, the `done`/`rest` split.

### Modified

- **`src/App.jsx`** — delete `Root`, add the layout route wrapping `/` and `/v/:videoId`. `AppLayout` does its own `useAuth()` branch and renders `Landing` when signed out, preserving today's behaviour at `/`. Leave `/settings`, `/trim/:videoId`, the auth routes and `*` untouched — they are full-bleed screens and do not want the rail.
- **`src/components/TopBar.jsx`** — optional `onOpenRail` prop rendering a toggle button, only visible on narrow screens. Reuse `FilmIcon`, no new glyph.
- **`src/hooks/useVideoMoments.js`** — add a module-level `Map` cache (see below).
- **`src/styles/tokens.css`** — add `--rail-width: 248px`.
- **`src/styles/components.css`** — the layout change and the rail styles.
- **`src/styles/pages.css`** — delete `.stream-filter` (lines 30-32), add `.pickup-*`.
- **Delete `src/pages/Studio.jsx`.**

### Layout

`.app-shell` currently carries the page padding, which would inset the rail from the viewport edge and stop its hairline running full height. Move the padding inward onto a new `.app-main`, behind a `.has-rail` modifier so `Settings`, `Trim` and the auth pages stay byte-identical. `--content-max: 1080px` survives untouched — `.app-content` now centres inside the column right of the rail.

```css
.app-shell.has-rail {
  display: grid;
  grid-template-columns: var(--rail-width) minmax(0, 1fr);
  align-items: start;
  padding: 0;
}

.app-main {
  min-width: 0; /* without this, long filenames push the grid past the viewport */
  padding: clamp(18px, 4vw, 34px) clamp(16px, 5vw, 40px) 96px;
}
```

The rail is `position: sticky; height: 100vh`, `background: var(--surface)` against the `--canvas` page, one `border-right` hairline. Selected row is `--surface-raised` + hairline + `--radius-row`. No shadow, no glow, no gradient — depth is the surface step and the hairline, per the house rules in `tokens.css`.

Below 920px the grid collapses to one column and the rail becomes an off-canvas drawer opened from the `TopBar` toggle, reusing the existing `.scrim`. Close it on `location.pathname` change.

### Caching, so switching videos does not flash

Today, hopping between videos blanks the grid to skeletons and refetches. Add a small module-level `Map` in `useVideoMoments.js`, capped around 20 entries:

- Seed state from the cache on mount, and resync **during render** when `videoId` changes (an effect paints one blank frame first, which is the exact flash this removes).
- On load start, only raise the skeleton if there is no cached data.
- On failure, keep the stale data rather than nulling it.
- Add a `cancelled` guard so a slow response for video A cannot land after the user moved to video B.
- Export `dropVideoMoments(id)`, called from the delete handler. That is the only invalidation point.

Safe because a `ready` video's moments never change — detect has finished by the time status flips. **Do not** cache `useVideoClips` too: clips genuinely change, that hook already polls and already refuses to blank on error, and a second cache is where hand-writing react-query starts.

### Edge cases on `/v/:videoId`

`Session` resolves the video from the shared list rather than fetching it, and parks the moments/clips hooks (`isReady ? videoId : ''`) until it is ready:

1. List still loading, no match — skeletons. Never claim "not found" before the list lands.
2. List loaded and no match, or moments returns 404 — one `EmptyState`: "We can't find that stream." Same copy for both; the user cannot act on the difference, and splitting them leaks whether the id exists.
3. `uploading` / `uploaded` / `processing` — the existing `.processing-row` markup with `LiveStatus`, no moments request. The layout poll flips it to ready on its own.
4. `error` — `.message.error` plus the delete control.
5. `ready` — the clips grids.

`useVideoMoments` needs to return a separate `notFound` flag for case 2; `getReadableError` flattens the status into a string, so capture it in the catch.

### Delete

`useDeleteVideo` lives in `AppLayout`. `onDeleted` drops the moments cache entry, refreshes the list, and navigates to `/` **only if** the deleted id is the one in the URL — use `matchPath('/v/:videoId', location.pathname)`, since the dynamic segment is on the child route and the layout's own `useParams` will not see it. `navigate('/', { replace: true })` so Back does not return to a dead video.

The two-step confirm in `DeleteVideo` stays exactly as it is.

---

# Phase 2 — Semantic search

You asked about embeddings. Worth doing, and the pipeline is already positioned for it, but it is a bigger piece than all of Phase 1 and it should ship separately.

My recommendation is **hybrid, not pure embeddings**. Two different searches are happening: "the podcast with Sarah" is a filename you half-remember, and "the part about pricing" is a meaning. Lexical wins the first instantly and for free; embeddings win the second. Running both and merging is better than either alone, and it means the box works from day one of Phase 1 with the lexical half only.

**Phase 1 ships the client-side filter** — lowercase `includes` on filename over the already-loaded list. Zero backend work, instant, and honest about what it does. Phase 2 replaces it.

## What gets embedded

Not the video. The **moments** — each already has an AI-written `title`, `reason`, and `transcript_excerpt` in the `moments` table. That is roughly 10 short texts per video, which is the right granularity: a hit tells you not just which video but which clip inside it.

## Work involved

1. **Migration** — `CREATE EXTENSION vector` (Neon supports pgvector), new table `moment_embeddings(moment_id UUID PK FK moments ON DELETE CASCADE, embedding vector(768), created_at)`, plus an HNSW index on `embedding vector_cosine_ops`. New Alembic revision on top of `2c0a02ab36a6`.
2. **Embed service** — `backend/app/services/embeddings.py`. Gemini `gemini-embedding-001` at 768 dims; the project already talks to Gemini in `app/tasks/detect.py`, so the key and client pattern exist. Batch every moment of a video into one call.
3. **Pipeline hook** — at the end of `app/tasks/detect.py`, after moments are written, embed and insert. This must be **best-effort**: wrap it so a failure logs and moves on rather than failing the job and blocking clip rendering. Search degrading to lexical is fine; losing a user's clips is not.
4. **Backfill** — a one-off script for existing moments. Without it, search only finds videos uploaded after the deploy.
5. **Endpoint** — `GET /videos/search?q=`. Embed the query, `ORDER BY embedding <=> :q` with a distance cutoff, `LIMIT ~40`, join up to videos, merge with an `ILIKE` pass over `videos.filename`, dedupe by video with the best-matching moment attached.
6. **Frontend** — the rail's search box switches to a debounced (~250ms) call, showing video title plus the matching clip title underneath. Falls back to the client-side filter if the request fails.

## Cost and honesty

Embedding calls are negligible (~10 short strings per video, one query embedding per search). The real cost is the moving parts: an extension, a migration, a backfill, a new external call in the hot pipeline path. That is why it is Phase 2 and why the detect hook must never be able to break rendering.

---

## Verification

Phase 1, on a deploy (no test harness — this is checked by using it):

1. Sign in with an account that has several videos. The rail lists all of them, newest first, processing ones greyed.
2. Click through three different videos. Each gets its own URL. Refresh on one — it stays put. Back button walks the history.
3. Click back to a video already visited — clips appear immediately, no skeleton flash. That is the cache working.
4. Start a render on video A, click to video B in the rail, come back. Still rendering or already ready. That is `useClipRenders` surviving navigation.
5. Upload a new video from `/`. It shows under "Working on it", the 15s poll flips it to ready on its own, and it appears in the rail without a manual refresh.
6. Delete the video you are viewing — lands on `/`. Delete a different one from the rail — stays put.
7. Hit `/v/` with a made-up UUID: "We can't find that stream", not a crash or a spinner forever.
8. Narrow the window past 920px: rail becomes a drawer, opens from the TopBar button, closes on navigation. No horizontal scrollbar at any width.
9. Sign out, hit `/v/<real id>`: Landing page, no rail.

Phase 2 adds: search "pricing" (or whatever a clip is actually about) and confirm the right video comes back with the matching clip title; confirm a video uploaded before the backfill is still findable by filename.
