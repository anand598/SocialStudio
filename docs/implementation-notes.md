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

## Phase 8 — all inputs, platforms, and formats

The assessment lists URL, image, and video inputs and Instagram/TikTok/YouTube outputs; P0 covered one path. This phase extends the same pipeline rather than adding parallel ones.

- **Format registry:** Instagram Reel (9:16 MP4), Feed 4:5 and Square 1:1 (JPEG); TikTok Video (9:16 MP4); YouTube Short (9:16 MP4), Video (16:9 1080p MP4), Thumbnail (1280 × 720 JPEG). Each carries caption/hashtag limits, enforced when composing the downloadable post text (YouTube adds a title and keeps ≤ 3 hashtags).
- **Video input:** streamed to disk, ffprobe-validated (container, codec allow-list, ≤ 4096 px, 1–180 s), keyframe extracted for analysis. Video outputs reframe the real clip over a blurred fill with overlays and original audio; image outputs use the keyframe.
- **URL input:** API pre-check, then worker `fetching` stage with SSRF defences (public-IP-only DNS, connection pinned to the checked IP with Host/SNI preserved, manual re-validated redirects, size/time caps). Open Graph image/title/description are extracted; page text is passed to the model as untrusted data. Demo mode may quote the page title but never infers claims from it.
- **Renderer:** one layout engine for portrait, square, and landscape canvases; image outputs are verified by reopening the JPEG; video outputs keep the ffprobe + full-decode gate.
- **Migration 0004:** nullable `input_file_path` (URL jobs receive it after fetch), `source_media_path`, `source_url`, `source_metadata`. Applied, downgraded, and re-applied on SQLite; the PostgreSQL offline SQL was reviewed.
- **UI:** input-type tabs, platform → format selectors from the registry, a dimension/type summary, input-aware stage list, aspect-correct video or image preview, and platform-specific post text.

