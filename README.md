# Social Studio

Turn a product **image, video, or product-page URL** into platform-ready content for **Instagram, TikTok, or YouTube**, plus a caption package that follows each platform's rules. Next.js/React/TypeScript/Tailwind provide the UI; FastAPI, PostgreSQL, Celery, Redis, Ollama, Pillow, and FFmpeg handle generation.

**Implemented end to end:** input (upload or URL) → persisted job → background fetch/analysis/copy → real media rendered at the selected format's exact dimensions → preview/download and caption copy/download. The page restores its job from the URL after refresh.

| Platform | Format | Output | Dimensions |
| --- | --- | --- | --- |
| Instagram | Reel | H.264 MP4 | 1080 × 1920 (9:16) |
| Instagram | Feed post | JPEG | 1080 × 1350 (4:5) |
| Instagram | Square post | JPEG | 1080 × 1080 (1:1) |
| TikTok | Video | H.264 MP4 | 1080 × 1920 (9:16) |
| YouTube | Short | H.264 MP4 | 1080 × 1920 (9:16) |
| YouTube | Video | H.264 MP4 | 1920 × 1080 (16:9) |
| YouTube | Thumbnail | JPEG | 1280 × 720 (16:9) |

| Input | What happens |
| --- | --- |
| Image (JPEG/PNG/WebP) | Validated, metadata stripped, normalized. Video formats get a promo video: photo-tinted backdrop, the product in a shadowed card, close-up detail shots with eased zoom/pan, animated captions, cross-fades, and an end card with a CTA button. Optional background music is trimmed or padded to length, loudness-normalized, and faded; otherwise silent. Image formats get a poster in the same design. |
| Video (MP4/MOV/WebM, ≤ 180 s) | ffprobe-validated. Four frames sampled across the clip (10/37/63/90 %) form a numbered 2×2 storyboard that the vision model analyzes in time order; audio is not analyzed. Video formats **reframe your clip** onto the target aspect over a blurred fill, trimmed to 30 s, with hook/CTA/brand overlays and original audio kept. Image formats use the keyframe. |
| Product URL | Fetched by the worker with SSRF protection. The page's `og:image`/`twitter:image` becomes the product image; title/description feed the copy as untrusted data. Direct image URLs also work. |

The platform registry (`backend/app/core/platforms.py`) is the single source of truth for dimensions, output kind, caption length, and hashtag limits (for example, YouTube ≤ 3 hashtags plus a title; TikTok ≤ 5). Rendered output is verified against it before publication.

**Two explicit modes:** `GENERATION_MODE=ollama` uses local vision/text inference. `GENERATION_MODE=demo` uses deterministic generic copy and no AI analysis. Both render real media from the user's image, video, or product-page image. The UI and result metadata label demo mode. Ollama does not synthesize video; Pillow composes every frame from the user's media and FFmpeg encodes it.

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

Open http://localhost:3000. Choose **Image**, **Video**, or **Product URL**. Upload [the synthetic sample image](assets/sample-product.png), your own media, or paste a public product page. Pick a platform and format, then generate. Template videos from stills run about 9–14 seconds (a 2-second hook card, then 3–4 scenes); reframed source videos keep their length up to 30 seconds. Ctrl-C stops the launched API, worker, and frontend. Runtime data and logs are kept in gitignored `storage/demo/`.

This alternate development configuration uses **SQLite and Celery's filesystem broker**, with a separate solo worker. It supports one local worker and is not the production topology. It avoids requiring Docker merely to try the product. PostgreSQL/Redis remain the default configuration.

## Local live AI

With the configured vision model installed, select Node 22 and run:

```sh
./scripts/dev-local.sh
```

