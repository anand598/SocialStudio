# Social Studio — submission summary

Social Studio turns a product **image, video, or product-page link** into ready-to-post content for **Instagram, TikTok, and YouTube**: a video or image at the platform's exact size, plus the caption, hashtags, and (for YouTube) title.

| Deliverable | Where |
| --- | --- |
| Live application | **`<LIVE_URL>`** |
| Demo video (2 min 12 s, captioned, silent) | **`<VIDEO_LINK>`** (`delivery/walkthrough.mp4`) |
| Source code | This repository; one commit per feature |
| README: setup, architecture, technology choices, assumptions, limitations | [README](../README.md), [architecture](architecture.md), [deployment](deployment.md) |
| Implementation notes: real vs simulated, known issues, trade-offs, next steps | This page; the phase-by-phase log is in [implementation notes](implementation-notes.md) |

## What a user can do

1. Upload a product **image** or **video**, or paste a **product page or image URL**.
2. Choose **Instagram, TikTok, or YouTube**, then a format valid for that platform.
3. Optionally add a brand name, product context, a call to action, a **brand colour**, a **logo**, and (for videos) **background music**.
4. Watch the job move through its stages, then **preview** the result, **download** it, and copy or download the caption package.
5. Make **another version** of a finished result, for any platform and format, from the same upload, with fresh copy.
6. Reopen earlier results from **Recent creatives**. Results are private to the browser that made them, and their media is deleted after a retention period.

| Platform | Format | Output | Size |
| --- | --- | --- | --- |
| Instagram | Reel / Feed post 4:5 / Square post 1:1 | MP4 / JPEG / JPEG | 1080×1920 / 1080×1350 / 1080×1080 |
| TikTok | Video | MP4 | 1080×1920 |
| YouTube | Short / Video / Thumbnail | MP4 / MP4 / JPEG | 1080×1920 / 1920×1080 / 1280×720 |

Each format also carries the platform's text rules, which are enforced on the post text: TikTok allows at most 5 hashtags; YouTube allows at most 3 plus a title of up to 100 characters; caption lengths are capped.

## The brief, point by point

| Brief | Status | Evidence |
| --- | --- | --- |
| Input: URL, image, or video | ✅ All three | Upload validation in [storage/local.py](../backend/app/services/storage/local.py); URL fetching in [ingest/url.py](../backend/app/services/ingest/url.py) |
| Choose a platform; an appropriate format for it | ✅ 3 platforms, 7 formats | One registry, [platforms.py](../backend/app/core/platforms.py), drives the UI, renderer, prompts, and validation |
| Generate a video or image at the platform's aspect ratio and dimensions | ✅ | [renderer.py](../backend/app/services/media/renderer.py), [promo.py](../backend/app/services/media/promo.py). Every video is ffprobe-checked and fully decoded before the job completes; every image is reopened and its size checked |
| Show generation status | ✅ | Each stage is saved in the database and polled by the UI; the job reopens from its link after a refresh |
| Preview and download | ✅ | Aspect-correct preview, file download, caption copy/download |
| At least one input and one format end to end | ✅ Exceeded | 3 inputs × 7 formats, verified in a real browser against live AI |
| Explain what is simulated | ✅ | Next section; demo mode is also labelled in the UI |

## Real vs simulated

| Part | Real or simulated |
| --- | --- |
| Uploads, URL fetching, job queue, status, storage, preview, download, retention | Real |
| Rendering every frame and image (Pillow + FFmpeg) at exact dimensions | Real in both modes |
| Product analysis and copywriting | **Real** in `ollama` mode (local `qwen3.5:4b` vision model). **Simulated** in `demo` mode: deterministic template copy, no analysis. The UI shows a banner in demo mode, and every job records its mode |
| Generative image or video synthesis (text-to-video, AI image editing) | **Not used**, by choice: outputs are built from the user's own media (see trade-offs) |

The app never silently falls back to demo copy. The live instance runs in **`<MODE>`** mode. The demo video shows live AI.

## How it works

```
Browser (Next.js) ──/api proxy──▶ FastAPI ──job id──▶ Celery worker ──▶ fetch URL (SSRF-safe)
                                     │                     │              analyse (vision model)
                                     ▼                     │              write copy (schema-checked JSON)
                               PostgreSQL job row ◀────────┘              render (Pillow/FFmpeg) → validate
                               (status, stage, results, errors)
Celery beat: expire stuck jobs every minute · purge expired media every hour
```

1. **API** ([generations.py](../backend/app/api/generations.py)) validates the input and format, stores the file, creates the job row, and queues only the job ID. It answers 202 at once.
2. **Worker** ([tasks.py](../backend/app/workers/tasks.py)) claims the job atomically, then runs and saves each stage, so progress is real and survives restarts.
3. **AI provider** ([provider.py](../backend/app/services/ai/provider.py)) asks the model for JSON matching a Pydantic schema, validates it, and retries bounded failures. A video is analysed as a storyboard of four frames from across the clip.
4. **Renderer** produces a designed poster (image formats), a promo video built from a still (blurred, colour-tinted backdrop, product card, close-up shots, animated captions, end card), or the uploaded clip reframed to the target aspect with overlays and its own audio. On 9:16 video, text stays clear of the areas the apps cover with their own controls.
5. **UI** ([page.tsx](../frontend/src/app/page.tsx)) polls the job and shows stages, the result, downloads, and safe errors with a retry option.

## Key decisions and trade-offs

