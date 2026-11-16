# Codex Handover: AI-Powered Social Media Content Generator

**Document purpose:** Give Codex the product requirements, architecture, implementation sequence, engineering constraints, and acceptance criteria needed to implement the assessment as a working application.

**Primary source:** User-provided *Tech Lead Assessment: Build AI-Powered Social Media Content Generator* (1 page).

---

## 1. Mission and expected outcome

Build a usable web application that turns a product URL, image, or video into social-media-ready content for Instagram, TikTok, or YouTube.

The application must let a user:

1. Provide a product URL, upload an image, or upload a video.
2. Select a target platform.
3. Select an output format supported by that platform.
4. Generate content adapted to the selected format's aspect ratio and dimensions.
5. See generation progress.
6. Preview and download the generated result.

The assessment explicitly prioritizes a complete working workflow over a large feature set. At least one input type must work end to end, and at least one platform format must be implemented correctly. If a real image/video generation service is unavailable, implement a working simulated generation flow and clearly document what is functional versus simulated.

**Initial vertical slice:** Image upload → AI product analysis → Instagram Reel creative package → rendered 9:16 video → preview/download.

Do not attempt to implement every input and platform before this vertical slice works reliably.

## 2. Assessment deliverables

The finished project must include:

- A deployed live application URL accessible to reviewers.
- A demo video walkthrough of no more than 5 minutes.
- A readable Git repository with meaningful commits where possible.
- A README with setup instructions, architecture, technology choices, assumptions, and limitations.
- Implementation notes covering:
  - What is real versus simulated.
  - Known issues.
  - Trade-offs.
  - What should be improved next and how the product could evolve.

The implementation will be evaluated on:

- End-to-end ownership and implementation.
- Technical design, asynchronous workflows, and failure handling.
- Engineering fundamentals and code quality.
- Failure cases, persistence, security, and production deployment.
- Product thinking, prioritization, and communication.
- Ability to explain decisions and identify the next highest-value improvements.

## 3. Developer environment and agreed stack

The developer machine is an **Apple Silicon Mac with 16 GB RAM**.

Use the following stack unless a concrete compatibility issue requires a documented change:

| Area | Technology |
|---|---|
| Frontend | Next.js App Router, React, TypeScript |
| Styling | Tailwind CSS |
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | PostgreSQL |
| ORM / migrations | SQLAlchemy 2.x, Alembic |
| Background jobs | Celery |
| Queue / broker | Redis |
| Local LLM runtime | Ollama |
| Initial LLM choice | `qwen3.5:4b`, configurable |
| Image processing | Pillow |
| Video processing | FFmpeg / ffprobe |
| Local development | Docker Compose |
| Production direction | Docker-based deployment on AWS; object storage such as S3 |
| Testing | pytest for backend; frontend test tooling selected by Codex and documented |

### Important AI and media boundary

- Ollama is for product understanding and text generation. Keep model name, base URL, timeout, and generation settings configurable through environment variables.
- The initial model choice is `qwen3.5:4b`, but do not hard-code assumptions about model capabilities. Verify that the installed model supports the image-analysis operation required by the implementation. If it does not, provide a configurable vision-model setting and document the required Ollama model.
- **Do not claim that Ollama generates finished images or videos.** The initial deliverable should use real local processing (Pillow and FFmpeg) to create a branded/template-based creative from the supplied product image and AI-generated copy.
- Treat template-based media rendering as a real implemented feature. Treat generative image/video synthesis as a future integration unless an actual provider is configured and working.
- Do not require a paid third-party API for the initial local end-to-end workflow.

## 4. Product scope and prioritization

### P0 — required end-to-end vertical slice

1. Upload one product image.
2. Validate file type, size, and content.
3. Store the original image safely.
4. Analyze the image and generate structured product information.
5. Generate Instagram marketing content:
   - Hook / opening line.
   - Short product description.
   - Three product benefits (only where supported by the input; do not invent factual specifications).
   - Caption.
   - Call to action.
   - Hashtags.
   - Short video scene / storyboard plan.
6. Render a vertical 9:16 MP4 creative using the supplied image, text overlays, and simple motion/transitions.
7. Track generation status and errors.
8. Preview the result in the browser.
9. Download the MP4 and copy/download the caption package.
10. Persist the job and its result metadata.

### P1 — next features after P0 is stable

- Upload a source video and produce a processed platform-sized output.
- Product URL input, with safe fetching and extraction.
- Instagram feed image formats (1:1 and 4:5).
- TikTok vertical video.
- YouTube Shorts vertical video.
- YouTube standard video (16:9).
- Job history and regeneration.
- Custom brand name, logo, colors, and CTA.
- Retry failed jobs.