Verification: **62 backend tests** (new: registry dimensions/aspect ratios, post-text limits, every image format's JPEG size, still → 16:9 video, video upload validation and rejection, video → 9:16 and 16:9 with audio, video → image, SSRF shape/address/mixed-DNS/redirect rejection, Open Graph extraction with connection pinning, unusable pages, URL job end to end) and **8 frontend tests** pass; typecheck and production build pass. A live launcher run (API + separate filesystem-queue worker + Next.js proxy) completed image → Instagram 4:5 and Reel, video → YouTube Short and 16:9 (audio kept, source length kept), and a real public product URL → TikTok; a page without `og:image` failed with `URL_NO_IMAGE`; metadata-IP, loopback, and `file://` URLs were rejected at submission.

Operational finding: two launcher instances sharing `storage/demo/queue` consumed each other's jobs (an older worker rendered new jobs with old code). The launcher now accepts `RUNTIME_DIR` for isolation; production uses Redis with one deployed worker version.

## Phase 9 — live inference verified; multi-frame video analysis

Live Ollama inference was verified on this machine with `qwen3.5:4b` (reports `vision`): image analysis + copy for the sample took ~40 s and stayed factual (verbatim label text, no invented specs, explicit uncertainties). It exposed two defects, both fixed test-first: scene text came back as camera directions although it is rendered on screen (prompt and schema now require viewer-facing captions ≤ 10 words), and `product_name` arrived as the string "null" (placeholders now normalize to null).

Video analysis previously used one frame ~1 s in. Uploads now also produce a numbered 2×2 storyboard of frames at 10/37/63/90 % of the clip; the worker sends it to `analyze_product_video`, whose prompt explains the time order and asks the model to merge details across frames and describe how the product is shown over time. A single composite stays within the 4096-token context budget that suits a 16 GB machine, where four separate images might not. Storyboard failure is non-fatal (falls back to the keyframe). Live check on a four-shot clip: 24 s, details merged across shots, limitations stated. Field-length truncation from constrained decoding was fixed by asking for concise fields. Audio/speech is not analyzed.

## Phase 10 — live browser testing and a structured-output runaway

The app was driven in headless Chrome (system Chrome via playwright-core) against the live Ollama stack: landing, platform/format switching, image → Reel and 4:5, video → TikTok and YouTube 16:9, URL → YouTube thumbnail, refresh restore, client and server input errors, mobile layout, and failed requests.

The first run exposed intermittent AI failures: image analyses exceeding the 120 s timeout and a URL job failing with `AI_INVALID_CONTENT`. Sampling the same request showed ~31 % of analysis calls finishing with `done_reason=length` at the full 2,200-token budget although only ~520 characters were visible: constrained decoding looped on whitespace. Every runaway stopped right after `confidence_or_limitations`, the field the model treats as its conclusion, while a required list field still followed. Fixes, test-first: (1) the concluding field is now last in the schema (runaways fell to ~7 % in a 14-run sample); (2) per-schema token budgets (analysis 800, copy 1,500) make a residual runaway fail in seconds instead of ~60 s; (3) truncated output is retried up to three times; (4) validation failures are logged with field/type and truncation flag, never the generated text. The machine was also under heavy memory pressure (≈19 of 20 GB swap used), which magnified each runaway into a timeout.

Browser testing also found, and test-first fixes resolved: a missing favicon (404 on every load); `#job=` links only read on first load, so back/forward and pasted links on an open tab did not switch jobs (now follows `hashchange`, and a URL without a job returns to the empty studio); and post text repeating hashtags or the CTA that the model had also put inside the caption (now merged/deduplicated, and the prompt asks for a clean caption).

After the fixes the live browser suite passed: image → Reel 34 s and 4:5 18 s, video → TikTok 34 s and YouTube 16:9 29 s, URL → YouTube thumbnail 26 s (previously 75–309 s with two failures), plus 13/13 navigation, error-handling, mobile, and network checks. Totals: 71 backend and 10 frontend tests.

## Known limitations and next improvements

1. Results are now private to the creating browser (owner cookie). Before public use still add user accounts or reviewer access, HTTPS, shared quotas, and monitoring; rate limiting is process-local.
2. Live inference is verified locally with `qwen3.5:4b`; a hosted deployment still needs a model host with enough memory (or explicitly labeled demo mode).
3. Build/run the Docker PostgreSQL/Redis topology and validate in a clean browser before claiming production readiness.
4. Add a transactional outbox for atomic database-to-broker delivery; current publish failure plus expiry is recoverable but not an exactly-once delivery guarantee.
5. Local media needs shared storage on one host. Add S3-compatible storage/signed URLs before multi-host scaling. Media retention (Phase 17) deletes whole job folders; partial artifacts of retried runs live until then.
6. Review AI claims manually; schema validation and prompts cannot guarantee factual accuracy. Non-Latin font coverage depends on the configured font. No copyright music is bundled.
7. Saved (reusable) brand kits, side-by-side comparison of versions, and generative image/video synthesis are pending. History is per browser (owner cookie), not per account.
8. URL ingestion reads Product JSON-LD and Open Graph/Twitter tags from the server's HTML; pages that build their product data in the browser fall back to their tags, and headless rendering is not implemented. Many large retailers block automated fetches (reported as `URL_BLOCKED` with an upload suggestion).
9. Video understanding samples four frames and ignores audio; long clips with many products or spoken claims need denser sampling and speech-to-text (e.g. Whisper) before copywriting.
10. Source video is re-encoded by FFmpeg on the worker. Production handling of hostile media should add sandboxing (seccomp/gVisor or an isolated transcoding service) and a per-job CPU budget.

## Local connection fix — 2026-11-16

The browser-facing UI now uses same-origin `/api` URLs, with Next.js proxying to the configured backend. The demo launcher sets the proxy to its chosen API port; Docker builds target the `api` service. This removes separate browser-port/CORS dependencies for the normal workflow. Five frontend tests, TypeScript, and the production build pass. A full separate-worker smoke test through `http://localhost:3000` verified configuration, multipart upload, status polling, MP4 download, and caption retrieval.

## Large uploads through the UI proxy — 2026-11-17

A 34 MB video uploaded through the UI returned HTTP 500 while the same file posted directly to the API was accepted. Next.js truncates bodies proxied through its `/api` rewrite at 10 MB by default (`middlewareClientMaxBodySize`), so every video over 10 MB, and images between 10 and 15 MB, failed in the browser. Earlier browser tests used a small clip, which hid this. `next.config.mjs` now allows 110 MB (the 100 MB video limit plus multipart overhead; the API still enforces per-type limits), a frontend test ties the setting to the backend limit, and the prepared Caddy ingress limit was raised from 16 MB to match. Verified: the same 34 MB upload through `http://localhost:3000` is accepted and processed.

## Phase 11 — private results, output polish, recorded walkthrough — 2026-11-17

**Access control.** Job links used to act as the only access key. Creating a job now sets a random `HttpOnly`, `SameSite=Lax` owner cookie; the job stores its SHA-256 hash (migration `0005`). Status, content, preview, download, thumbnail, and retry compare it in constant time and otherwise return the same 404 as a missing job. A cookie was chosen over a header because media elements and download links cannot send headers. `COOKIE_SECURE` marks it Secure behind HTTPS (set in the public override); CORS allows credentials for a separately hosted API. In the UI, a link opened in another browser stops polling and explains that results open only where they were created. Tests: 6 backend, 1 frontend. Verified live through the Next.js proxy: the owner gets 200 and a cookie-less request gets 404.

**Output review.** Rendered frames from every path were reviewed and fixed test-first:
- Template videos never showed the AI's hook. They now open with a 2-second hook card. It is skipped when the first scene overlaps it: live output once split the hook "Not for sale. Just for show." across the first two scenes, so the card repeated them.
- Headlines, overlays, and CTAs were thin and small. They now use bold faces (DejaVu Sans Bold in Docker, Arial Bold on macOS, `FONT_BOLD_PATH` to override) at larger sizes. The YouTube thumbnail headline grew from 54 px to up to 94 px, since thumbnails are judged at about 300 px wide.
- On 9:16 video, the CTA sat inside the bottom area that TikTok, Reels, and Shorts cover with captions and buttons. Overlays and template text now stay between 10% and 80% of the height.

**Walkthrough.** A captioned walkthrough of the live app (image → Reel, video → TikTok, URL → YouTube thumbnail, refresh restore, unsafe-input rejection, access control) was recorded in headless Chrome via the DevTools screencast, with real-time waits, and encoded with FFmpeg to `delivery/walkthrough.mp4` (gitignored; share it separately).

- Reported from Safari: a finished Reel showed an almost-black frame. Every template scene faded out, including the last one, so the ended player rested on black (the first frame was also black, hidden only by the thumbnail poster). Scenes now dip to black only between scenes; the video opens and ends on a full frame.

Totals: 89 backend and 12 frontend tests.

## Phase 12 — promo-style video from a still — 2026-11-17

Feedback: the still → video output did not look like a promotion video and its background looked poor. The flat dark-green template, the beige mat around the photo (worst with landscape photos), a single static framing, captions baked into the frame, and dips to black all read as a slideshow.

`app/services/media/promo.py` replaces the template, test-first (`tests/test_promo.py`):
- **Backdrop from the product:** the photo is cover-scaled, heavily blurred, and tinted dark with its dominant colour. The accent colour (caption bar, CTA button) is a light tint of the same hue; grey products fall back to the studio palette.
- **Card without a mat:** the photo keeps its own aspect ratio, with rounded corners and a soft shadow. On 9:16 canvases very wide photos are trimmed to 1.3:1 so the card fills the frame.
- **Shot plan:** whole product (slow push-in), then close-up detail shots that push in, pan, or pull back, then the whole product again on an end card. Zoom is limited by the source resolution, and each shot gets its own pre-scaled source so sampling stays near 1:1 without shimmer.
- **Motion and type:** an accent bar grows and each caption slides up as the scene starts. Scenes cross-fade over 0.4 s. On the end card a CTA button pops in, and if the last caption only repeated the CTA, the opening line returns as the headline.
- **Rendering:** frames are composed in Pillow with sub-pixel sampling, because FFmpeg zoompan jitters on slow moves, and streamed to FFmpeg as raw video under the existing timeout. A 13 s 1080×1920 promo renders in about 10 s.
- **Posters** (feed, square, thumbnail) use the same backdrop, card, and type.

Verified live: picsum laptop URL → Instagram Reel in 54 s end to end (1080×1920, 10 s). Totals: 99 backend tests. No music is bundled because of licensing; see Phase 13 for user-supplied music.

## Phase 13 — optional background music — 2026-11-17

Video formats accept an optional music upload (`music` form field; MP3, M4A, or WAV; 20 MB / 10 minutes by default). It is refused for image formats. The API checks that MIME type and extension agree before storing anything, streams the file into the job folder under a byte cap, and validates it with ffprobe (audio stream, container and codec allow-lists, duration). Any failure removes the whole job folder. The request-size bound now allows the largest product file plus a track. Migration `0006` adds `music_path`; responses expose `has_music`.

Rendering: for image → promo video, the track is loudness-normalized (−16 LUFS), faded in over 0.6 s and out over 1.5 s, and padded with silence or trimmed so it lasts exactly as long as the video. For video input, the music is normalized lower (−20 LUFS, then −9 dB) and mixed under the clip's own sound; if the clip is silent it plays alone. Music never makes a video longer. The UI shows the field only for video formats, with a reminder to use music the user has the rights to.

Tests: 9 backend (formats, rejection and cleanup, full-length padded audio that fades in, mixing under source audio, config limits) and 2 frontend. Verified live: picsum laptop URL plus a synthetic music track → Reel with a 13 s video and a 13 s AAC track (mean −18 dB) in 53 s. Totals: 108 backend and 14 frontend tests.

## Phase 14 — recent creatives (job history) — 2026-11-18

Before this, a past result could be reopened only from its saved `#job=` link. `GET /api/v1/generations` now lists the calling browser's own jobs, newest first (default 20, at most 50), using the existing owner cookie: no cookie returns an empty list and sets none, and other browsers' jobs never appear. Rows are deliberately light (status, platform, format, output kind, and a headline taken from the completed copy's title or hook) and omit analysis, captions, and file paths, so the full result still goes through the per-job, access-checked endpoints. Migration `0007` indexes `(owner_hash, created_at)` for this query.

The UI shows a "Recent creatives" strip under the workspace: thumbnails for finished results, status for running or failed ones, and the open result outlined. Each card is a plain `#job=` link, so it reuses the existing hash-restore and polling path rather than a second loading mechanism. The list refreshes when the open job is created or changes state. History is non-critical: if it is empty or fails to load, the section is hidden and creation is unaffected. The API helpers moved from `page.tsx` to `src/lib/api.ts` so the component shares them.

Tests: 6 backend (ordering, isolation between browsers, no-cookie behaviour, limit bounds, headline, omitted fields) and 6 frontend (component behaviour plus opening a past result from the page). Verified live in demo mode through the Next.js proxy with headless Chrome at 1280 px and 390 px. Totals: 115 backend and 20 frontend tests.

## Phase 15 — brand colour and logo — 2026-11-18

The form gained two optional "Make it yours" fields that apply to every input and format.

**Brand colour.** `brand_color` must be `#RRGGBB` (validated by the API, stored upper-case in `brand_context`). The renderer uses the exact colour for the CTA button and accent bar and a dark shade of its hue for the backdrop tint, replacing the photo-derived palette. Text on the button is white or dark ink, whichever has the higher WCAG contrast; if the colour reads poorly on the dark backdrop (contrast below 3:1, e.g. navy), the brand name and accent bar fall back to white. Reframed source videos use the colour for their CTA box.

**Logo.** An optional PNG/JPEG/WebP upload (2 MB by default, `MAX_LOGO_UPLOAD_SIZE_MB`). The API checks MIME/extension agreement before storing anything, then decodes it with the same hardened path as product images (format allow-list, single frame, decompression-bomb guard, EXIF orientation) but keeps transparency. It is trimmed to its visible pixels, capped at 800 px, re-drawn onto a fresh image (no metadata or embedded payloads), and saved as `logo.png` in the job directory (migration `0008` adds `logo_path`; responses expose `has_logo`). Fully transparent or tiny logos are refused, and any failure removes the job directory. The logo takes the brand name's position at a fixed cap height (7 % of the short side, at most 40 % of the width) on posters, promo videos, and reframed videos; on 9:16 it stays below the top app UI.

Why replace the brand name rather than show both: the top-left slot is sized for one mark, and logos usually contain the name already.

Tests: 14 backend (validation and normalisation, transparency kept and trimmed, rejection and cleanup, contrast choice, button colour, backdrop hue, readable dark brands, logo placement and aspect, video overlays, and two end-to-end worker runs: poster and reframed TikTok) and 3 frontend (sent when chosen, validated before upload, not sent when absent or removed). Verified live in demo mode: an orange brand colour and a transparent logo on an Instagram square post and a Reel, plus the form at 1280 px and 390 px. A generic `input` rule had stretched the colour picker to full width; it now excludes colour inputs. Totals: 129 backend and 23 frontend tests.

## Phase 16 — another version from the same upload — 2026-11-19

A finished result offers "Make another version": pick any platform and format (default: the current one) and get a new job built from the same stored inputs, so one upload can be repurposed for Instagram, TikTok, and YouTube without uploading again. Built with two agents in parallel against a fixed API contract (backend and frontend in separate directories), then integrated, checked live, and reviewed independently.

**API.** `POST /api/v1/generations/{id}/variants` (JSON `{platform, format}`, both or neither) uses the same owner check and 404 as every job endpoint, and is rate-limited by the existing generation middleware. The source must be completed (409), the format supported (422). The new job copies the source's input type, URL, page metadata, and brand context, and its input files: still, source video, storyboard, logo, and music only when the new format is a video. Files are hard-linked into the new job's own directory (copy fallback), so per-job cleanup never affects a sibling; inputs are only ever replaced atomically, never edited in place, which makes linking safe. Missing originals give a clear 409; storage or database failures remove the new directory and leave no row. URL versions reuse the fetched image, so the page is not fetched again.

**Numbering.** Migration `0009` adds `parent_id`, `root_id`, and `variant` (default 1) with a unique `(root_id, variant)` index. A version gets one more than the highest number in its family, so a version of a version continues the sequence. Concurrent requests that collide on a number are retried against the unique index (up to three times, then 409).

**Fresh copy.** The worker reads the parent's hook and title and passes them to the provider with the version number. Ollama: from version 2 the prompt asks for a clearly different angle and a new hook and lists the previous lines as untrusted `previous_copy` data; the version 1 prompt is unchanged. Demo: version 1 is unchanged; later versions rotate through two more deterministic template sets and skip any whose hook matches the parent's.

**UI.** The control sits under Download in the preview panel: platform and format selects (formats filtered by platform), a hint (music is left out for image formats), and a button naming the target ("Create a new YouTube Thumbnail version"). On success it navigates with a real history entry (`#job=<new id>`), so Back returns to the original; errors show inline and never navigate. Versions show a "Version N" label, and history cards a "v2" badge.

**Independent review.** A separate reviewer found two minor defects, both fixed test-first: a database error while choosing the version number left the new job's copied files on disk (the query now runs inside the block that cleans up), and a version form's error or in-flight request followed the user to another job, where a late response could navigate away from the job they had opened (both are now tied to the job they came from). The reviewer also ran migration 0009 up and down on SQLite and PostgreSQL.

Tests: 30 backend (contract, access, validation, file carry-over and cleanup, link fallback, numbering and races, rate limit, demo and Ollama variation, URL no-refetch, end-to-end render in a new format) and 10 frontend. Verified live in demo mode in headless Chrome: an Instagram square post with logo and brand colour → YouTube thumbnail v2 with a new hook, logo and colour carried over, history badge shown. Totals: 159 backend and 33 frontend tests.

## Phase 17 — media retention — 2026-11-19

Uploads and outputs used to stay on disk forever. Now a finished or failed job's media is deleted `MEDIA_RETENTION_DAYS` after it finished (default 30; 0 keeps media forever). The row and its generated text are kept, so the owner still sees what was made, the caption stays copyable, and the app can explain why the media is gone instead of failing with a 404 or a broken player.

**Purge (`app/services/retention.py`).** Selects up to 200 finished/failed, not-yet-purged jobs whose `completed_at` (or `updated_at`) is past the cutoff. Each job is first claimed with a conditional update that sets `purged_at` and clears every media path; only then is its folder deleted. Claiming first means a concurrent retry (whose own conditional update now also requires `purged_at IS NULL`) or a new version can never start from media that is being removed. If deleting the folder fails, the sweep below removes it later. Queued and processing jobs are never touched.

**Sweep.** Job folders older than a day whose job no longer exists or has expired are removed: for example, files left by a crash between storing an upload and saving its row. Only folders whose names are canonical job UUIDs are considered (never symlinks or other folders such as the development queue), and the one-day grace protects a job that is being created.

**Scheduling.** `social.purge_expired` runs hourly on the existing beat scheduler and once whenever a worker becomes ready. Interval schedules first fire one full interval after the scheduler starts, so services restarted more often than hourly would otherwise postpone retention indefinitely. Live testing found that hooking the start-up purge to the scheduler did not work locally: on macOS the embedded scheduler runs in a spawned process that never imports the app module, so its signal handler was not connected. The worker runs in the main process, and every deploy restarts it. The local launcher now runs the worker with an embedded scheduler, so stale-job recovery and retention also run locally.

**API and UI.** Responses and history rows include `expired`, and the platform config exposes `media_retention_days`. For an expired job, preview, download, and thumbnail answer 410 Gone with a clear message; retry and new version answer 410 too; `/content` still works. The owner check runs first, so strangers still get the standard 404. The UI (built by a parallel agent against this contract) replaces the player, download, and version form with a "This result has expired" state, keeps the caption panel, hides Retry on expired failures, shows "Expired" in history without requesting the thumbnail, and notes "Kept for N days" under Download.

**Independent review.** A separate reviewer found no data-loss, race, or access-control defects (it re-checked purge against retry, new versions, unfinished jobs, and timestamp handling on SQLite and PostgreSQL). It did find three issues, all fixed: the Docker Compose environment did not pass `MEDIA_RETENTION_DAYS` (containers do not read `.env`), so `0` would still have deleted after 30 days. The Compose environment now passes it, and the music and logo limits. The sweep's live-folder lookup could exceed PostgreSQL's 65,535-parameter limit and is now chunked. A folder disappearing mid-sweep no longer aborts the run.

Tests: 15 backend (age cutoff, unfinished and recent jobs kept, failed jobs purged, 0 disables, idempotence with missing folders, 410s and kept text, retry blocked, strangers still 404, orphan sweep rules, hourly schedule and task, start-up purge, chunked lookup, vanishing folders, config) and 9 frontend. Verified live: a job backdated 40 days was purged by the worker at start-up; its folder was gone, the API reported it expired with 410 for media, the caption was still served, and Chrome showed the expired state with no failed requests. Totals: 174 backend and 42 frontend tests.

## Walkthrough re-recorded — 2026-11-19

`delivery/walkthrough.mp4` now covers the current app in live AI mode in 2 min 12 s: brand kit, a new version for another platform, Recent creatives, video and URL inputs, an unsafe URL refused, an expired result, and per-browser privacy. It was recorded by driving headless Chrome over the DevTools protocol (screencast frames with their timestamps), with on-screen captions injected into the page, and assembled with FFmpeg. The four AI/render waits (13–30 s each) are fast-forwarded 6× and labelled as such. The retention scene ages one job past the cutoff and runs the same purge function the scheduled task uses. A first take was checked frame by frame and re-recorded: captions lagged behind two scene changes, and the privacy scene kept the previous form state because a hash-only navigation does not reload the page.

## Phase 18 — product data from structured markup — 2026-11-19

Product URLs used to rely only on Open Graph/Twitter tags, which are often a share banner or logo rather than the product. The fetcher now also reads schema.org Product JSON-LD (`<script type="application/ld+json">`, including `@graph` wrappers and multi-type entries) and takes the product's name, brand, description (HTML stripped, scripts dropped, capped), and gallery images from it, falling back to the tags field by field. Image candidates are tried in order, product photos first, up to three attempts, so a missing or unreadable first image no longer fails the job; if every attempt failed only for transient reasons (e.g. timeouts) the transient error is raised so the job retries automatically. Prices and offers are deliberately not passed on: they go stale and the prompts forbid price claims. Everything still goes through the same SSRF-hardened fetch, and page text stays untrusted data.

Checking real stores found two more things. Large storefront pages can put their JSON-LD after the 2 MB that is parsed for tags (one product page was 3.7 MB with JSON-LD at the very end), so when no Product is found in the parsed part the whole body is scanned for JSON-LD blocks with a bounded regex (512 KB of JSON at most) without parsing the rest of the HTML. And some sites build their product data in the browser, so their server HTML has no JSON-LD; those keep working through their Open Graph tags.

Tests: 9 backend (JSON-LD fields and precedence, ImageObject images, malformed and non-product blocks, image fallback order and the three-attempt bound, description cap, script stripping with a mutation check, late JSON-LD in a page over 2 MB). Verified against live stores: a Shopify product page now yields the product's name, brand, description, and a transparent product photo in 1.8 s; a page without JSON-LD still works from its tags; a link that redirects to a category page uses that page's share image. Totals: 182 backend and 42 frontend tests.
