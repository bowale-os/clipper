# Changelog — Multipart upload + Postgres rewrite of the video API

> Date: 2026-07-13
> Scope: fast large-video uploads (S3 multipart to Cloudflare R2, parallel parts, retry + resume) and the rewrite of the upload path from the deleted Mongo/Modal (v1) stack onto the new Postgres layer (v2, per [ARCHITECTURE.md](ARCHITECTURE.md)).
> Companion doc: [UPLOADS.md](UPLOADS.md) — how the upload flow works + required R2 configuration.

---

## Why

- Long videos previously uploaded through **one** presigned PUT: no parallelism, and any network hiccup restarted the whole upload.
- The backend didn't boot: `video.py`, `clips.py`, and `auth.py` still imported `app/services/mongo_client.py` and `modal_client.py`, which were deleted as part of the v1→v2 migration.

## Behavior summary

| File size | Upload path |
|---|---|
| < 100 MiB | Single presigned PUT (unchanged behavior, new `sources/` key layout) |
| ≥ 100 MiB | S3 multipart to R2: fixed 16 MiB parts, 4 parallel part uploads, per-part retry ×3 with backoff, URL re-signing on 403, resume after page refresh, cancel/abort |
| > 156 GiB | Rejected with 413 at init (16 MiB × 10,000-part S3 limit) |

---

## Backend changes