### P2 — future enhancements

- Real generative image/video provider integration behind provider interfaces.
- More templates and brand kits.
- Multi-language copy.
- Multiple creative variants.
- User accounts and team workspaces.
- Usage quotas, analytics, and billing.

Do not let P1/P2 work delay the complete P0 workflow.

## 5. Platform output configuration

Create a centralized platform/format configuration rather than scattering dimensions across UI and rendering code.

Initial formats:

| Platform | Format | Aspect ratio | Target dimensions |
|---|---|---:|---:|
| Instagram | Reel | 9:16 | 1080 × 1920 |
| Instagram | Feed square | 1:1 | 1080 × 1080 |
| Instagram | Feed portrait | 4:5 | 1080 × 1350 |
| TikTok | Video | 9:16 | 1080 × 1920 |
| YouTube | Shorts | 9:16 | 1080 × 1920 |
| YouTube | Standard video | 16:9 | 1920 × 1080 |

Keep these values in a single typed configuration module and use it for format selection, validation, rendering, and tests. Do not imply that every platform/format is implemented until it is actually supported.

For P0, expose only **Instagram Reel (9:16, 1080 × 1920)** in the UI.

## 6. Proposed architecture

Use a modular monolith initially. Avoid unnecessary microservices for an assessment-sized product.

```text
Browser
  |
  v
Next.js frontend
  |
  | REST API
  v
FastAPI backend
  |             \
  |              \ enqueue job
  v               v
PostgreSQL       Redis broker
                   |
                   v
                Celery worker
                   |
          +--------+---------+
          |                  |
          v                  v
      Ollama service     Media pipeline
      product analysis   Pillow + FFmpeg
          |                  |
          +--------+---------+
                   |
                   v
             File storage
       (local in development,
        object storage later)
```

### Responsibilities

**Frontend**
- Input form and upload experience.
- Platform/format selection.
- Job status and progress display.
- Result preview, caption display, and download actions.
- Friendly validation and failure messages.

**FastAPI**
- Request validation and API contracts.
- File upload handling and storage coordination.
- Job creation and status retrieval.
- Authentication/authorization can be deferred for local assessment MVP, but structure routes/services so it can be added.
- Never run long AI or FFmpeg work inside a normal request handler.

**Celery worker**
- Executes AI analysis and media generation asynchronously.
- Updates persisted job state at each stage.
- Handles retries only for transient failures.
- Writes output artifacts and final metadata.

**PostgreSQL**
- Persists jobs, inputs, selected platform/format, status, errors, generated copy, and output metadata.
- Do not store large binary media in database rows.

**Redis**
- Celery broker and, if needed, result backend.
- PostgreSQL remains the source of truth for user-visible job state.

**Ollama**
- Local inference over HTTP.
- Isolate model calls behind an `LLMProvider`/service interface.
- Add timeout, structured-output validation, and clear error mapping.

**Media pipeline**
- Pillow for image inspection, resizing/cropping, text overlays, and thumbnail generation.
- FFmpeg for video composition, encoding, audio handling, and metadata checks.
- Use subprocess argument arrays, never shell-interpolated user input.

## 7. Suggested repository layout

Codex may adjust names where justified, but preserve clear separation of concerns.

```text
ai-social-content-generator/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── generation/
│   │   │   ├── upload/
│   │   │   └── preview/
│   │   ├── lib/
│   │   └── types/
│   ├── public/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── ai/
│   │   │   ├── media/
│   │   │   └── storage/
│   │   ├── workers/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── infrastructure/
│   └── docker-compose.yml
├── storage/                 # local runtime data; gitignored
├── docs/
│   ├── architecture.md
│   ├── implementation-notes.md
│   └── demo-script.md
├── .env.example
├── .gitignore
└── README.md
```

## 8. Core data model

Use UUID identifiers and UTC timestamps. At minimum implement a `GenerationJob` entity/table with fields equivalent to:

- `id`
- `status`: `queued | processing | completed | failed`
- `stage`: e.g. `validating | analyzing | writing_copy | rendering | finalizing`
- `progress`: integer 0–100 (best-effort stage progress; do not imply exact work percentage if unknown)
- `input_type`: initially `image`; later `video | url`
- `input_file_path` or storage key
- `platform`
- `format`
- `product_analysis` JSON
- `generated_content` JSON
- `output_file_path` or storage key
- `thumbnail_file_path` or storage key
- `error_code`
- `error_message` (safe user-facing message; detailed exception only in server logs)
- `created_at`, `updated_at`, `started_at`, `completed_at`