- **Render from the user's media; use AI for understanding and copy.** Hosted text-to-video is slow, costly, and unreliable at showing the actual product. Rendering from the user's media keeps the product faithful and the output exactly platform-sized. The trade-off is a more template-like look than generative video.
- **Local AI (Ollama) instead of a paid API.** No keys, no spend, and product media never leaves the server. The trade-off is speed (about 20–60 s per job on a 16 GB Mac) and a host with enough memory; a labelled demo mode covers hosts without one.
- **One format registry.** Dimensions, output type, and text limits are data. Adding a format is one entry and a test.
- **Background jobs with the database as the source of truth.** Rendering takes seconds to minutes, so it runs outside the request. Celery carries only job IDs and needs no result backend.
- **Privacy without accounts.** A random `HttpOnly` cookie marks the creating browser, and jobs store only its hash. Anyone else, even with the link, gets the same 404 as for a missing job. A cookie is used because `<video>`, `<img>`, and download links cannot send custom headers. The trade-off: clearing cookies or switching browsers loses access.
- **Honest output.** Prompts forbid invented specifications, benefits, and prices; every result lists the facts to confirm before publishing; scraped page text is passed to the model as untrusted data, never as instructions.

## Asynchronous work and failure handling

- **No lost or doubled work:** an atomic claim plus a per-attempt token means duplicate deliveries do nothing and a stale worker cannot overwrite a newer attempt. Outputs are written under attempt-specific names and published atomically only after validation.
- **Guaranteed hand-off to the queue (transactional outbox):** a job and its queue message are saved in one transaction and published at once; if the broker is down, the job simply stays queued and a relay in the API publishes it when the broker returns, with backoff. Verified live: jobs created during a broker outage, and even across an API restart, were all delivered within seconds of the broker coming back. After one failed publish, requests stop waiting on the broker (about 6 s each) and answer in milliseconds.
- **Bounded retries:** AI network/server errors are retried at most twice; invalid model output gets one repair attempt; validation errors are not retried.
- **Stuck jobs:** jobs that stop updating expire after a timeout (scheduled task and on read) and can be retried by the user.
- **Safe errors:** users see stable codes and plain messages (for example `URL_BLOCKED` with a suggestion to upload instead); internals and stack traces never reach the client.
- **Concurrency:** new versions are numbered per family under a unique index, with collisions retried; retention claims a job with a conditional update before deleting its files, so a retry or new version can never start from media being removed.

## Persistence

PostgreSQL holds jobs, stages, results, and errors (SQLite only for the offline local demo). Media lives in per-job folders named by UUID. Eleven Alembic migrations, all run by the test suite on SQLite; migration 0009 was also run up and down on PostgreSQL during review. Media is deleted `MEDIA_RETENTION_DAYS` after a job finishes (default 30); the record and caption stay, media requests answer 410 Gone, and the UI shows an expired state. A sweep removes folders left by crashes.

## Security

- **Uploads:** checked by size, MIME type and extension together, decoded content, frame count, and pixel count; images are re-encoded with metadata stripped; logos keep transparency but are redrawn without metadata.
- **Product URLs (SSRF):** only http/https on default ports; every DNS answer must be public (loopback, private, link-local/cloud-metadata, CGNAT and mapped forms rejected); the connection is pinned to the validated IP with Host/SNI kept; redirects are re-validated; bodies are size- and time-limited.
- **Media processing:** FFmpeg runs with argument lists, fixed paths, timeouts, and thread limits.
- **Access and abuse:** owner cookie on every job endpoint; `Secure` behind HTTPS. Generation requests are limited per client per minute and per UTC day, counted in Redis so every API process shares the limit. The client address is taken from `X-Forwarded-For` only when the request comes from a trusted proxy (Caddy → Next.js → API), so users neither share one bucket nor spoof their way out of it.
- **Operations:** `/api/v1/ready` checks the database is at the latest migration, plus Redis, the model, and FFmpeg. (It used to compare with a hard-coded revision and reported every database since migration 0007 as not ready; found and fixed with a test against a real migrated database.)

## How it was built and verified

Built with AI coding assistants (Codex, then Claude Code), feature by feature, each change test-first, reviewed, and checked in a real browser. Later features were built by parallel agents against a fixed API contract and then reviewed by a separate agent that had not seen the implementation; those reviews found defects that were all fixed with regression tests and confirmed no data-loss or access-control issues.

- **225 backend tests:** real FFmpeg renders and full decodes, every format's dimensions, upload and URL attacks, AI schema handling, job lifecycle and races, the outbox and its relay, rate limits and proxies, access control, retention, and rendering rules (headline size, safe zones).
- **42 frontend tests**, typecheck, and production build. GitHub Actions runs the backend and frontend checks on every push, and the runs on `main` pass.
- **Live checks** in headless Chrome against live AI for every input type, new versions, retention, and privacy; product-URL extraction checked against real stores.

## Known issues and limitations

- Results belong to a browser, not a person; there are no user accounts.
- Live AI needs a host with enough memory for the model; on CPU a job takes up to a minute.
- Product pages that build their content in the browser fall back to their share tags; many large retailers block automated fetches (the user is asked to upload instead).
- Video understanding uses four frames and ignores speech.
- Media is on one host's disk; scaling to several hosts needs object storage.
- If Redis is unreachable, rate limits are not enforced (fail open, logged); ingress limits remain the outer guard.
- AI copy can still be wrong; users must review it (the app says so on every result).

## What I would do next, in order

1. **User accounts and saved brand kits.** This turns one-off results into a workspace and removes the per-browser limit. It is the biggest product gap.
2. **Object storage with signed URLs.** This allows more than one API/worker host and pushes downloads to a CDN.
3. **Quotas per account and plan**, building on the shared Redis limits, plus usage metering.
4. **Speech-to-text for video uploads** (Whisper), so the copy can use what is said in the clip.
5. **Product evolution:** scheduling and direct posting to the platforms' APIs, side-by-side comparison of versions, and usage analytics to learn which hooks perform.