This uses the same separate-process local workflow with real Ollama analysis/copy. `dev-demo.sh` explicitly forces demo mode. Optional API/UI port overrides are `DEMO_API_PORT` and `DEMO_UI_PORT`; `RUNTIME_DIR` isolates the database, media, and filesystem queue (use it when another launcher is already running — workers sharing one queue directory will consume each other's jobs); the browser always uses same-origin `/api` requests. Both scripts preserve jobs under `storage/<mode>/` and never switch inference mode silently.

The provider limits context to 4096 tokens and unloads idle models after 60 seconds by default to reduce memory pressure on a 16 GB Mac. Tune `OLLAMA_NUM_CTX` / `OLLAMA_KEEP_ALIVE` through environment settings.

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

The initial model is configurable through `OLLAMA_MODEL` and `OLLAMA_VISION_MODEL`. Live inference with `qwen3.5:4b` (vision) is verified on a 16 GB Mac (see implementation notes, Phases 9–10). Before image analysis the provider calls `/api/show` and requires the model to report `vision` capability. Configure a compatible installed model if necessary. No paid provider is required. The adapter uses Ollama `/api/chat` structured JSON output with bounded validation retries. Model reference: [official Qwen 3.5 4B page](https://ollama.com/library/qwen3.5:4b).

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

The backend reads root `.env` from either root or `backend/`. The frontend defaults to same-origin `/api` requests, proxied by Next.js to `API_PROXY_URL` (default `http://127.0.0.1:8000`). Put frontend overrides in `frontend/.env.local` or its launch environment; Next.js does not read the root `.env`. Set `NEXT_PUBLIC_API_URL` only when deliberately using a separate browser-facing API. Direct API requests use CORS restricted to `FRONTEND_ORIGIN`. API docs: http://localhost:8000/docs.

### Full local container configuration

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.app.yml up --build
```

The migration service must finish before API/worker startup. Host Ollama is accessed at `http://host.docker.internal:11434` on Docker Desktop. Ensure the host service permits that connection; it has not been tested here. To run explicit demo mode in containers, set `GENERATION_MODE=demo` in `.env` before startup. The container frontend proxies to `http://api:8000` by default. Proxy targets are build-time arguments for standalone production output; rebuild after changing them. Explicit `NEXT_PUBLIC_API_URL` overrides must be browser-reachable.

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
| `MAX_UPLOAD_SIZE_MB` | Image upload limit, default 15; request-size and decoded image limits also apply |
| `MAX_VIDEO_UPLOAD_SIZE_MB`, `MAX_SOURCE_VIDEO_SECONDS` | Video upload limits, default 100 MB / 180 s |
| `MAX_MUSIC_UPLOAD_SIZE_MB`, `MAX_MUSIC_SECONDS` | Optional background music (MP3/M4A/WAV) for video formats, default 20 MB / 600 s |
| `URL_FETCH_TIMEOUT_SECONDS`, `URL_MAX_REDIRECTS` | Product URL fetch bounds, default 10 s / 3 redirects |
| `FFMPEG_TIMEOUT_SECONDS` | Per subprocess timeout, default 180 |
| `STALE_JOB_SECONDS` | Abandoned job expiry, default 900 |
| `REQUESTS_PER_MINUTE` | Per-process/client-IP generation request limit, default 10 |
| `FONT_PATH`, `FONT_BOLD_PATH` | Optional TrueType fonts (body, headlines) for other scripts or branding; Docker bundles DejaVu Sans and Sans Bold |
| `COOKIE_SECURE` | Mark the job-owner cookie `Secure`; set `true` whenever served over HTTPS (the public Compose override does) |

`CELERY_RESULT_BACKEND` is reserved; task results are deliberately disabled. PostgreSQL job records are the source of truth. AI generation settings are externalized as `OLLAMA_TEMPERATURE` (default 0.2) and `OLLAMA_NUM_PREDICT` (default 2200).

## API

All routes use `/api/v1`:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | API liveness |
| GET | `/ready` | Database migration, broker, model presence, and media tool checks |
| GET | `/config/platforms` | Supported format, explicit inference mode, upload limit |
| POST | `/generations` | Multipart `input_type` (`image`/`video`/`url`), `file` or `source_url`, `platform`, `format`, optional brand context, optional `music` (video formats only); 202 |
| GET | `/generations/{id}` | Persisted state, generated copy, safe errors |
| POST | `/generations/{id}/retry` | Retry a failed job; 202 |
| GET | `/generations/{id}/content` | Completed analysis, caption package, platform post text, scraped page metadata |
| GET | `/generations/{id}/preview` | Inline MP4 (range support) or JPEG |
| GET | `/generations/{id}/download` | MP4 or JPEG attachment named `{platform}-{format}-{id}` |
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

An opt-in real model check is available after installing the vision model:

```sh
cd backend
.venv/bin/python -m scripts.check_ollama --output ../storage/ollama-check.json
```

GitHub Actions configuration runs backend/render tests and frontend tests/builds on pushes and pull requests. A remote CI run is not claimed until an actual repository run succeeds.

## Security and operating limits

Uploads are limited by bytes, MIME, extension, decoded content, frame count, and pixel count. Images are normalized with metadata stripped and stored outside the frontend under UUID directories. Downloads validate the requested job and its asset directory. FFmpeg uses argument arrays, fixed generated paths, timeouts, and bounded threads. Output must pass dimensions/codec/duration checks and a full decode before completion.

**Results are private to the browser that created them.** Creating a job sets a random `HttpOnly`, `SameSite=Lax` owner cookie (30 days); the job stores only its SHA-256 hash. Status, content, preview, download, thumbnail, and retry all require the matching cookie; anyone else, including someone holding the job link, gets the same 404 as for a missing job, so existence is not revealed. This is per-browser ownership, **not user accounts**: clearing cookies or switching browsers loses access, and jobs created before migration `0005` are no longer served. A real public deployment still needs HTTPS (`COOKIE_SECURE=true`), an ingress body limit, shared rate limits/quotas, reviewer access or accounts, storage retention, and monitoring. Current rate limiting is per process and does not trust forwarded IP headers; configure ingress handling deliberately. Product URL fetching is an SSRF surface and is hardened: only http/https on default ports, no embedded credentials, `localhost`/`.internal` names refused, every DNS answer must be globally routable (loopback, RFC 1918, link-local/cloud metadata, CGNAT, multicast, IPv4-mapped forms all rejected), the connection is pinned to the validated IP with Host/SNI preserved (no DNS rebinding window), redirects are followed manually and re-validated, bodies are size-capped and time-limited, and proxies from the environment are ignored. The API rejects obviously unsafe URLs at submission; the worker re-validates every hop. Uploaded videos are probed and re-encoded by FFmpeg with timeouts and thread limits; a hostile-media deployment should additionally sandbox the worker.

## Status and delivery

See [implementation notes](docs/implementation-notes.md), [architecture](docs/architecture.md), [demo script](docs/demo-script.md), and [deployment notes](docs/deployment.md). Demo and live Ollama flows are verified for all three input types (live browser suite: image, video, and URL across Instagram, TikTok, and YouTube formats). A captioned walkthrough of the live app is recorded to `delivery/walkthrough.mp4` (gitignored; shared separately). Redis/Compose and a public URL remain pending. For how the build maps to the assessment brief and why it is built this way, see [submission notes](docs/submission.md).
