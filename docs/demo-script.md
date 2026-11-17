# Walkthrough — target 4 minutes

Record only the application tab, with no personal tabs, credentials, or private product media visible. A captioned recording of the core flows exists at `delivery/walkthrough.mp4` (silent, real-time AI waits). This script is for a narrated version.

1. **0:00–0:30 — Frame the product.** Open Social Studio. Explain the scope: image, video, or product URL in; seven Instagram/TikTok/YouTube formats out. State whether this run uses live Ollama or explicit demo copy. Distinguish AI-written copy from template-based media rendering.
2. **0:30–1:10 — Create.** Upload `assets/sample-product.png`, pick Instagram → Reel, add a brand name/CTA, and start. Then switch to YouTube to show the format list change (Short, 16:9 Video, Thumbnail) and the dimension summary. If time allows, paste a public product page URL and show the "Read the product page" stage, or upload a short landscape clip for a TikTok video to show reframing with audio.
3. **1:10–1:45 — Observe.** Show queued and current stage. Explain that Celery works outside the request and the database persists status. Demo rendering is fast, so do not fabricate stage timings if it completes quickly.
4. **1:45–2:30 — Use the result.** Play the video. Download the MP4 and caption. Show the disclaimer and facts needing confirmation. Refresh the page and show that the result remains available.
5. **2:30–3:15 — Failure handling.** Demonstrate rejecting a text file or oversized image, and a private URL such as `http://169.254.169.254/` (SSRF guard). Explain safe persisted errors, manual retry, and stale-job recovery without showing internal logs or secrets.
6. **3:15–4:00 — Explain decisions.** Show the architecture diagram. Explain the narrow scope, structured model responses, real FFmpeg validation, upload security, and next improvements: delivery outbox, storage/authentication, additional creative templates, and then more formats.

Before submission: verify the deployed URL from a clean browser, record at most five minutes, and add the real URL and recording link to README. Do not describe demo copy as live inference.
