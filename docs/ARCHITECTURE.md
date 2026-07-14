# Clipper — System Architecture

> **Status:** approved design, v1 (2026-07). Companion doc: [BUILD_PLAN.md](BUILD_PLAN.md).
> **Product:** upload a long-form video (stream VOD, podcast, match footage) → AI finds, ranks, and cuts the best short clips → user reviews, refines, and exports.

---

## 1. Design principles

These are the rules every technical decision below follows. When in doubt, come back here.

1. **The heavy compute never runs on our box.** Transcription and LLM ranking are API calls (Groq, Gemini). Our server only does orchestration and FFmpeg work on small byte ranges.
2. **Compute every expensive artifact exactly once.** Audio, transcript, and audio features are immutable after creation. Every later user action (re-rank, tweak, re-cut) reads from cache and costs cents.
3. **Render lazily, preview for free.** A moment is previewed by seeking the source video in the browser (R2 range requests). FFmpeg runs only when the user exports.
4. **LLMs propose, code cuts.** The LLM outputs *approximate* boundaries and scores. Deterministic code snaps boundaries to word timestamps and silence. FFmpeg does exact cutting. An LLM never computes a final timestamp.
5. **Append, never mutate.** New ranking runs, new clip versions, new moment states are new rows. Nothing a user has seen or exported is ever clobbered. This is what makes conversational refinement safe.
6. **Boring technology.** Every component is the most proven option that meets the requirement. Cleverness is spent in exactly two places: the ranking prompt and the boundary-snapping algorithm — because that's what separates good clips from junk.

---

## 2. System context

```
┌──────────────┐   presigned PUT    ┌─────────────────┐
│   Browser    │ ─────────────────► │  Cloudflare R2   │  sources/, audio/,
│ (React/Vite, │ ◄───────────────── │  (zero egress)   │  clips/, artifacts/
│  Vercel)     │   range GET (preview/download)────────┘
│              │
│  JSON + JWT  │
▼              │
┌──────────────┴──────────────────────────────────────────────┐
│                    Railway (three services, no Docker)       │
│                                                              │
│                 ┌──────────┐   ┌────────────────────────┐   │
│                 │ FastAPI  │──►│ Supabase Postgres       │   │
│                 │ (api)    │   │ (metadata, jobs,        │   │
│                 └────┬─────┘   │  moments, clips)        │   │
│                     │ enqueue  └────────────────────────┘   │
│                ┌────▼─────┐        ┌──────────────────┐     │
│                │  Redis   │───────►│ RQ workers        │     │
│                │ (Railway │        │  worker-io  (API  │     │
│                │  plugin) │        │   calls, ingest)  │     │
│                └──────────┘        │  worker-render    │     │
│                                    │   (FFmpeg)        │     │
│                                    └───┬──────────┬────┘     │
└────────────────────────────────────────┼──────────┼──────────┘
                                         │          │
                              ┌──────────▼───┐  ┌───▼─────────────┐
                              │ Groq Whisper │  │ Gemini 2.5 Flash │
                              │ (transcribe) │  │ (rank + verify)  │
                              └──────────────┘  └──────────────────┘
                    Auth: Clerk (JWT verify in API, webhook for user sync)
```

