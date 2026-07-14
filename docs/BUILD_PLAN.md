# Clipper — Build Plan

> Execution plan for [ARCHITECTURE.md](ARCHITECTURE.md). Read that first; this doc assumes its vocabulary (stages, layers, queues).

---

## 0. How we work (the process, before the tasks)

These are the habits that make big-company engineering actually ship:

1. **Vertical slices, walking skeleton first.** Milestone 1 ends with a video flowing through a *trivial* end-to-end pipeline (upload → fake job → status → UI shows "ready"). Every later milestone thickens one stage. You always have a working product; you never have "80 % done, nothing runs."
2. **Strangler pattern for the migration.** The current Modal/Mongo path keeps working while the new path is built behind a flag (`PIPELINE=v2`). Cut over per-feature, delete old code only after the new path has processed real videos. Never a big-bang rewrite.
3. **Definition of Done, every milestone:** code merged to `main` via PR • runs locally (`uvicorn` + `rq worker`, pointed at the Supabase dev project + local/dev Redis) • deployed to Railway • demoed on a real video • `jobs` table shows sane cost/latency numbers. Not "works on my machine."
4. **Idempotency + logging from day one, dashboards later.** Every worker task follows the job contract (ARCHITECTURE §7). Structured logs with `video_id` on every line. Fancy observability waits; grep-able logs don't.
5. **Test what breaks, skip what doesn't.** Unit-test the pure logic (boundary snapping, transcript stitching, junk filtering, score math) hard — that's where quality lives and tests are cheap. Don't unit-test FFmpeg or Groq; instead keep one small integration test with a bundled 2-min sample video that runs the whole pipeline locally (local whisper provider, mocked Gemini).
6. **Prompts are code.** Versioned files in `backend/app/pipeline/prompts/`, `prompt_version` recorded on every run, and a tiny eval set (5–10 hand-labeled VODs with "these are the good moments") re-run on every prompt change. Never tune prompts by vibes in production.
7. **Track spend from commit one.** Every job writes `est_cost_usd`. Check `/admin/stats` weekly. The whole point of this rebuild is cost control — measure it.

**Branch/PR flow:** feature branches → PR → merge to `main` (existing habit, keep it). One milestone ≈ 1–3 PRs.

---

## Milestone 1 — Substrate + walking skeleton (~2–3 days)

**Goal:** new foundation running end-to-end with a no-op pipeline.

- [ ] Provision a Supabase project (dev + prod, or one project with separate schemas early on); grab the pooled connection string. Provision a Railway project with four services — `api`, `worker-io`, `worker-cpu`, `redis` (Railway plugin) — all pointed at the same repo, Nixpacks build, no Dockerfile. `.env.example` with every var documented.
- [ ] Add SQLAlchemy 2 + Alembic. Create `backend/app/db/` (engine, session, models) and migration 001 with the full schema from ARCHITECTURE §6 (all tables now, even ones used later — schema churn is cheaper on paper than in prod). Run it against Supabase.
- [ ] `backend/app/workers/`: RQ setup, queues `io` + `cpu`, the **job contract wrapper** (decorator that opens/closes the `jobs` row, idempotency hook, retry policy, metrics dict). This wrapper is the most-reused code in the system — write it carefully, unit-test it.
- [ ] Rewire `POST /videos/complete` behind `PIPELINE=v2` flag: insert video row (Supabase Postgres), enqueue a stub `ingest` job that sleeps 5 s and marks the video `ready`. Old Modal path still default.
- [ ] `GET /videos/{id}` polling endpoint returning `pipeline` state.
- [ ] Port Clerk user sync to Postgres (`users` table) — dual-write to Mongo until cutover.

**Done when:** locally, `uvicorn` + `rq worker` (pointed at the Supabase dev project and a dev Redis) → upload a video in the local frontend → watch status flip `processing → ready` via polling, `jobs` row shows the stub run. Same flow works after pushing to Railway.

## Milestone 2 — Ingest stage (~2 days)

**Goal:** real artifacts in R2 for every upload.

- [ ] `backend/app/pipeline/ingest.py`: probe → validate (reject unsupported codecs with friendly error) → audio extract → features (silencedetect + RMS) → keyframe index → thumbnail sprite → audio chunking at silences (~15 min chunks). All ffmpeg invocations as small tested helpers in `backend/app/pipeline/ffmpeg.py`; commands from ARCHITECTURE §8.1.
- [ ] Upload artifacts to the R2 layout (§5), update `videos.artifacts`, progress updates as chunks complete.
- [ ] Unit tests: features parser (silences/RMS from canned ffmpeg output), chunk-boundary picker. Integration: sample video → assert all artifact keys exist.

**Done when:** uploading the 2-min sample produces audio/features/keyframes/thumbs in R2 in < 30 s; a 1 h video in < 3 min.

## Milestone 3 — Transcription (~2 days)

**Goal:** word-accurate transcript, provider-agnostic.

- [ ] `backend/app/pipeline/transcription/`: `TranscriptionProvider` protocol; `groq.py` (verbose_json, word+segment granularity), `local.py` (faster-whisper small, for dev/tests), stub `deepgram.py` fallback wiring.
- [ ] Fan-out: one `transcribe` job per chunk on `io`; Redis counter fan-in; stitcher offsets timestamps, de-dupes overlap words, writes `transcripts` row + `words.json`.
- [ ] Fallback chain on repeated provider failure; provider/model recorded.
- [ ] Unit tests: stitcher (overlaps, offsets, empty chunks). Golden test: sample video transcript sanity (word count ±, monotonic timestamps).