### `backend/app/config/secrets.py`
- `MONGO_CONNECT`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` are now `Optional[str] = None` (legacy v1 — the server must boot without them).

### `backend/requirements.txt`
- Removed `pymongo` and `modal==1.4.3`.

### `backend/app/db/models.py`
- `Video.size_bytes`: `Integer` → `BigInteger`. Postgres `integer` caps at ~2 GiB, which would overflow for exactly the large files multipart targets.

### `backend/alembic/versions/a4c9d02f31e7_videos_size_bytes_bigint.py` (new)
- Migration widening `videos.size_bytes` to `bigint`. **Already applied to the Neon database** (`alembic upgrade head`, now at `a4c9d02f31e7`).

### `backend/app/dependencies/user.py` (new)
- `get_current_user_record`: FastAPI dependency mapping the Clerk JWT `sub` (from the existing `get_current_user`) to a `users` row. Get-or-create — covers Clerk accounts that predate the webhook — with an `IntegrityError` re-select for concurrent-request races.

### `backend/app/services/r2_client.py`
- Existing functions unchanged. Added the multipart toolkit:
  - `create_multipart_upload(r2_key, content_type) -> upload_id`
  - `generate_part_upload_urls(r2_key, upload_id, part_numbers) -> {n: presigned_url}` (1 h expiry)
  - `list_uploaded_parts(r2_key, upload_id)` — paginated ListParts, used for resume
  - `complete_multipart_upload(r2_key, upload_id, parts)` — ETags passed exactly as R2 returned them (quotes included)
  - `abort_multipart_upload(r2_key, upload_id)`
  - `head_object_size(r2_key)` — verifies single-PUT completion

### `backend/app/api/video.py` — full rewrite (Mongo → Postgres/SQLAlchemy)
All routes are now sync `def` (FastAPI threadpools them) with `Depends(get_db)` + `Depends(get_current_user_record)`. R2 keys follow ARCHITECTURE §5: `sources/{video_id}/original{ext}`. Transient multipart state lives in `videos.pipeline["upload"]` (`{mode, upload_id, part_size, part_count}`) and is removed at complete/abort.

| Endpoint | Change |
|---|---|
| `POST /videos/init` | Returns `{mode:"single", video_id, upload_url}` below 100 MiB, `{mode:"multipart", video_id, upload_id, part_size, part_count}` above. Rejects > 156 GiB (413). Aborts the R2 multipart upload if the DB insert fails. |
| `POST /videos/{id}/parts` **(new)** | Batch-signs up to 100 presigned part URLs on demand (also serves resume re-signing). 409 unless the video is mid-multipart-upload. |
| `GET /videos/{id}/upload-status` **(new)** | Resume anchor. Multipart: lists parts already in R2. Single: returns a fresh `upload_url`. If R2's lifecycle rule expired the upload (`NoSuchUpload`): marks the video `error`, returns `resumable:false, reason:"upload_expired"`. |
| `POST /videos/complete` | Idempotent. Multipart: validates exactly parts `1..part_count` and calls CompleteMultipartUpload (S3 errors surface as 400). Single: verifies object existence + size via HEAD. Pipeline enqueue is a logged `TODO(v2)` stub — `auto_detect` is accepted but not acted on yet. |
| `POST /videos/{id}/abort` **(new)** | Aborts the R2 multipart upload and deletes the row. |
| `GET /videos/` | One SQL query, grouped by status. **`analyzed_videos` → `ready_videos`** (v2 status enum). |
| `GET /videos/{id}/metadata` | Returns cached `duration_sec` or `null`; the Modal duration probe is gone (`TODO(v2)`: ingest worker fills it). |
| `GET /videos/{id}/moments` | Reads the `moments` table (empty until the pipeline exists); same response shape. |
| `DELETE /videos/{id}` | Aborts an in-flight multipart upload first, deletes the R2 object, then the row (FK cascades cover transcripts/moments/clips/jobs). |

### `backend/app/api/auth.py`
- Clerk `user.created` webhook now upserts into the Postgres `users` table (`ON CONFLICT (clerk_id) DO UPDATE`) instead of inserting into Mongo. Backfills email/name onto stub rows created by `get_current_user_record`; webhook replays are harmless.

### `backend/app/api/clips.py`
- Minimal boot fix: dead `modal`/`mongo_client` imports removed; `POST /clips/create` returns **501** ("being migrated") until the v2 render pipeline exists. Route kept so the frontend gets a sane error, not a 404.

---

## Frontend changes (`frontend/clippper/`)

### `src/services/multipartUpload.js` (new) — chunked upload engine
- `runMultipartUpload(...)`: slices the file into `part_size` chunks, uploads with a 4-worker pool, lazily fetches presigned URL batches of 100 as workers drain them, retries each part ×3 with exponential backoff (re-signs on 403), aggregates per-part bytes into a single 0–100 progress value (held at 99 until `/complete` confirms), supports cancellation via `AbortSignal`, and skips parts already in R2 on resume.
- Throws a descriptive error if the part ETag response header is unreadable (missing `ExposeHeaders: ["ETag"]` in the R2 CORS policy).

### `src/services/api.js`
- `requestJson` (and all endpoint helpers) accept a `getToken` async provider in addition to a fixed `token` — Clerk tokens expire in ~60 s, so long uploads fetch a fresh token per request.
- New helpers: `getPartUploadUrls`, `getUploadStatus`, `abortVideoUpload`. `completeVideoUpload` now sends the multipart `parts` list. `initVideoUpload` validates the mode-specific response shape.
- `uploadVideoFile` orchestrates: resume check (`upload-status`) or fresh `init` → single PUT or multipart engine → `complete`. New options: `getToken`, `signal`, `resume: {videoId}`, `onInit({videoId, mode})`.
- `uploadFileToSignedUrl` (single PUT) now supports an `AbortSignal`.

### `src/hooks/useAuthedApi.js`
- Now also exposes `getFreshToken` (per-request token provider) and `handleExpiredAuth`; `runWithToken` is unchanged for existing callers.

### `src/hooks/useVideoUpload.js`
- Uses `getFreshToken` instead of one token for the whole upload.
- New state/actions: `resumeTarget`, `startResume(video)`, `cancelUpload()` (aborts in-flight XHRs, then `POST /videos/{id}/abort`).
- On resume, the re-selected file must match the original **byte size exactly** (parts are byte-offset slices); mismatch is a hard error.

### `src/components/VideoUploadCard.jsx`
- Resume mode: header/picker/prompt change to *Re-select "{filename}" to resume*, primary button becomes **Resume upload**.
- **Cancel** button while an upload is in flight (replaces Clear).

### `src/pages/DashBoard.jsx`
- Reads a resume target from `location.state.resume` (set by the videos page) and passes it into `VideoUploadCard`.

### `src/pages/Videos.jsx`
- **Resume upload** button on rows in "Uploading videos" → navigates to the dashboard with the resume target. (Delete already aborts an in-flight multipart upload server-side.)
- Renamed `analyzed_videos`/`analyzed` → `ready_videos`/`ready` to match the v2 status enum; reads `size_bytes` (falls back to legacy `size`).

---

## Manual steps (operator)

1. **R2 CORS policy** must expose the `ETag` header — required for multipart. Exact JSON in [UPLOADS.md](UPLOADS.md).
2. **R2 lifecycle rule**: abort incomplete multipart uploads after 7 days.
3. `alembic upgrade head` in any environment that hasn't applied `a4c9d02f31e7` (already applied to the current Neon DB).

## Verification status

- Backend imports and registers all routes (`app.main:app` loads with Mongo/Modal env vars absent).
- Alembic migration applied to Neon (`alembic current` → `a4c9d02f31e7 (head)`).
- Frontend production build passes (`pnpm build`).
- Not yet exercised end-to-end (needs the R2 CORS change + a signed-in browser session): small-file upload, ≥100 MiB multipart upload, kill-and-resume, cancel. Test plan is in the plan file / [UPLOADS.md](UPLOADS.md).

## Known follow-ups (out of scope here)

- `POST /videos/complete` logs a TODO instead of enqueueing the ingest→transcribe→detect pipeline (RQ workers don't exist yet — BUILD_PLAN milestones).
- `POST /clips/create` returns 501 pending the v2 render pipeline.
- `GET /videos/{id}/metadata` returns `duration: null` until the ingest worker fills `duration_sec`.