Use separate tables for assets or generation variants only if they add clear value. Add Alembic migrations and do not rely on `create_all()` as the production schema-management strategy.

## 9. API contract

Use versioned routes under `/api/v1`.

Suggested initial endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness check |
| GET | `/api/v1/ready` | Dependency/readiness check |
| POST | `/api/v1/generations` | Upload image and create generation job |
| GET | `/api/v1/generations/{job_id}` | Read persisted job status and result |
| GET | `/api/v1/generations/{job_id}/content` | Retrieve generated copy/package |
| GET | `/api/v1/generations/{job_id}/download` | Download completed media |
| GET | `/api/v1/config/platforms` | Return supported platforms/formats |

For `POST /generations`, accept multipart form data:
- `file`
- `platform`
- `format`
- optional `brand_name`
- optional `brand_description`
- optional `call_to_action`

Return `202 Accepted` with a job ID and initial status. The frontend should poll the status endpoint at a reasonable interval, or use SSE later if useful. Polling is sufficient for the first reliable version.

Validate that the requested platform/format pair is supported. For P0, only accept Instagram Reel.

Define response schemas explicitly with Pydantic. Keep API errors consistent and avoid returning stack traces.

## 10. AI content generation requirements

Implement an AI service interface with methods such as:

- `analyze_product_image(image_path) -> ProductAnalysis`
- `generate_social_content(product_analysis, platform, format, brand_context) -> SocialContent`

Use Pydantic models for structured output. Validate model responses and handle malformed JSON with a bounded retry or a clear job failure.

Example `ProductAnalysis` fields:
- `product_name` (nullable if not identifiable)
- `product_category`
- `visible_attributes`
- `visible_text`
- `likely_audience` (mark as an inference)
- `visual_style`
- `confidence_or_limitations`
- `facts_needing_user_confirmation`

Example `SocialContent` fields:
- `hook`
- `short_description`
- `benefits`
- `caption`
- `call_to_action`
- `hashtags`
- `scenes` (ordered list of scene text and duration)
- `disclaimer_or_assumptions`

Important:
- Do not invent product specifications, prices, certifications, performance claims, or guarantees.
- Clearly distinguish observed facts from inferred marketing suggestions.
- If product identity is uncertain, ask the user to edit/confirm product details or use cautious generic copy.
- Make prompts platform-aware and constrain output lengths.
- Do not expose internal prompts, secrets, or raw provider errors to the browser.

## 11. Media generation requirements

For the P0 workflow, implement a genuine template-based video renderer.

Suggested flow:
1. Load the original uploaded image.
2. Create a 1080 × 1920 canvas with a suitable background.
3. Crop/fit the product image without distorting it.
4. Render hook, product name (if known), selected benefits, CTA, and branding.
5. Create a small number of scenes with simple zoom/pan or fade transitions.
6. Use FFmpeg to compose scenes into an MP4.
7. Produce a thumbnail.
8. Run ffprobe to verify output dimensions, duration, and codec/container.
9. Mark the job complete only after the output file exists and passes validation.

Use a royalty-free or self-generated silent background by default. Do not bundle copyrighted music. If audio is added later, ensure the user has rights to it.

The UI and implementation notes must call this **template-based video rendering**, not AI-generated video. The AI generates the copy/storyboard; Pillow and FFmpeg create the media.

## 12. Asynchronous workflow and state transitions

The request handler should validate/store the input, create a database job, enqueue a Celery task, and return quickly.

Suggested state progression:

```text
queued
  |
  v
processing: validating
  |
  v
processing: analyzing
  |
  v
processing: writing_copy
  |
  v
processing: rendering
  |
  v
processing: finalizing
  |
  +------> completed
  |
  +------> failed
```

Requirements:
- Persist each meaningful state transition.
- The frontend must show queued, processing, completed, and failed states.
- A worker crash must not leave jobs permanently shown as processing without a recovery strategy.
- Use bounded retries for transient Ollama/Redis/storage errors where safe.
- Do not retry deterministic validation errors or malformed user input indefinitely.
- Make task execution idempotent enough to avoid duplicate output or corrupted state when a task is retried.
- Keep internal exception details in logs; store safe error codes/messages for users.
- Define timeouts for Ollama and FFmpeg.
- Add a basic stale-job recovery approach or document its limitation.