**What changed vs. the current codebase:** Modal is retired (GPU cost sink), Mongo → Supabase Postgres. `api`, `worker-io`, and `worker-render` become three Railway services built directly from the repo (Railway's Nixpacks builder — no Dockerfile, no Compose). Railway's TLS/routing replaces Caddy. Clerk, R2, FastAPI, and the React frontend stay.

## 3. Technology choices & rationale

| Layer | Choice | Why (and what we rejected) |
|---|---|---|
| API | **FastAPI** | Already built, async, typed. Never the bottleneck. |
| Metadata + job state | **Supabase (managed Postgres 16) + JSONB** | Transactions for job state, enums, indexes, `SKIP LOCKED` escape hatch. JSONB keeps schema flexibility for scores/params. Managed means no DB to patch/back up ourselves. *Rejected:* Mongo (no transactions across jobs/moments, 16 MB doc limit bit us with embedded moments), self-hosted Postgres (one more thing to operate for no benefit at this scale). |
| Queue | **Redis (Railway plugin) + RQ** | ~50 lines to production, native retries, `depends_on` chaining, per-queue workers. *Rejected:* Celery (config surface, no benefit at this scale), Modal (paying GPU rates for orchestration). |
| Transcription | **Groq `whisper-large-v3-turbo`** | ~$0.04/audio-hour, 3 h VOD in minutes, word timestamps via `verbose_json`. Provider abstraction keeps OpenAI/Deepgram as fallback and local faster-whisper for offline dev. *Rejected:* self-hosted GPU (the original cost sink), CPU whisper (3–6 h latency). |
| Ranking LLM | **Gemini 2.5 Flash** (text) | Key already provisioned; 1 M context fits a full 3 h transcript in ONE call; structured output; context caching makes refinement calls ~75 % cheaper. A/B Claude Haiku later. |
| Visual verify | **Gemini Flash video, `media_resolution: low`** | Only cheap native-video model family. Runs on top ~20 finalists only. |
| Cut/render | **FFmpeg + x264 `veryfast`** | Frame-accurate, deterministic, reads only the clip's byte range from R2 over HTTP (60 s from an 8 GB file downloads ~50 MB). *Rejected:* NVENC (needs GPU), pre-rendering all moments (renders junk). |
| Storage | **Cloudflare R2** | Zero egress — the same bytes are read many times (preview, verify, render, download). |
| Auth | **Clerk** | Already integrated (JWT + svix webhook). |
| Hosting | **Railway** | Deploys straight from git, no Dockerfile/Compose to maintain, auto-TLS, per-service scaling for `api`/`worker-io`/`worker-render`. *Rejected:* VPS + Docker Compose (one more layer to operate; explicit non-goal, no Docker). Frontend stays on Vercel. |
| Status updates | **Polling (MVP) → SSE (later)** | 3 s polling is fine; SSE when the review UX matures. |

## 4. Latency & cost model (3-hour VOD, the pessimistic-friendly case)

| Stage | Wall clock | Marginal cost |
|---|---|---|
| Upload (browser → R2, user's bandwidth) | user-dependent | $0 |
| Ingest: audio extract + features + thumbs (parallel ffmpeg) | 3–6 min | ~$0 (own CPU) |
| Transcribe (Groq, chunks in parallel) | 2–5 min (overlaps ingest) | ~$0.12 |
| Detect: one Gemini ranking call over full transcript | 1–2 min | ~$0.05–0.10 |
| Verify: top 20 moments, low-res video scoring | 3–5 min (optional) | ~$0.03–0.05 |
| **Upload-complete → reviewable moments** | **~8–12 min** | **~$0.20–0.30** |
| Render one exported clip | 30–60 s | ~$0.01 |
| Any refinement op (re-rank / adjust / re-cut) | seconds–1 min | $0.01–0.05 |

Fixed costs: Railway usage-based compute (~$15–25/mo for `api` + two workers at this scale) + Supabase free/Pro tier (~$0–25/mo), R2 ~$0.015/GB-mo stored, Clerk/Vercel free tiers. **There is no GPU anywhere.**

Pessimistic case (Groq degraded/slow, big queue): provider fallback (Deepgram/OpenAI) keeps transcription < 15 min; worst realistic time-to-moments ~30–40 min. Concurrency does not stack: 10 simultaneous uploads = 10 parallel API calls, not a serial CPU queue.

## 5. R2 storage layout

```
sources/{video_id}/original.{ext}         immutable source upload
artifacts/{video_id}/audio.ogg            16 kHz mono Opus ~32 kbps (~45 MB for 3 h)
artifacts/{video_id}/audio/chunk_{n}.ogg  transcription chunks (deleted after stitch)
artifacts/{video_id}/words.json           word-level timestamps (too big for a DB row)
artifacts/{video_id}/features.json        energy/silence timeline
artifacts/{video_id}/keyframes.json       keyframe timestamps (seek math)
artifacts/{video_id}/thumbs.jpg           sprite sheet, 1 frame / 10 s
clips/{video_id}/{clip_id}.mp4            rendered exports
```

Lifecycle rule (R2 object lifecycle or nightly job): delete `sources/` N days after last activity on free tier; `artifacts/` are tiny and kept (they make re-work free); `clips/` kept.

## 6. Data model (Postgres)

```sql
create table users (
  id          uuid primary key default gen_random_uuid(),
  clerk_id    text unique not null,
  email       text,
  name        text,
  created_at  timestamptz not null default now()
);

create type video_status as enum ('uploading','uploaded','processing','ready','error');

create table videos (
  id            uuid primary key,                    -- generated at /videos/init
  user_id       uuid not null references users(id),
  filename      text not null,
  size_bytes    bigint,
  duration_sec  numeric,
  status        video_status not null default 'uploading',
  r2_key        text not null,
  content_type  text not null default 'default',     -- default | stream | podcast | football
  artifacts     jsonb not null default '{}',         -- {audio_key, words_key, features_key, keyframes_key, thumbs_key}
  pipeline      jsonb not null default '{}',         -- {stage, progress_pct, error}
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index videos_user_idx on videos(user_id, created_at desc);

create table transcripts (
  video_id     uuid primary key references videos(id) on delete cascade,
  language     text,
  model        text not null,
  segments     jsonb not null,                       -- [{start, end, text, speaker: null}]
  words_r2_key text not null,
  created_at   timestamptz not null default now()
);

-- One row per analysis pass. "Find funnier ones" = a new run; old runs remain.
create table ranking_runs (
  id             uuid primary key default gen_random_uuid(),
  video_id       uuid not null references videos(id) on delete cascade,
  params         jsonb not null default '{}',        -- {tone, target_platform, min_len, max_len, user_instruction}
  prompt_version text not null,
  model          text not null,
  status         text not null default 'running',    -- running | done | error
  est_cost_usd   numeric,
  created_at     timestamptz not null default now()
);

create table moments (
  id                 uuid primary key default gen_random_uuid(),
  video_id           uuid not null references videos(id) on delete cascade,
  run_id             uuid not null references ranking_runs(id),
  start_sec          numeric not null,               -- SNAPPED, final
  end_sec            numeric not null,
  raw_start_sec      numeric,                        -- what the LLM proposed (debugging/tuning)
  raw_end_sec        numeric,
  scores             jsonb not null,                 -- {hook, completeness, shareability, visual, final}
  type               text,                           -- funny | hype | insight | play | ...
  title              text,
  reason             text,                           -- LLM's one-line justification (shown in UI)
  transcript_excerpt text,
  status             text not null default 'candidate',  -- candidate | kept | dismissed
  source             text not null default 'auto',       -- auto | refined | manual
  created_at         timestamptz not null default now()
);
create index moments_video_run_idx on moments(video_id, run_id, (scores->>'final') desc);

create table clips (
  id             uuid primary key default gen_random_uuid(),
  moment_id      uuid references moments(id),
  video_id       uuid not null references videos(id) on delete cascade,
  user_id        uuid not null references users(id),
  version        int not null default 1,
  parent_clip_id uuid references clips(id),          -- "make it shorter" chains here
  params         jsonb not null,                     -- {start, end, format:'16:9'|'9:16', captions:bool, crop}
  r2_key         text,
  status         text not null default 'queued',     -- queued | rendering | ready | error
  created_at     timestamptz not null default now()
);
create index clips_video_idx on clips(video_id, created_at desc);

-- Observability + idempotency + cost accounting. One row per pipeline task execution.
create table jobs (
  id          uuid primary key default gen_random_uuid(),
  video_id    uuid references videos(id) on delete cascade,
  clip_id     uuid references clips(id),
  type        text not null,        -- ingest | transcribe | detect | verify | render
  status      text not null default 'queued',  -- queued | running | done | error
  attempt     int not null default 1,
  rq_job_id   text,
  started_at  timestamptz,
  finished_at timestamptz,
  error       text,
  metrics     jsonb not null default '{}',     -- {cpu_seconds, audio_seconds, tokens_in, tokens_out, est_cost_usd}
  created_at  timestamptz not null default now()
);
create index jobs_video_idx on jobs(video_id, created_at desc);

-- User feedback = future training signal + drives "more like this".
create table moment_events (
  id         uuid primary key default gen_random_uuid(),
  moment_id  uuid not null references moments(id) on delete cascade,
  user_id    uuid not null references users(id),
  action     text not null,   -- keep | dismiss | export | adjust_bounds | more_like_this
  payload    jsonb not null default '{}',
  created_at timestamptz not null default now()
);
```

**Why moments are their own table (not embedded in videos):** versioned runs, per-moment state transitions, indexed ranking queries, no document-size ceiling — and refinement appends rows instead of rewriting a blob.

## 7. Job & queue design

### Queues

| Queue | Workers | Concurrency | Jobs |
|---|---|---|---|
| `io` | worker-io | high (jobs are API waits) | transcribe chunks, detect, verify |
| `cpu` | worker-cpu | ~cores/2 | ingest (ffmpeg), render |

Two separate Railway services (`worker-io`, `worker-cpu`), each `railway up` from the same repo with a different start command — no shared container. Render is isolated on `cpu` so a render burst can never starve the pipeline, and vice versa.

### Pipeline DAG per video

```
POST /videos/complete
  └─► ingest (cpu) ──┬─► transcribe (io, chunks fan-out → stitch)──┐
                     └─► features already done inside ingest       ├─► detect (io) ─► [verify (io)] ─► status: ready
                                                                   ┘
render (cpu) is enqueued independently, on user export only.
```

Chaining is explicit: each task's last act is `enqueue(next_stage, depends_on=self)` or a fan-in check (transcribe chunks decrement a Redis counter; the last one enqueues `detect`).

### Job contract (every task follows this)

1. **Open:** insert/claim `jobs` row → status `running`, record `rq_job_id`, `started_at`.
2. **Idempotency check first:** if the output artifact already exists (R2 key present / DB row exists), mark `done` and exit. This makes retries, requeues, and partial reprocessing free.
3. **Work**, writing progress to `videos.pipeline` (`{stage, progress_pct}`) at coarse intervals.
4. **Close:** write `metrics` (including `est_cost_usd` — computed from audio seconds / token counts at current prices), status `done`, enqueue next stage.
5. **On exception:** RQ `Retry(max=3, interval=[10, 60, 300])`. Final failure → `jobs.status='error'`, `videos.pipeline.error` set, video status `error`. Failed jobs land in RQ's failed registry; an admin endpoint can requeue.

**Cost accounting is not optional.** `sum(metrics.est_cost_usd)` per video/user/day is a one-line SQL query. This is how we notice a cost regression in hours, not on the invoice.

## 8. Pipeline stages in detail

### 8.1 Ingest (cpu queue)

Input: `sources/{video_id}/original.ext` in R2. All ffmpeg reads use a presigned URL — the source is streamed, and only fully downloaded when unavoidable.

```bash
# a) Probe (duration, streams, resolution) — header reads only
ffprobe -v error -print_format json -show_format -show_streams "$SRC_URL"

# b) Audio: 16 kHz mono Opus. 3 h video → ~45 MB. THE only full read of the source.
ffmpeg -i "$SRC_URL" -vn -ac 1 -ar 16000 -c:a libopus -b:a 32k audio.ogg

# c) Features from the small local audio file (fast):
ffmpeg -i audio.ogg -af silencedetect=noise=-35dB:d=0.4 -f null - 2> silences.txt
ffmpeg -i audio.ogg -af astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level -f null - 2> rms.txt
#    → features.json: [{t, rms_db}] at 0.5 s resolution + [{silence_start, silence_end}]

# d) Keyframe index (from source, packet metadata only — cheap):
ffprobe -v error -select_streams v -show_entries packet=pts_time,flags -of csv "$SRC_URL" | grep K
#    → keyframes.json

# e) Thumbnail sprite for the scrubber: 1 frame / 10 s tiled
ffmpeg -i "$SRC_URL" -vf "fps=1/10,scale=160:-1,tile=10x{rows}" -frames:v 1 thumbs.jpg
```

Also inside ingest: split `audio.ogg` into transcription chunks (~15 min each, cut at the nearest detected silence to avoid splitting words), upload all artifacts to R2, update `videos.artifacts`, enqueue one `transcribe` job per chunk.

### 8.2 Transcribe (io queue, fan-out)

Per chunk: POST to Groq `audio/transcriptions`, `model=whisper-large-v3-turbo`, `response_format=verbose_json`, `timestamp_granularities=["word","segment"]`. Offset every timestamp by the chunk's start. Fan-in (Redis counter) → stitch chunks, drop duplicate words in overlap zones, write `transcripts` row (segments) + `words.json` to R2.

- **Provider abstraction:** `TranscriptionProvider` interface with `groq` (primary), `openai`/`deepgram` (fallback on 5xx/429 after retries), `local-faster-whisper` (dev machines, tests). Provider + model recorded on the transcript row.
- Chunking sidesteps per-file size limits *and* parallelizes: a 3 h VOD transcribes in the time of one 15-min chunk.

### 8.3 Detect (io queue) — the quality-critical stage

**Step 1 — build the annotated transcript.** Render segments as numbered lines with `[h:mm:ss]` stamps, interleaved with feature markers derived from `features.json`:

```
[0:42:07] and he actually said yes on the spot
<LOUD +9dB spike, crowd/laughter 0:42:11–0:42:19>
[0:42:20] I could not believe it, chat went insane
<SILENCE 2.8s>
[0:42:31] okay so next topic...
```

**Step 2 — one structured-output Gemini call** (full transcript fits in context for ≤ ~4 h). Response schema (enforced, not prose-parsed):

```json
{ "moments": [{
    "start": "h:mm:ss", "end": "h:mm:ss",
    "type": "funny|hype|insight|play|wholesome|drama",
    "title": "≤8 words, written like a caption",
    "hook_line": "the exact transcript line that would open the clip",
    "reason": "one sentence: why a cold viewer stops scrolling",
    "scores": {"hook": 0-10, "completeness": 0-10,
               "shareability": 0-10, "context_independence": 0-10}
}]}
```

Prompt core (versioned in-repo, `prompt_version` recorded on the run):

```
You are ranking candidate clips from a {content_type} recording for short-form
social media (TikTok/Reels/Shorts). You receive the full transcript with
timestamps and audio-energy annotations (<LOUD>, <SILENCE>, laughter).

Find up to {max_moments} moments. Score each 0–10 on:
- hook: do the FIRST 3 SECONDS make a cold viewer stop scrolling?
- completeness: are setup AND payoff both inside the clip?
- shareability: would someone send this to a friend?
- context_independence: understandable with zero knowledge of this channel?

HARD RULES:
- start/end MUST be timestamps that appear in the transcript. Never invent times.
- REJECT: moments that start mid-sentence, need unseen context, have no payoff,
  or duplicate a better moment. Fewer great moments beat many mediocre ones.
- Target clip length {min_len}–{max_len} seconds.
{user_instruction}   ← empty for auto runs; filled by refinement ("funnier", "more gameplay")
```

**Step 3 — deterministic boundary snapping (code, no LLM):**

1. Map LLM `start` to the word timeline (`words.json`). Walk **backwards** to the start of the sentence (previous word ends with `.?!` or inter-word gap ≥ 0.6 s). Pad −0.25 s.
2. Walk `end` **forwards** to the sentence end, then extend to the next silence ≥ 0.4 s (from `features.json`) so the cut lands in a natural pause, not mid-breath.
3. Clamp to `[min_len, max_len]`; if clamping breaks completeness, prefer trimming the setup, never the payoff.
4. Store both raw (LLM) and snapped values — the delta is our tuning signal.

**Step 4 — programmatic junk filter:** drop overlaps > 60 % (keep higher `final`), drop `hook < 4`, compute `final = 0.4·hook + 0.25·shareability + 0.2·completeness + 0.15·context_independence`. Insert `moments` rows, mark run `done`, video `ready`.

### 8.4 Verify (io queue, optional — default ON for `stream`/`football`)

For the top ~20 by `final`: extract a low-res segment **without downloading the source** —

```bash
ffmpeg -ss {start} -i "$SRC_URL" -t {dur} -vf scale=-2:480 -r 8 -c:v libx264 -preset ultrafast -an seg.mp4
```

— send to Gemini Flash (`media_resolution: low`) asking only: *visual interest 0–10, does anything visually important happen, is the moment visually dead?* Blend: `final = 0.8·final + 0.2·visual`; drop `visual ≤ 2` (talking-head dead air). Catches visual-only moments and kills visually-dead ones — at pennies, because it never sees more than ~10 min of low-res video per VOD.

### 8.5 Render (cpu queue, on user export only)

```bash
# Coarse seek via HTTP range (-ss before -i), fine seek after, frame-accurate re-encode.
ffmpeg -ss {start-2} -i "$SRC_URL" -ss 2 -t {dur} \
       -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 128k \
       -movflags +faststart clips/{video_id}/{clip_id}.mp4
```

~30–60 s of CPU for a 60 s 1080p clip; downloads only the clip's byte neighborhood. Future render params slot in here as filters: `9:16` crop (later: face/subject tracking), caption burn-in from `words.json` (ASS subtitles → `subtitles=` filter), watermark. `clips.params` already carries them.

## 9. Versioning & conversational refinement

Three append-only layers:

| Layer | Contents | Mutability | Cost to regenerate |
|---|---|---|---|
| 1. Sources | video, audio, transcript, features, keyframes | immutable | n/a (never regenerated) |
| 2. Analysis | `ranking_runs` → `moments` | append new runs | $0.02–0.10, seconds |
| 3. Outputs | `clips` (versioned, `parent_clip_id`) | append new versions | ~$0.01, ~1 min |

The conversational layer (post-MVP) is an **intent parser, not an agent**: a cheap model maps chat to a closed set of operations —

- `rerank(instruction, params)` → new ranking_run over the cached transcript (Gemini context caching makes repeat calls ~75 % cheaper)
- `adjust_bounds(moment_id, delta_start, delta_end)` → new moment (`source='refined'`), pure code
- `more_like(moment_id)` → rerank seeded with that moment's excerpt + the user's keep/dismiss history from `moment_events`
- `rerender(clip_id, params)` → new clip version pointing at parent

Every operation hits layers 2–3 only. **Chat can never trigger re-transcription.** Undo = point back to the parent row. Existing exports never break because nothing they reference is ever mutated.

## 10. API surface

```
POST   /videos/init                 → {video_id, upload_url}          (exists)
POST   /videos/complete             → enqueue pipeline                 (exists, rewire)
GET    /videos                      → list w/ status                   (exists)
GET    /videos/{id}                 → {status, pipeline:{stage,progress_pct,error}, duration, artifacts.thumbs_url}   ← polling target
GET    /videos/{id}/moments?run_id= → ranked moments (default: latest run)
GET    /videos/{id}/transcript
POST   /videos/{id}/rank            → {instruction?, params?} → new ranking_run (202 + run_id)
PATCH  /moments/{id}                → {status: kept|dismissed} | {start_sec, end_sec}  (bounds → new refined moment)
POST   /moments/{id}/export         → {format?, captions?} → clip row + render job (202 + clip_id)
GET    /clips/{id}                  → {status, url?}                   ← poll until ready
GET    /videos/{id}/clips           → clip library (fixes clips-vanish-on-refresh)
DELETE /videos/{id}                 → cascade: R2 prefixes + rows      (exists)
POST   /auth/clerk-auth             → Clerk webhook                    (exists)
```

Auth: every route except the webhook requires the Clerk JWT (existing `get_current_user`); every query is scoped `where user_id = :current_user`. All R2 URLs returned to clients are presigned and short-lived (24 h download, 1 h upload).

## 11. Frontend UX flows

1. **Upload** (exists): picker → presigned PUT with progress → complete. Content-type select stays.
2. **Processing:** poll `GET /videos/{id}` every 3 s; stage progress bar ("Transcribing… 60 %"). Replaces the manual Refresh button.
3. **Review (the core screen):** ranked moment cards (title, reason, scores, timecodes) → clicking **previews instantly** by seeking a `<video>` bound to the presigned *source* URL (zero render). Thumbnail sprite + energy timeline as a scrubber strip. Keep / Dismiss (→ `moment_events`). Drag handles adjust bounds (PATCH). **Export** button → render job → poll clip → download. 
4. **Clips library:** `GET /videos/{id}/clips` — survives refresh, re-presigns URLs.
5. **Later — chat panel** on the review screen driving the refinement ops (§9).

## 12. Operations

- **Deploy:** Railway project with four services — `api`, `worker-io`, `worker-cpu`, `redis` (Railway plugin) — each built from the repo via Nixpacks (no Dockerfile). Supabase project holds Postgres, provisioned separately. Frontend on Vercel (unchanged). Deploy = `git push` → Railway auto-builds/redeploys each service (CI later).
- **Backups:** Supabase's built-in nightly Postgres backups (Pro tier, 7–14 day retention) — no `pg_dump` cron to run ourselves. R2 data is the durable store for artifacts/clips.
- **Logging:** JSON logs (structlog) with `video_id`/`job_id` on every line; Railway's built-in log viewer/export is grep-able. Sentry (free tier) for exceptions in api + workers.
- **Metrics:** the `jobs` table IS the metrics store — latency per stage, cost per video/user/day, failure rates — all plain SQL. Admin endpoint `/admin/stats` surfaces them. Uptime: external ping on `/healthz`.
- **Secrets:** Railway's per-service environment variables (never committed — note: rotate anything from the previously committed `backend/.env`). Keys: Supabase Postgres URL, Railway Redis URL, R2, Clerk, `GROQ_API_KEY`, `GEMINI_API_KEY`.

## 13. Failure modes & handling

| Failure | Handling |
|---|---|
| Groq 429/5xx | RQ retry ×3 backoff → provider fallback (Deepgram/OpenAI) → job error surfaced in UI with retry button |
| Gemini malformed/empty output | Structured-output schema + one re-ask; then run `error`, prior runs still shown |
| LLM invents timestamps | Snapping rejects anything not mappable to the word timeline; unmappable moment dropped, logged with prompt_version |
| FFmpeg fails on odd container/codec | Ingest probe validates up front; unsupported → immediate friendly error, no wasted pipeline |
| Worker dies mid-job | RQ requeues (job timeout); idempotency check skips completed sub-steps |
| Railway service dies | Railway auto-restarts the service; R2 is the durable artifact store, Supabase holds durable metadata — no local disk to lose. |
| Cost runaway | Per-job `est_cost_usd` + daily cap check before enqueueing detect/verify (per-user quota, free tier: N videos/mo) |

## 14. Scaling path (in order — don't do these early)

1. Bump replica count / instance size on the Railway worker services → 2) split `worker-io`/`worker-cpu` across more Railway replicas (Redis/Supabase already reachable over the network, no re-architecture needed) → 3) Supabase compute add-on (bigger Postgres instance) → 4) self-hosted Parakeet/faster-whisper on one rented GPU **only when** Groq spend > ~$300/mo → 5) SSE, CDN in front of clips, multi-region. The architecture doesn't change shape for any of these.

## 15. Non-goals (explicit)

- No Kubernetes, no Celery, no Kafka, no microservices, no Docker/Compose to hand-operate — one repo, platform-managed deploys.
- No pre-rendering of all detected moments. Ever.
- No full-video multimodal LLM passes.
- No LLM-computed final timestamps.
- MVP defers: URL/yt-dlp ingestion, diarization, vertical-crop tracking, caption burn-in, chat refinement — all have designed seams (§8.5, §9, transcripts.speaker) but zero MVP code.
