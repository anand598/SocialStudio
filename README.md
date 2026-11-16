# Social Studio

Turn a product image into a silent Instagram Reel and a caption package. Next.js/React/TypeScript/Tailwind provide the UI; FastAPI, PostgreSQL, Celery, Redis, Ollama, Pillow, and FFmpeg handle generation.

**Implemented:** image upload → persisted job → background analysis/copy → real 1080 × 1920 H.264 MP4 → preview/download and caption copy/download. The page restores its job from the URL after refresh.

**Two explicit modes:** `GENERATION_MODE=ollama` uses local vision/text inference. `GENERATION_MODE=demo` uses deterministic generic copy and no AI analysis. Both render real media from the uploaded image. The UI and result metadata label demo mode. Ollama does not synthesize video; Pillow/FFmpeg render a template with subtle zoom and fades.

## Quick local demo — no Docker or model download

Prerequisites: Python 3.12, Node **22.13+** (tested 22.23.2), FFmpeg/ffprobe. For macOS, install prerequisites from their official distributions or Homebrew (`brew install python@3.12 ffmpeg`). If using nvm, `cd frontend && nvm install && nvm use` selects the checked-in version.

```sh
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
cd frontend
npm ci
cd ..
./scripts/dev-demo.sh
```

Open http://localhost:3000. Upload [the synthetic sample image](assets/sample-product.png) or your own JPEG/PNG/WebP. Select Instagram/Reel and generate. Default demo video duration is nine seconds. Ctrl-C stops the launched API, worker, and frontend. Runtime data and logs are kept in gitignored `storage/demo/`.

This alternate development configuration uses **SQLite and Celery's filesystem broker**, with a separate solo worker. It supports one local worker and is not the production topology. It avoids requiring Docker merely to try the product. PostgreSQL/Redis remain the default configuration.

## Default stack — PostgreSQL, Redis, host Ollama

Install Docker Desktop/Compose and Ollama in addition to the prerequisites above. On macOS, start Docker Desktop before Compose. Copy the example configuration only if no `.env` exists:

```sh
cp -n .env.example .env
docker compose -f infrastructure/docker-compose.yml up -d --wait
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
```

Start Ollama (`ollama serve`, or its desktop app), then pull/check the model:

```sh
ollama pull qwen3.5:4b
ollama show qwen3.5:4b
```

The initial model is configurable through `OLLAMA_MODEL` and `OLLAMA_VISION_MODEL`. Its availability and image support have **not been verified on this machine**. Before image analysis the provider calls `/api/show` and requires the model to report `vision` capability. Configure a compatible installed model if necessary. No paid provider is required. The adapter uses Ollama `/api/chat` structured JSON output with bounded validation retries.

Run the following in separate terminals:

```sh
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```sh
cd backend
.venv/bin/celery -A app.workers.celery_app:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO
```

```sh
cd backend
.venv/bin/celery -A app.workers.celery_app:celery_app beat --schedule=../storage/celerybeat-schedule --loglevel=INFO
```

Create `storage/` first with `mkdir -p storage` from the repository root if running beat. Use one beat scheduler. macOS development uses a solo worker; Linux containers use the normal prefork worker, which also enforces Celery process time limits. HTTP and FFmpeg subprocess timeouts apply in both.

```sh
cd frontend
nvm use
npm ci
npm run dev
```

The backend reads root `.env` from either root or `backend/`. The frontend reads `NEXT_PUBLIC_API_URL`; put overrides in `frontend/.env.local` or its launch environment, since Next.js does not read the root `.env`. Default API is http://localhost:8000; CORS allows only `FRONTEND_ORIGIN`. API docs: http://localhost:8000/docs.

### Full local container configuration

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.app.yml up --build
```

The migration service must finish before API/worker startup. Host Ollama is accessed at `http://host.docker.internal:11434` on Docker Desktop. Ensure the host service permits that connection; it has not been tested here. To run explicit demo mode in containers, set `GENERATION_MODE=demo` in `.env` before startup. Containerized frontend API URLs are build-time arguments and must be reachable by the browser.

Containers run application code as non-root users. Database, Redis, and app ports bind to loopback for local use. The Docker configuration is supplied but **not build/run verified**, because Docker is missing in the current environment.

## Configuration