## 13. Security, validation, and reliability

Implement these from the beginning, not as a final polish step:

### Upload security
- Enforce a configurable maximum file size.
- Allowlist supported image MIME types and extensions.
- Verify actual file content rather than trusting the browser-provided MIME type or filename.
- Generate server-side filenames; never use raw user filenames as storage paths.
- Reject malformed or unsupported files.
- Store uploads outside the publicly served frontend directory.
- Prevent path traversal.
- Avoid logging sensitive file contents or secrets.

### URL input (when implemented)
- Protect against SSRF: block loopback, private, link-local, and reserved IP ranges; validate redirects and DNS resolutions; restrict protocols to HTTP/HTTPS.
- Apply timeouts, response-size limits, and content-type allowlists.
- Do not fetch arbitrary local-network resources.
- Do not execute downloaded content.

### API and infrastructure
- Keep secrets in environment variables; commit only `.env.example`.
- Configure CORS for known frontend origins.
- Add request timeouts and safe error responses.
- Use non-root containers where practical.
- Pin or constrain dependencies and document upgrades.
- Add health checks for application and dependencies.
- Do not expose PostgreSQL, Redis, or Ollama publicly in production.
- Add rate limiting before public deployment.
- Ensure generated download routes only serve assets belonging to the requested job.

## 14. Frontend UX requirements

Create a clean, professional dashboard suitable for a product demo.

P0 screen should contain:
- Product image upload area with drag/drop and browse.
- File type and size guidance.
- Platform selector (only Instagram enabled initially).
- Format selector (Instagram Reel only initially).
- Optional brand name and CTA fields.
- Generate button with disabled/loading states.
- Job progress/status panel.
- Clear error and retry guidance.
- Completed result preview with video controls.
- Download video action.
- Generated caption, hashtags, and copy-to-clipboard action.

The user must never be left wondering whether generation is running. Show the current stage and a useful status message. Do not fake progress percentages; stage-based progress is acceptable.

## 15. Local development and environment configuration

Provide `.env.example` with documented variables, for example:

```dotenv
APP_ENV=development
API_HOST=0.0.0.0
API_PORT=8000
FRONTEND_ORIGIN=http://localhost:3000

DATABASE_URL=postgresql+psycopg://app:app_password@localhost:5432/social_content
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:4b
OLLAMA_VISION_MODEL=qwen3.5:4b
OLLAMA_TIMEOUT_SECONDS=120

STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=./storage
MAX_UPLOAD_SIZE_MB=15
```

Adjust connection hostnames appropriately depending on whether a process runs on the host or inside Docker. On Apple Silicon macOS, Ollama may run directly on the host while Docker containers access it through `host.docker.internal`. Verify this in the actual environment; do not assume it works without testing.

Use safe development-only credentials and clearly state that production secrets must be changed.

README must include exact commands to:
- Install prerequisites.
- Start PostgreSQL and Redis.
- Install backend dependencies.
- Run database migrations.
- Start FastAPI.
- Start Celery worker.
- Install and run the frontend.
- Install/pull/run the Ollama model.
- Run tests.
- Troubleshoot common issues.

## 16. Testing and acceptance criteria

Do not mark a stage complete merely because the server starts.

### Backend tests
- Health and readiness endpoints.
- Upload accepts valid supported image.
- Upload rejects invalid MIME/content, oversized file, and malformed image.
- Unsupported platform/format is rejected.
- Job creation returns 202 and a job ID.
- Job status is persisted and transitions correctly.
- AI response schema validation works, including malformed response handling.
- Media output is created and validated.
- Download endpoint returns the expected completed asset.
- Failure path stores a safe error state.

Use mocked Ollama responses for deterministic automated tests. Add an optional local integration test for a running Ollama instance.

### Frontend checks
- Upload validation and error display.
- Generate button and pending state.
- Job polling and status transitions.
- Completed preview and download.
- Failed job display.
- Responsive layout and basic accessibility.

### P0 end-to-end acceptance test

A reviewer must be able to:
1. Open the deployed application.
2. Upload a valid product image.
3. Select Instagram Reel.
4. Start generation.
5. See the job progress through its stages.
6. Receive generated marketing copy and a rendered MP4.
7. Preview the MP4 in the browser.
8. Download the MP4 and copy the caption.

The MP4 must be 1080 × 1920, playable, and have a sensible duration. The job and result metadata must remain available after refreshing the page.

If external AI inference is unavailable, the app must clearly indicate whether a deterministic demo/fallback path is being used. Never silently present hard-coded demo output as live AI output.

