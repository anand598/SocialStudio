# Submission notes — how Social Studio meets the brief

Social Studio turns a product **image, video, or product-page URL** into a ready-to-post **video or image** for **Instagram, TikTok, or YouTube**. It also produces the caption, hashtags, and (for YouTube) title. All three inputs and all seven output formats work end to end, both with live AI (local Ollama) and in an explicitly labeled demo mode.

## Requirement checklist

| Brief | Status | Where / evidence |
| --- | --- | --- |
| Input: URL, image upload, or video upload | ✅ All three | Input tabs in [page.tsx](../frontend/src/app/page.tsx). URL ingest in [ingest/url.py](../backend/app/services/ingest/url.py); upload validation in [storage/local.py](../backend/app/services/storage/local.py) |
| Choose platform: Instagram, TikTok, YouTube | ✅ | Platform selector driven by `GET /api/v1/config/platforms` |
| Configure output: format appropriate to the platform | ✅ 7 formats | Format list filtered by platform, from the registry in [platforms.py](../backend/app/core/platforms.py) |
| Generate a video or image adapted to the aspect ratio and dimensions | ✅ | [renderer.py](../backend/app/services/media/renderer.py). Output is ffprobe-checked against the registry dimensions and fully decoded before the job completes |
| Show generation status | ✅ | Persisted stages (queued → fetching → analyzing → writing copy → rendering → done), polled by the UI. Restored after refresh via `#job=` |
| Preview and download | ✅ | Aspect-correct `<video>`/`<img>` preview, file download, and caption copy/download |
| Extra: background music | ✅ | Optional MP3/M4A/WAV for video formats: fitted to length and faded, or mixed under an uploaded clip's sound |
| Extra: brand colour and logo | ✅ | Optional colour (exact button colour, hue-tinted backdrop, contrast-safe text) and logo on every format ([promo.py](../backend/app/services/media/promo.py)) |
| Extra: recent creatives | ✅ | A per-browser history strip reopens past results ([RecentJobs.tsx](../frontend/src/app/RecentJobs.tsx), `GET /api/v1/generations`) |
| Extra: private results | ✅ | Only the browser that created a job can open it (owner cookie); see "Key decisions" |
| At least one input and one format end to end | ✅ Exceeded | 3 inputs × 7 formats. The live browser suite covered image → Reel and 4:5, video → TikTok and YouTube 16:9, and URL → YouTube thumbnail |
| Simulated generation explained if a service is unavailable | ✅ | See "Simulated vs functional" below |
| Explain code and decisions | ✅ | This document, plus [architecture](architecture.md) and [implementation notes](implementation-notes.md) |

| Platform | Format | Output | Size |
| --- | --- | --- | --- |
| Instagram | Reel / Feed 4:5 / Square 1:1 | MP4 / JPEG / JPEG | 1080×1920 / 1080×1350 / 1080×1080 |
| TikTok | Video | MP4 | 1080×1920 |
| YouTube | Short / Video / Thumbnail | MP4 / MP4 / JPEG | 1080×1920 / 1920×1080 / 1280×720 |

Each format also has platform text rules, enforced on the post text: TikTok allows at most 5 hashtags; YouTube allows at most 3 hashtags plus a title of up to 100 characters; caption length limits apply.

## Simulated vs functional

| Part | Real or simulated |
| --- | --- |
| Upload validation, URL fetching, job queue, status, storage, preview, download | Real |
| Media rendering (Pillow + FFmpeg) at exact platform dimensions | Real, in both modes |
| Product analysis (what is in the image or video) and copywriting | **Real** in `ollama` mode (local `qwen3.5:4b` vision model). **Simulated** in `demo` mode: deterministic template copy, no image analysis. The UI shows a banner when demo mode is on |
| Generative video/image synthesis (text-to-video, AI image editing) | **Not used.** Videos are built from your media: still images are animated with zoom/fade scenes; source videos are reframed with overlays and their original audio |

The mode is chosen in configuration and stored on every job. The app never falls back to demo silently.

## How it works