**Done when:** 1 h video → complete transcript ≤ 5 min, `est_cost_usd ≈ $0.04`, and `PROVIDER=local` runs the same path offline.

## Milestone 4 — Detect: ranking + snapping (~3–4 days, the quality milestone)

**Goal:** ranked, junk-free, well-bounded moments. Spend the care here.

- [ ] Annotated-transcript builder (segments + feature markers → prompt text). Unit-tested formatting.
- [ ] `prompts/rank_v1.txt` + params; Gemini structured-output call with response schema (§8.3); `ranking_runs` row with cost + prompt_version.
- [ ] **Boundary snapper** (`pipeline/snapping.py`): pure function `(raw_start, raw_end, words, silences, bounds) → (start, end)` per §8.3 step 3. This gets the most unit tests in the repo — mid-sentence starts, no-silence tails, clamping, unmappable timestamps.
- [ ] Junk filter + `final` score blend; insert moments; video → `ready`.
- [ ] **Eval harness** (`backend/evals/`): 5+ hand-labeled real VODs (you know what the good moments are) → script reports precision/recall-ish overlap vs. labels per prompt version. Run before merging any prompt change.
- [ ] Wire `GET /videos/{id}/moments` to Postgres (latest run default).

**Done when:** a real 1–3 h VOD yields moments where you'd honestly post the top 5, zero mid-sentence starts in the top 10, and eval script beats the old full-video-Gemini output on your labels.

## Milestone 5 — Render + clips library (~2 days)

**Goal:** export works and clips persist.

- [ ] `pipeline/render.py`: range-seek + re-encode (§8.5) on `cpu` queue; `clips` row lifecycle `queued → rendering → ready`.
- [ ] Endpoints: `POST /moments/{id}/export`, `GET /clips/{id}` (re-presigns), `GET /videos/{id}/clips`, `PATCH /moments/{id}` (keep/dismiss + bounds→refined moment), `moment_events` writes.
- [ ] Kill the eager-cutting path for good.

**Done when:** export from the UI → downloadable clip ≤ 90 s later; clip list survives refresh (fixes the current vanish bug); dismissing a moment records an event.

## Milestone 6 — Frontend review experience (~3–4 days)

**Goal:** the debug UI becomes the product.

- [ ] Processing screen: 3 s polling of `GET /videos/{id}`, stage + % bar. Remove manual Refresh.
- [ ] **Review screen** (replaces `Moments.jsx` fallback-soup with the now-typed schema): ranked cards (title, reason, scores, duration) → click seeks a source-bound `<video>` to `start_sec` (free preview) → Keep / Dismiss → drag handles on a strip built from `thumbs.jpg` + energy timeline → Export button with progress → inline download.
- [ ] Clips library page on `GET /videos/{id}/clips`.
- [ ] Delete `MomentClipViewer` router-state hack; clip URLs always fetched by id.

**Done when:** a friend (not you) uploads a VOD and gets posted-quality clips downloaded without any explanation.

## Milestone 7 — Deploy + cutover (~2 days)

**Goal:** new stack in production, old stack retired.

- [ ] Promote the Railway `api`/`worker-io`/`worker-cpu` services and Supabase project to prod config; custom domain + auto-TLS on Railway, prod env vars set per-service (**rotate every key that ever sat in the committed `backend/.env`**).
- [ ] Point Vercel `VITE_API_URL` at the Railway `api` domain; CORS update.
- [ ] Confirm Supabase's built-in nightly backups are on (Pro tier); `/healthz` + external uptime ping; Sentry DSN in api + workers.
- [ ] Flip `PIPELINE=v2` default. Run both paths for ~1 week on real uploads; compare `jobs` costs vs. Modal invoices.
- [ ] Retire: Modal app, Mongo (export anything worth keeping first). Delete the dead code paths + committed `dist/`, `vite.*.log`.

**Done when:** production traffic runs entirely on Railway + Supabase; `/admin/stats` shows ≈ $0.20–0.30 per multi-hour video; Modal bill is $0.

## Milestone 8 — Verify stage + quotas (~2 days, post-cutover)

- [ ] Visual-verify job (§8.4) behind per-content-type flag; score blending; eval re-run to confirm it helps.
- [ ] Free-tier quota (N videos/user/mo) + daily global cost cap checked before enqueueing `detect`/`verify`.
- [ ] Source-file lifecycle cleanup job (§5).

## Later phases (designed, not scheduled)

In rough order of product value: **chat refinement** (intent parser → `rerank/adjust/more_like/rerender` ops, §9 — everything it needs already exists after M5) → **caption burn-in** (ASS from `words.json`) → **9:16 vertical crop** (static center/face crop first, tracking later) → **URL ingestion** (yt-dlp worker → R2, joins pipeline at ingest) → **diarization** (fills the reserved `speaker` field) → **SSE** replacing polling.

---

## Timeline & spend summary

| | |
|---|---|
| M1–M7 (usable, deployed product) | ~3 weeks of focused solo work |
| Infra during build | ~$15–25/mo Railway + Supabase free tier + pennies of API calls on test videos |
| Steady state after cutover | ~$20–45/mo fixed (Railway + Supabase Pro) + ~$0.25 marginal per 3 h VOD, **no GPU anywhere, no Docker anywhere** |

The single highest-leverage place to slow down and do it right: **Milestone 4**. Everything else is plumbing; that one is the product.