## 17. Implementation sequence for Codex

Work in small, verifiable increments. At the end of each phase, run relevant tests and report the result.

### Phase 0 — inspect and establish baseline
- Inspect the current repository before changing it.
- Preserve useful existing work.
- Identify the current state of the Stage 1 starter project.
- Check Python, Node, Docker, and Ollama prerequisites.
- Report any mismatch between this document and existing files.
- Do not overwrite user files without understanding their contents.

### Phase 1 — complete the application skeleton
- Ensure frontend and backend start.
- Add PostgreSQL and Redis via Docker Compose.
- Add configuration validation and health/readiness endpoints.
- Add structured logging.
- Add Alembic and the initial migration.
- Add a simple frontend page that calls the backend health endpoint.
- Verify host-to-container connectivity, including Ollama access where needed.

### Phase 2 — image upload and persistence
- Implement upload endpoint, validation, local storage service, and job record.
- Add tests for valid and invalid uploads.
- Add the upload UI.

### Phase 3 — AI analysis and copy
- Implement Ollama provider and configurable model settings.
- Implement product analysis and structured marketing content.
- Validate output with Pydantic.
- Add mocked tests and an optional local model integration test.

### Phase 4 — asynchronous generation
- Add Celery worker and task lifecycle.
- Persist stage transitions and safe failures.
- Implement job status API and frontend polling.

### Phase 5 — media rendering
- Implement Pillow scene generation and FFmpeg MP4 rendering.
- Verify dimensions, codecs, duration, and playability.
- Generate thumbnail and expose preview/download.

### Phase 6 — hardening
- Add retries, timeouts, idempotency safeguards, stale-job handling, security checks, and operational logging.
- Run backend/frontend tests and the full local end-to-end flow.

### Phase 7 — assessment delivery
- Complete README and implementation notes.
- Prepare a concise architecture diagram.
- Prepare a demo script and record a walkthrough of no more than 5 minutes.
- Deploy the app and verify the public URL from a clean browser session.
- Ensure the repository contains no secrets or generated user media.

## 18. Codex working instructions

Follow these rules throughout implementation:

1. **Inspect before editing.** Start by listing and reading the existing project files. Do not assume the starter ZIP has already been extracted or that its structure matches this document.
2. **Implement, don't just advise.** Create and modify the actual source files, tests, migrations, Docker configuration, and documentation.
3. **Work incrementally.** Finish one phase, run checks, fix failures, then proceed.
4. **Explain meaningful decisions.** Briefly state what changed, why, and any trade-offs.
5. **No fake completion.** Never claim a service, integration, test, deployment, or generation path works unless it has been run and verified.
6. **No hidden simulation.** Clearly label mock, fallback, and template-rendered functionality.
7. **Keep configuration externalized.** No hard-coded credentials, URLs, model secrets, or environment-specific paths.
8. **Maintain quality.** Add type hints, clear names, small modules, validation, useful logs, and tests.
9. **Avoid overengineering.** Build a modular monolith first; do not introduce Kubernetes, microservices, or complex infrastructure without a demonstrated need.
10. **Protect the user's machine.** Do not run destructive cleanup commands, delete existing files/data, or overwrite environment files without checking first.
11. **Ask only when blocked.** Make reasonable reversible choices and document them. Ask the user before actions that incur costs, publish data, expose services publicly, or require credentials.
12. **Keep a running implementation log** in `docs/implementation-notes.md`, distinguishing implemented, simulated, pending, and known limitations.

### First Codex response / first action

Begin with **Phase 0**. Inspect the repository and report:
- Current directory structure.
- Which Stage 1 components already exist.
- Missing or broken prerequisites.
- Exact commands needed to run the existing baseline.
- A short plan for Phase 1.

Then proceed with Phase 1 implementation. Do not start by generating the entire application in one pass.

---

## 19. Definition of done

The project is ready for assessment only when:

- The P0 workflow works end to end.
- A user can see status, preview, and download.
- At least one platform/format is correctly implemented.
- Job state and result metadata persist.
- Failure paths are handled and communicated.
- Security basics are implemented and documented.
- Tests pass and the README allows another developer to run the project.
- Real functionality and simulation are clearly distinguished.
- Live deployment and a demo video (maximum 5 minutes) are available.
- The candidate can explain the architecture, asynchronous processing, failure handling, security, trade-offs, and next improvements.

**Guiding principle:** Deliver one complete, reliable, honestly described product workflow before expanding feature breadth.
