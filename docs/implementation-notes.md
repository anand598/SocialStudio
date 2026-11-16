# Implementation log

## Phase 0 — inspected 2026-11-16

The workspace initially contained only the handover Markdown. No starter source or Git repository existed. The assessment PDF was subsequently reviewed and confirmed that one complete input/output workflow is sufficient and an explicitly simulated generation path is allowed.

Python 3.12, FFmpeg, Ollama client, and multiple Node versions are installed. Docker and Redis server are unavailable. Native PostgreSQL 18.3 was discovered later and used in an isolated test cluster. Ollama is not serving; the configured qwen3.5:4b model is not installed. A separate gemma3:12b installation exists but was not loaded or used for inference.

## Phase 1 — foundation

Implemented Next.js App Router/React/TypeScript/Tailwind, FastAPI configuration and JSON request logging, typed liveness/readiness, PostgreSQL/Redis Compose, SQLAlchemy job model, and explicit Alembic migrations. The frontend initially used Node 20.10; updated Tailwind tooling required modern ESM interop, so the project now targets Node 22.13+ with 22.23.2 pinned in `.nvmrc`.

Backend dependencies are frozen; frontend dependencies have a public-registry lockfile. A patched PostCSS override resolved dependency advisories; the latest installation audit reports zero vulnerabilities. No private registry tokens or secrets are tracked.

## Phase 2 — upload and persistence

Implemented multipart upload, MIME/extension/content agreement, file-size limits, streamed request limits, decoded image/pixel/frame checks, metadata-stripping normalization, UUID storage paths, optional brand context, and persisted job/status APIs. Unsupported platforms/formats are rejected. Configuration comes from a typed backend format registry. Only Instagram Reel is enabled.

Accepted input is stored as a normalized JPEG preserving visible content, rather than retaining original metadata or potentially malicious trailing payloads. Tests cover valid/invalid input, unsupported formats, oversized request streams, and per-process request throttling.

## Phase 3 — AI adapter

Implemented a provider interface, Ollama image capability check, structured product analysis/copy/storyboard schemas, configurable models/timeouts/temperature/token budget, constrained prompts, and bounded malformed-response retries. Live inference is **not verified**. Mocked Ollama tests verify schema handling and missing vision capability. Explicit demo mode supplies generic deterministic copy and no product analysis or invented benefits. Mode is persisted and displayed in UI/results. There is no silent fallback.

## Phase 4 — asynchronous lifecycle

Celery runs long work in a separate process. Database records track queue, stage, errors, and results. Atomic task claims, per-attempt leases, attempt-specific artifacts, bounded transient AI retries, safe failure messages, and manual retries handle duplicate delivery/failures. Beat and status retrieval expire abandoned jobs; the user can retry rather than waiting permanently.

PostgreSQL/Redis are defaults. An alternate one-worker local demo uses SQLite and Celery filesystem transport because Docker/Redis are unavailable here. The one-command launcher explicitly selects demo mode, creates an Alembic-managed database, starts separate API/worker/frontend processes, records logs, and stops its owned processes on Ctrl-C. This fallback topology is for development only.

## Phase 5 — real media rendering

Pillow fits the product image without distortion and draws branded scenes with wrapped copy. FFmpeg applies subtle zoom/fades and creates silent H.264/yuv420p MP4. ffprobe verifies 1080 × 1920, duration, codec, pixel format, and container. Every frame is decoded before output is atomically published. A JPEG thumbnail is generated. Temporary scene data is cleaned up; runtime media remains gitignored.

The UI provides drag/drop and browse, brand/CTA inputs, supported format selection, stage display, errors/retry, video controls, download, caption copy/text download, and refresh restoration through a job URL. No exact percentage is displayed as measured progress. A rendered sample thumbnail was visually inspected for layout.

## Phase 6 — verification and hardening

- **19 backend tests pass**, including a real render/full decode, download/package retrieval, idempotency, expired-attempt protection, safe worker/queue failures, manual retry, expiry, upload security, readiness, and mocked AI responses.
- **5 frontend component tests pass**, including upload validation, queued → rendering → completed polling, completed preview/download/caption after refresh, and failed-job controls.
- TypeScript check and Next.js production build pass on Node 22.23.2.
- All migrations applied to an isolated native PostgreSQL 18.3 cluster; `alembic check` reports no schema drift. SQLite migrations were also applied in the launcher/smoke workflow. The PostgreSQL cluster was stopped after testing.
- A real API + separate Celery filesystem worker smoke test uploaded the synthetic image, persisted stage changes, completed rendering, and downloaded a 270,140-byte MP4 and caption package. The same flow passed through `scripts/dev-demo.sh` on isolated test ports. Frontend returned HTTP 200. Temporary test services were stopped.
- Full native browser interaction/visual responsive QA remains unverified: no automation-enabled browser was available, and native Chrome actions were interrupted by concurrent activity. Component tests are not a substitute for browser playback/clipboard/responsive verification.
- Backend tests have one upstream Starlette httpx test-client deprecation warning; no test failures.

## Phase 7 — delivery status

README, architecture, deployment preparation, and a four-minute walkthrough script are supplied. Non-root backend/frontend Dockerfiles and a full Compose override are prepared. Docker images/Compose, Redis integration, host/container Ollama access, and live model inference remain **unverified**. No public URL or recorded walkthrough exists yet. Hosting target, access/account, and authorized budget are required before public deployment. A local Git repository has been initialized for the implementation; no remote repository has been created or pushed.

## Known limitations and next improvements

1. Add reviewer authentication or explicit access control, HTTPS/ingress size limits, shared quotas, storage retention, and monitoring before public/private product use. Current random UUID URLs act as bearer capabilities, and rate limiting is process-local.
2. Verify real Ollama inference using a vision model that fits the host memory budget. Keep demo labeling if live inference is not available.
3. Build/run the Docker PostgreSQL/Redis topology and validate in a clean browser before claiming production readiness.
4. Add a transactional outbox for atomic database-to-broker delivery; current publish failure plus expiry is recoverable but not an exactly-once delivery guarantee.
5. Local media needs shared storage on one host. Add S3-compatible storage/signed URLs before multi-host scaling. Failed/retried artifacts currently have no automatic retention cleanup.
6. Review AI claims manually; schema validation and prompts cannot guarantee factual accuracy. Non-Latin font coverage depends on the configured font. No copyright music is bundled.
7. Only still image → Instagram Reel is implemented. Source video, URL input, history UI, more formats, and generative image/video synthesis are pending. Existing jobs remain accessible through their saved URL, not an account history.
