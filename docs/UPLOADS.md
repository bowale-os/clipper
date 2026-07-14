# Video uploads (single PUT + multipart)

How uploads work after the multipart rewrite, plus the one-time R2 configuration it needs.

## Flow

- Files **< 100 MiB**: `POST /videos/init` returns `{mode: "single", upload_url}` — one presigned PUT, same as before.
- Files **≥ 100 MiB**: `init` returns `{mode: "multipart", upload_id, part_size, part_count}`. The browser slices the file into fixed **16 MiB** parts and uploads **4 in parallel**, fetching presigned part URLs in batches of 100 from `POST /videos/{id}/parts`. Each part retries up to 3 times with backoff (re-signing on 403). `POST /videos/complete` finalizes with the collected `[{part_number, etag}]` list.
- **Resume**: if the page is refreshed mid-upload, the video stays in "uploading". The videos page shows a *Resume upload* button → the user re-selects the same file (must match byte size exactly) → `GET /videos/{id}/upload-status` lists the parts already in R2 and only the missing ones are uploaded.
- **Cancel/abort**: the Cancel button (or `POST /videos/{id}/abort`, or deleting the video) aborts the R2 multipart upload so incomplete parts don't accrue storage.
- R2 keys follow ARCHITECTURE §5: `sources/{video_id}/original.{ext}`.
- Limits: 16 MiB × 10,000 parts = **156 GiB max** file size (rejected with 413 at init).

## One-time R2 configuration (required)

### 1. CORS policy — multipart fails without this

Cloudflare dashboard → R2 → bucket → **Settings → CORS policy**:

```json
[
  {
    "AllowedOrigins": [
      "http://localhost:5173",
      "https://clippper.vercel.app",
      "https://clippper.fyi",
      "https://www.clippper.fyi"
    ],
    "AllowedMethods": ["PUT", "GET"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

`"ExposeHeaders": ["ETag"]` is the critical line: the browser must read each part's ETag response header to finalize the upload. Without it every multipart upload fails at the complete step (the UI surfaces a CORS hint when this happens).

### 2. Lifecycle rule — clean up abandoned uploads

Bucket → **Settings → Object lifecycle rules** → add a rule to **abort incomplete multipart uploads after 7 days**. The backend already tolerates this (`upload-status` returns `resumable: false, reason: "upload_expired"` and marks the video as errored).

## Database

`videos.size_bytes` was widened to `bigint` (migration `a4c9d02f31e7`) — run `alembic upgrade head` in any environment that hasn't applied it. Transient multipart state (`upload_id`, `part_size`, `part_count`) lives in `videos.pipeline["upload"]` and is removed when the upload completes or aborts.