See [.env.example](.env.example). Defaults are development-only, including the PostgreSQL password. Change credentials before deployment. Important settings:

| Variable | Purpose |
| --- | --- |
| `GENERATION_MODE` | `ollama` (default) or explicit `demo` |
| `DATABASE_URL` | PostgreSQL by default; SQLite for isolated local demo |
| `CELERY_BROKER_URL` | Redis by default; `filesystem://` only for offline development |
| `LOCAL_STORAGE_PATH` | Shared API/worker filesystem; use an absolute path outside the demo helper |
| `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL` | Text and image analysis models |
| `OLLAMA_TIMEOUT_SECONDS` | Per AI request timeout, default 120 |
| `MAX_UPLOAD_SIZE_MB` | Default 15; request-size and decoded image limits also apply |
| `FFMPEG_TIMEOUT_SECONDS` | Per subprocess timeout, default 180 |
| `STALE_JOB_SECONDS` | Abandoned job expiry, default 900 |
| `REQUESTS_PER_MINUTE` | Per-process/client-IP generation request limit, default 10 |
| `FONT_PATH` | Optional TrueType font; Docker bundles DejaVu Sans |

`CELERY_RESULT_BACKEND` is reserved; task results are deliberately disabled. PostgreSQL job records are the source of truth. AI generation settings are externalized as `OLLAMA_TEMPERATURE` (default 0.2) and `OLLAMA_NUM_PREDICT` (default 2200).

## API

All routes use `/api/v1`:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | API liveness |
| GET | `/ready` | Database migration, broker, model presence, and media tool checks |
| GET | `/config/platforms` | Supported format, explicit inference mode, upload limit |
| POST | `/generations` | Multipart `file`, `platform=instagram`, `format=reel`, optional brand context; 202 |
| GET | `/generations/{id}` | Persisted state, generated copy, safe errors |
| POST | `/generations/{id}/retry` | Retry a failed job; 202 |
| GET | `/generations/{id}/content` | Completed analysis/caption package |
| GET | `/generations/{id}/preview` | Inline MP4 with range support |
| GET | `/generations/{id}/download` | MP4 attachment |
| GET | `/generations/{id}/thumbnail` | JPEG thumbnail |

Readiness does not guarantee a worker is running or that AI inference will succeed. In demo/filesystem mode, unnecessary dependencies are explicitly reported as not required. Generation errors use safe messages without provider details or storage paths.

## Validation

```sh
cd backend
.venv/bin/python -m pytest -q
.venv/bin/alembic upgrade head --sql
```

Tests include real FFmpeg rendering and full decode, uploads, failures, retries, expiry, duplicate execution, and Ollama schema mocks. FFmpeg must be installed. Tests use isolated SQLite schemas; production schema management uses Alembic.

```sh
cd frontend
nvm use
npm test
npm run typecheck
npm run build
```

With API and a **separate worker** running, run from the repository root:

```sh
backend/.venv/bin/python backend/scripts/smoke_test.py
```

Pass `--api http://localhost:PORT` for a custom API address. This uploads a synthetic sample, polls the real queue-driven job, and verifies media/caption downloads.

## Security and operating limits

Uploads are limited by bytes, MIME, extension, decoded content, frame count, and pixel count. Images are normalized with metadata stripped and stored outside the frontend under UUID directories. Downloads validate the requested job and its asset directory. FFmpeg uses argument arrays, fixed generated paths, timeouts, and bounded threads. Output must pass dimensions/codec/duration checks and a full decode before completion.

This MVP uses unguessable UUID URLs as result capabilities, **not user authentication**. Anyone with a job URL can access its result. Do not use sensitive product media in a public assessment deployment. A real public deployment needs HTTPS, an ingress body limit, shared rate limits/quotas, authentication or explicit reviewer access, storage retention, and monitoring. Current rate limiting is per process and does not trust forwarded IP headers; configure ingress handling deliberately. No URL fetching is implemented, so there is no SSRF input path.

## Status and delivery

See [implementation notes](docs/implementation-notes.md), [architecture](docs/architecture.md), [demo script](docs/demo-script.md), and [deployment notes](docs/deployment.md). Local demo smoke flow is verified; live Ollama inference, Redis/Compose, a public URL, and the recorded walkthrough remain pending. Only image → Instagram Reel is supported.