```
Browser (Next.js) ──/api proxy──▶ FastAPI ──job id──▶ Celery worker
                                    │                    │ fetch URL (SSRF-safe)
                                    ▼                    │ analyze (Ollama vision)
                              Job table (status,        │ write copy (structured JSON)
                              results, errors)  ◀───────┘ render (Pillow/FFmpeg) → validate
```

1. **API** ([generations.py](../backend/app/api/generations.py)) validates the input and format, stores the file, creates a job row, and enqueues only the job ID. It returns 202 immediately.
2. **Worker** ([tasks.py](../backend/app/workers/tasks.py)) runs the stages and saves each one to the database, so the UI shows real progress and survives restarts.
3. **AI provider** ([provider.py](../backend/app/services/ai/provider.py)) asks the model for JSON that matches a Pydantic schema ([content.py](../backend/app/schemas/content.py)), validates it, and retries bounded failures. For a video it analyzes a 2×2 storyboard of four frames taken across the clip, not just one frame.
4. **Renderer** produces one of three outputs: a designed poster with a bold headline (image formats), a promo video built from the photo itself: tinted, blurred backdrop, the product in a shadowed card, a shot plan of whole product → close-ups → end card with a CTA button, animated captions, and cross-fades (still → video), or the source clip reframed over a blurred fill with hook, CTA, and brand overlays (video → video). On 9:16 video, text stays clear of the areas TikTok, Reels, and Shorts cover with their own UI.
5. **UI** ([page.tsx](../frontend/src/app/page.tsx)) polls the job and shows stages, the preview, downloads, and errors with a retry option.

## Key decisions

- **One format registry as the source of truth.** Dimensions, output type, and text limits live in [platforms.py](../backend/app/core/platforms.py). The renderer, validator, prompts, post text, and UI all read from it, so adding a format means adding one data entry and a test.
- **Real rendering, AI for understanding and copy.** Hosted text-to-video is costly, slow, and unreliable for product accuracy. Rendering from the user's own media keeps the product faithful and makes the output exactly platform-sized every time.
- **Local, free AI (Ollama) instead of a paid API.** No keys or spending are needed, and product media never leaves the machine. The trade-off is speed: about 20–35 s per job on a 16 GB Mac.
- **Structured output with validation.** The model must return schema-valid JSON, and invalid or cut-off answers are retried. Live testing found that the model sometimes padded its answer with whitespace until it hit the length limit. Reordering the schema fields, capping tokens per step, and retrying fixed this; details are in implementation notes, Phase 10.
- **Background jobs with database state.** Rendering takes seconds to minutes, so it runs outside the HTTP request. Atomic claims and per-attempt IDs stop duplicate or stale workers from overwriting results, and stuck jobs expire and can be retried.
- **Results are private without needing accounts.** Creating a job sets a random `HttpOnly` cookie, and the job stores only its hash. Every read, preview, download, and retry must present that cookie, otherwise the API answers 404, so a leaked link reveals nothing. A cookie (not a header) is used because `<video>`/`<img>` tags and download links cannot send custom headers. User accounts remain a next step.
- **Safety at the edges.** Uploads are checked by size, type, and decoded content, and image metadata is stripped. URL fetching blocks private and internal addresses, pins DNS, and re-validates redirects. Error messages never expose internals.
- **Honest labeling.** Demo mode is visible, AI copy lists the facts the user should confirm, and prompts forbid invented product claims.

## Verification

- 129 backend tests: real FFmpeg renders and decodes, every format's dimensions, upload rejection, URL protection, AI schema handling, job lifecycle, access control, and render quality rules (bold headline size, safe zones, hook card).
- 23 frontend tests, typecheck, and production build.
- Live browser run (headless Chrome against live Ollama): 5 generation flows and 13 navigation, error, mobile, and network checks passed.
- A 34 MB video uploaded through the UI is accepted.

## Not done (next steps)

User accounts (results are currently tied to one browser, not a person), cloud deployment and a public URL, Docker images verified (prepared but not built here), object storage, speech-to-text for video audio, and JavaScript-rendered product pages. The full list is in [implementation notes](implementation-notes.md#known-limitations-and-next-improvements).
