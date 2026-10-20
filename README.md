# Clipper

Turn a long video into ready-to-post short clips, automatically.

Upload a stream VOD, podcast, lecture or match recording. Clipper transcribes it, finds the moments most worth sharing, snaps each one to clean start and end points, and renders captioned clips in the format you pick (vertical, square, landscape, or the original). Live at [clippper.fyi](https://clippper.fyi).

## Why it exists

Cutting highlights out of a multi-hour recording is slow manual work: scrub, guess, trim, caption, export. Clipper does the finding and cutting, and leaves the final call to you. You review the suggested moments, adjust them, and export only the ones you want.

**Who it is for:** streamers, podcasters, educators and anyone who publishes short-form video from long-form source material.

## Features

- Large uploads: resumable multipart upload straight from the browser to object storage, so the API never handles the file.
- Moment detection: an LLM reads the transcript, combined with audio loudness and silence data, and proposes ranked moments.
- Clean boundaries: the model only suggests rough times. Code snaps them to sentence and silence boundaries, so clips do not start or end mid-word.
- Captions burned in from word-level timestamps.
- Multiple output formats: 9:16, 1:1, 16:9, or the source's own dimensions.
- Search across your videos.
- Per-user accounts and rate limiting.

## How it works

```mermaid
flowchart LR
    user([User])

    subgraph vercel [Vercel]
        web[React app]
    end

    subgraph railway [Railway]
        api[FastAPI API]
        redis[(Redis)]
        subgraph workers [RQ workers]
            io["io worker<br/>ingest, transcribe, detect"]
            cpu["cpu worker<br/>render"]
        end
    end

    clerk[Clerk]
    r2[(Cloudflare R2<br/>videos and clips)]
    db[(Neon Postgres<br/>+ pgvector)]

    subgraph ai [AI providers]
        groq[Groq Whisper]
        deepseek[DeepSeek]
        gemini[Gemini embeddings]
    end

    user --> web
    web -- "sign in" --> clerk
    web -- "JSON + session token" --> api
    web -- "multipart upload via presigned URLs" --> r2
    web -- "preview and download" --> r2
    clerk -- "webhook: sync users" --> api

    api --> db
    api -- "enqueue jobs" --> redis
    redis --> io
    redis --> cpu

    io --> r2
    io --> db
    io --> groq
    io --> deepseek
    io --> gemini
    cpu --> r2
    cpu --> db
```

The same flow as a sequence, from upload to finished clip:

```mermaid
sequenceDiagram
    actor U as User
    participant W as React app
    participant A as FastAPI
    participant R as R2
    participant Q as Redis queue
    participant IO as io worker
    participant CPU as cpu worker

    U->>W: choose a video
    W->>A: POST /videos/init
    A-->>W: upload id and presigned part URLs
    W->>R: upload parts directly
    W->>A: POST /videos/complete
    A->>Q: enqueue ingest
    Q->>IO: ingest (FFmpeg analysis)
    IO->>IO: transcribe (Groq)
    IO->>IO: detect moments (DeepSeek, snap to boundaries)
    IO->>Q: enqueue render for each top moment
    W->>A: poll status, GET /videos/id/moments
    U->>W: pick moments and a format
    W->>A: POST /clips/create
    A->>Q: enqueue render
    Q->>CPU: render (FFmpeg cuts from R2)
    CPU->>R: write finished clip
    W->>A: GET /clips/id
    A-->>W: download link
```

Each uploaded video moves through four background stages. Every stage is idempotent and retried with backoff, so a flaky upstream API does not lose work.

| Stage | What it does | Tools |
|---|---|---|
| ingest | Probes the file, extracts audio, measures silence and loudness, finds keyframes, builds a thumbnail sprite | FFmpeg, ffprobe |
| transcribe | Speech to text with word-level timestamps | Groq (Whisper large v3) |
| detect | Splits the transcript into sections, extracts and scores moments, snaps boundaries, removes overlapping duplicates | DeepSeek, Gemini embeddings |
| render | Cuts the clip straight from the source over HTTP, burns in captions, encodes | FFmpeg (x264) |

Design decisions worth knowing:

- **Heavy compute is rented, not hosted.** Transcription and ranking are API calls. The servers only orchestrate and run FFmpeg.
- **Expensive work happens once.** Audio, transcript and audio features are stored and reused, so re-ranking or re-cutting costs very little.
- **LLMs propose, code decides.** No final timestamp ever comes from a model.
- **Append, never overwrite.** New rankings and clip versions are new rows, so nothing a user has already seen or exported changes under them.
- **Two queues.** CPU-bound renders and I/O-bound ingest, transcribe and detect run on separate workers, so a long ingest cannot stall an export.

Deeper notes live in [docs/](docs/): [ARCHITECTURE.md](docs/ARCHITECTURE.md) (original design and rationale), [UPLOADS.md](docs/UPLOADS.md) (multipart upload flow), [DESIGN.md](docs/DESIGN.md) and [UX.md](docs/UX.md).

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 19, Vite, React Router, Clerk |
| API | FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| Database | PostgreSQL on Neon, with pgvector |
| Queue | Redis, RQ |
| Storage | Cloudflare R2 (S3-compatible) |
| Auth | Clerk (JWT verified in the API, webhook syncs users) |
| AI | Groq (transcription), DeepSeek (moment detection), Gemini (embeddings) |
| Media | FFmpeg |
| Hosting | Vercel (frontend), Railway (API and workers) |

## Project layout

```
backend/
  app/
    api/          HTTP routes: auth, videos, clips
    tasks/        pipeline stages: ingest, transcribe, detect, render
    workers/      RQ queues, job contract (retries, idempotency), worker entrypoint
    services/     clients for Clerk, Groq, DeepSeek, Gemini, R2
    db/           SQLAlchemy models and session
    dependencies/ auth and rate limiting
  alembic/        database migrations
  tests/
frontend/clippper/  React app (pages, components, hooks, upload client)
brand-materials/    logos and icons
docs/               design and architecture notes
```

## Running it locally

### Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- FFmpeg and ffprobe on your `PATH`
- A Redis instance (for example `docker run -p 6379:6379 redis`)
- Accounts and keys for [Clerk](https://clerk.com), [Neon](https://neon.tech) (enable the `vector` extension), [Cloudflare R2](https://developers.cloudflare.com/r2/), [Groq](https://groq.com), [DeepSeek](https://platform.deepseek.com), and [Google AI Studio](https://aistudio.google.com) (Gemini)

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

Create `backend/.env`. The app refuses to start if any of these are missing:

```
SECRET_KEY=
ENV=dev
CLERK_SECRET_KEY=
CLERK_WEBHOOK_SIGNING_SECRET=
CLERK_FRONTEND_API=
CLERK_DEV_FRONTEND_API=
R2_ENDPOINT_URL=
R2_ACCESS_KEY=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
NEON_DB_CONNECT=postgresql://user:password@host/dbname
REDIS_URL=redis://localhost:6379
GROQ_API_KEY=
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
```

The R2 bucket also needs a CORS rule allowing `PUT` and `GET` from `http://localhost:5173`, since the browser uploads to it directly.

Apply the database migrations and start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In a second terminal (same virtualenv, still inside `backend/`), start a worker:

```bash
python -m app.workers.worker_setup
```

The worker must be started from `backend/` so the `app` package resolves. By default it drains both queues. Set `WORKER_QUEUES=cpu` or `WORKER_QUEUES=io` to run them as separate workers, as production does.

### 2. Frontend

```bash
cd frontend/clippper
npm install
```

Create `frontend/clippper/.env`:

```
VITE_API_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

```bash
npm run dev
```

Open http://localhost:5173, sign in, and upload a video.

### 3. Tests

```bash
cd backend
pytest
```

## Deployment

- **Frontend:** Vercel, using [vercel.json](frontend/clippper/vercel.json).
- **API:** Railway service started with `uvicorn app.main:app` ([railway.toml](backend/railway.toml)).
- **Workers:** Railway services started with `python -m app.workers.worker_setup` ([railway.worker.toml](backend/railway.worker.toml)), one with `WORKER_QUEUES=io` and one with `WORKER_QUEUES=cpu`.
- FFmpeg is installed at build time through [railpack.json](backend/railpack.json).
- The API and workers need the same environment variables as above. Services inside Railway should use Redis's internal URL.

## API overview

All routes except the Clerk webhook require a Clerk session token.

| Route | Purpose |
|---|---|
| `POST /auth/clerk-auth` | Clerk webhook, keeps the users table in sync |
| `POST /videos/init`, `/videos/{id}/parts`, `/videos/complete`, `/videos/{id}/abort` | Multipart upload lifecycle |
| `GET /videos/{id}/upload-status` | Resume an interrupted upload |
| `GET /videos/`, `GET /videos/search` | List and search your videos |
| `GET /videos/{id}/metadata`, `GET /videos/{id}/moments` | Processing status and detected moments |
| `DELETE /videos/{id}` | Delete a video and its files |
| `POST /clips/create`, `GET /clips`, `GET /clips/{id}` | Request, list and fetch rendered clips |
