"use client";

import { useCallback, useEffect, useState } from "react";
import { request } from "../lib/api";
import type { Config, InputType, Job } from "../lib/types";
import { useJobPolling } from "../lib/useJobPolling";
import CopyPanel from "./CopyPanel";
import CreateForm from "./CreateForm";
import RecentJobs from "./RecentJobs";
import ResultPanel from "./ResultPanel";

// The API answers 404 for missing jobs and for jobs created in another browser alike.
const UNAVAILABLE_JOB =
  "This result isn't available here. Results open only in the browser that created them — create a new one below.";

/**
 * The studio page. It loads the config and wires the pieces together: the form's
 * input type and format (which the result panel previews before a job exists), the open
 * job (useJobPolling), and the submitting / error / copied state that several pieces share.
 */
export default function Home() {
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState("");
  const loadConfig = useCallback(() => {
    setConfigError("");
    request<Config>("/api/v1/config/platforms")
      .then(setConfig)
      .catch(() =>
        setConfigError(
          "We couldn’t connect to the service. Check that the API is running, then reconnect.",
        ),
      );
  }, []);
  useEffect(loadConfig, [loadConfig]);

  const [inputType, setInputType] = useState<InputType>("image");
  const [target, setTarget] = useState({
    platform: "instagram",
    format: "reel",
  });
  // Shown under the form: upload validation, create and retry failures, clipboard errors.
  const [error, setError] = useState("");
  // A create or retry request is in flight.
  const [submitting, setSubmitting] = useState(false);
  // The job whose caption was last copied, so the label never carries over to another job.
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const { job, jobID, pollError, unavailable, open, reopen, isOpen } =
    useJobPolling();
  const busy =
    submitting || job?.status === "queued" || job?.status === "processing";
  const formats = config?.formats ?? [];
  const platformFormats = formats.filter(
    (item) => item.platform === target.platform,
  );
  const selectedFormat =
    platformFormats.find((item) => item.format === target.format) ??
    platformFormats[0];
  const jobFormat = formats.find(
    (item) => item.platform === job?.platform && item.format === job?.format,
  );
  const resultFormat = jobFormat ?? selectedFormat;
  const retentionDays = Math.max(0, config?.media_retention_days ?? 0);
  const content = job?.generated_content;

  async function create(body: FormData) {
    setSubmitting(true);
    setError("");
    try {
      const next = await request<Job>("/api/v1/generations", {
        method: "POST",
        body,
      });
      open(next);
      window.history.replaceState(null, "", `#job=${next.id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Upload failed. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function retry() {
    if (!job || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const next = await request<Job>(`/api/v1/generations/${job.id}/retry`, {
        method: "POST",
      });
      // Restart polling for this same persisted job.
      reopen(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function openVariant(from: string, next: Job) {
    // The user opened another job meanwhile: the version is still made (it shows in
    // Recent creatives), but don't pull them away from what they chose.
    if (!isOpen(from)) return;
    open(next);
    // A real history entry, so Back returns to the original.
    window.location.hash = `job=${next.id}`;
  }

  return (
    <div className="studio-shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="Social Studio home">
          <span className="mark">s</span> social studio
          <span className="wordmark-dot">.</span>
        </a>
        <div className="topbar-right">
          <span className="connection-dot" />
          Your next creative starts here
        </div>
      </header>
      <main>
        <section className="intro">
          <div>
            <div className="eyebrow">PRODUCT IN. STORY OUT.</div>
            <h1>
              Make a little
              <br />
              <em>scroll-stopping</em> magic.
            </h1>
            <p>
              A product image, video or link — and a fresh perspective.
              <br className="desktop-break" /> Create Instagram, TikTok and
              YouTube content that puts your product first.
            </p>
          </div>
          <div className="intro-note">
            <span>01 / THE CREATIVE STUDIO</span>
            <p>
              AI-assisted storytelling.
              <br />
              Real, template-rendered video.
              <br />
              Made from your product.
            </p>
            <div className="tiny-stars">✳ &nbsp; ✳ &nbsp; ✳</div>
          </div>
        </section>
        {config?.generation_mode === "demo" && (
          <div className="notice demo-notice">
            <strong>Demo mode is on.</strong> Copy uses a deterministic
            template; no AI image analysis is performed. Your input is rendered
            into a real, platform-sized video or image.
          </div>
        )}
        {unavailable && (
          <div className="notice error" role="alert">
            {UNAVAILABLE_JOB}
          </div>
        )}
        {configError && (
          <div className="notice error" role="alert">
            {configError}{" "}
            <button type="button" onClick={loadConfig}>
              Reconnect
            </button>
          </div>
        )}
        <div className="workspace">
          <CreateForm
            config={config}
            inputType={inputType}
            onInputTypeChange={setInputType}
            selectedFormat={selectedFormat}
            onFormatChange={(platform, format) =>
              setTarget({ platform, format })
            }
            busy={busy}
            submitting={submitting}
            error={error}
            onError={setError}
            onSubmit={create}
          />
          <ResultPanel
            job={job}
            formats={formats}
            resultFormat={resultFormat}
            selectedFormat={selectedFormat}
            inputType={inputType}
            retentionDays={retentionDays}
            pollError={pollError}
            retrying={submitting}
            onRetry={retry}
            onVariantCreated={openVariant}
          />
        </div>
        {job?.status === "completed" && content && (
          <CopyPanel
            job={job}
            content={content}
            platform={resultFormat?.platform}
            copied={copiedId === job.id}
            onCopied={() => setCopiedId(job.id)}
            onError={setError}
          />
        )}
        <RecentJobs
          activeId={jobID}
          refreshKey={`${job?.id ?? ""}:${job?.status ?? ""}`}
          labelFor={(platformKey, formatKey) =>
            formats.find(
              (item) =>
                item.platform === platformKey && item.format === formatKey,
            )?.label ?? `${platformKey} ${formatKey}`
          }
        />
        <footer>
          <span>Made for stories worth sharing.</span>
          <span>INSTAGRAM · TIKTOK · YOUTUBE · TEMPLATE-BASED RENDERING</span>
        </footer>
      </main>
    </div>
  );
}
