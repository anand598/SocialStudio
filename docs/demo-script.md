# Walkthrough — target 4 minutes

Record only the application tab, with no personal tabs, credentials, or private product media visible. This is a recording script; no walkthrough has been recorded yet.

1. **0:00–0:30 — Frame the product.** Open Social Studio. Explain the image-to-Instagram-Reel scope. State whether this run uses live Ollama or explicit demo copy. Distinguish AI-written copy from template-based media rendering.
2. **0:30–1:10 — Create.** Upload `assets/sample-product.png`. Show the supported platform/format and optional brand name/CTA. Start generation.
3. **1:10–1:45 — Observe.** Show queued and current stage. Explain that Celery works outside the request and the database persists status. Demo rendering is fast, so do not fabricate stage timings if it completes quickly.
4. **1:45–2:30 — Use the result.** Play the video. Download the MP4 and caption. Show the disclaimer and facts needing confirmation. Refresh the page and show that the result remains available.
5. **2:30–3:15 — Failure handling.** Demonstrate rejecting a text file or oversized image. Explain safe persisted errors, manual retry, and stale-job recovery without showing internal logs or secrets.
6. **3:15–4:00 — Explain decisions.** Show the architecture diagram. Explain the narrow scope, structured model responses, real FFmpeg validation, upload security, and next improvements: delivery outbox, storage/authentication, additional creative templates, and then more formats.

Before submission: verify the deployed URL from a clean browser, record at most five minutes, and add the real URL and recording link to README. Do not describe demo copy as live inference.
