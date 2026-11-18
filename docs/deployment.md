# Deployment preparation

The live instance is listed in the [submission summary](submission.md). This page covers what any deployment needs. The supplied Dockerfiles and Compose application override are the starting point for a container deployment.

After each update, run `alembic upgrade head` before starting the new API and worker, and keep exactly one scheduler running: it expires stuck jobs every minute and purges expired media every hour. Rate limits are shared through Redis and identify clients by `X-Forwarded-For` only from `TRUSTED_PROXIES` (Compose trusts the private ranges its own containers use). If the host serves IPv6 visitors, enable IPv6 on the Docker network or run Caddy with host networking: otherwise Docker's proxy presents every IPv6 visitor as the bridge gateway and they share one quota. Containers do not read `.env`; settings must be passed through the Compose environment (as `infrastructure/docker-compose.app.yml` does for `MEDIA_RETENTION_DAYS` and the upload limits).

## Assessment topology

A single Linux host can run frontend, API, worker, scheduler, PostgreSQL, and Redis with a shared media volume. The worker also needs a reachable Ollama instance with enough memory for the configured model. Use an explicitly labeled demo configuration if inference infrastructure is unavailable. This avoids paying for a GPU merely to demonstrate the permitted simulated copy path.

The local Compose configuration binds ports to loopback. For public access, place an HTTPS reverse proxy in front of frontend/API, set a specific CORS origin, and build the frontend with the browser-accessible API URL. Do not expose PostgreSQL, Redis, or Ollama publicly. Set strong database credentials through environment/secrets; the example password is development-only.

Add an ingress upload/body limit and shared request/usage limits. Restrict reviewer access or add authentication before accepting private media. Job results are bound to the creating browser by an `HttpOnly` owner cookie; set `COOKIE_SECURE=true` behind HTTPS (the public override does) so it is never sent in clear text. Establish backups, log collection, health monitoring, and worker supervision. Only one scheduler should run.

## Verification before publishing

Build the images and run the combined Compose files; check migration completion, API readiness, worker registration, and Ollama reachability. Run `backend/scripts/smoke_test.py` against the deployed API. Check video playback, download, caption copy, failure handling, and refresh recovery in a clean browser. Verify dimensions and duration with ffprobe. Confirm no `.env`, runtime media, or credentials are included in the image/repository.

## Scaling beyond one host

An AWS multi-host topology can later replace local files with S3 and the database with RDS; that additional infrastructure is not necessary to validate the initial workflow.

## Prepared HTTPS and reviewer access

After approving and configuring a writable host, set `SITE_ADDRESS` to its DNS name and supply `REVIEW_USERNAME` and `REVIEW_PASSWORD_HASH` through private environment configuration. Generate the bcrypt hash interactively with `caddy hash-password`; do not put a plain password in a command argument or commit it. Add `-f infrastructure/docker-compose.public.yml` to the two-file Compose command to enable Caddy HTTPS, a 110 MB ingress body limit (100 MB video uploads plus multipart overhead), and reviewer Basic authentication. DNS must already point to the host and ports 80/443 must be authorized. The API/worker/database/Ollama remain private. The public override is prepared, not yet deployed or build-tested.
