# Deployment preparation

No cloud resources have been created and no public URL exists. The supplied Dockerfiles and Compose application override are the concrete deployment starting point. Docker builds are unverified locally because Docker is not installed.

## Assessment topology

A single Linux host can run frontend, API, worker, scheduler, PostgreSQL, and Redis with a shared media volume. The worker also needs a reachable Ollama instance with enough memory for the configured model. Use an explicitly labeled demo configuration if inference infrastructure is unavailable. This avoids paying for a GPU merely to demonstrate the permitted simulated copy path.

The local Compose configuration binds ports to loopback. For public access, place an HTTPS reverse proxy in front of frontend/API, set a specific CORS origin, and build the frontend with the browser-accessible API URL. Do not expose PostgreSQL, Redis, or Ollama publicly. Set strong database credentials through environment/secrets; the example password is development-only.

Add an ingress upload/body limit and shared request/usage limits. Restrict reviewer access or add authentication before accepting private media. Job results are bound to the creating browser by an `HttpOnly` owner cookie; set `COOKIE_SECURE=true` behind HTTPS (the public override does) so it is never sent in clear text. Establish a storage retention policy, backups, log collection, health monitoring, and worker supervision. Only one scheduler should run.

## Verification before publishing

Build the images and run the combined Compose files; check migration completion, API readiness, worker registration, and Ollama reachability. Run `backend/scripts/smoke_test.py` against the deployed API. Check video playback, download, caption copy, failure handling, and refresh recovery in a clean browser. Verify dimensions and duration with ffprobe. Confirm no `.env`, runtime media, or credentials are included in the image/repository.

## Information needed to complete public delivery

- Deployment target/account and region, and the authorized spending limit.
- Public hostname or provided hosting URL, plus intended reviewer access.
- Whether the assessment deployment should use explicitly labeled demo copy or a provisioned Ollama model.

These decisions are needed before provisioning or exposing services. An AWS multi-host topology can later replace local files with S3 and the database with RDS; that additional infrastructure is not necessary to validate the initial workflow.

## Prepared HTTPS and reviewer access

After approving and configuring a writable host, set `SITE_ADDRESS` to its DNS name and supply `REVIEW_USERNAME` and `REVIEW_PASSWORD_HASH` through private environment configuration. Generate the bcrypt hash interactively with `caddy hash-password`; do not put a plain password in a command argument or commit it. Add `-f infrastructure/docker-compose.public.yml` to the two-file Compose command to enable Caddy HTTPS, a 110 MB ingress body limit (100 MB video uploads plus multipart overhead), and reviewer Basic authentication. DNS must already point to the host and ports 80/443 must be authorized. The API/worker/database/Ollama remain private. The public override is prepared, not yet deployed or build-tested.
