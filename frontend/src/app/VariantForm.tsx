"use client";

import { FormEvent, useState } from "react";
import { request } from "../lib/api";
import type { Format, Job } from "../lib/types";

/**
 * State for "Make another version" of the open job. Call it from a component that stays
 * mounted across jobs: the choice, the pending request and its error are each remembered
 * per job, so they never follow the user to another job.
 */
export function useVariantRequest(
  job: Job | null,
  formats: Format[],
  // The new version exists; `from` is the job it was made from.
  onCreated: (from: string, next: Job) => void,
) {
  // The "another version" choice, remembered per job; otherwise it follows the open job.
  const [choice, setChoice] = useState<{
    jobId: string;
    platform: string;
    format: string;
  } | null>(null);
  const [sendingFrom, setSendingFrom] = useState("");
  const [errorFor, setErrorFor] = useState<{
    jobId: string;
    message: string;
  } | null>(null);
  const sending = !!job && sendingFrom === job.id;
  const error = errorFor && errorFor.jobId === job?.id ? errorFor.message : "";
  const platform =
    choice && choice.jobId === job?.id
      ? choice.platform
      : (job?.platform ?? "");
  const platformFormats = formats.filter((item) => item.platform === platform);
  const target =
    platformFormats.find(
      (item) =>
        item.format ===
        (choice && choice.jobId === job?.id ? choice.format : job?.format),
    ) ?? platformFormats[0];

  function choose(platformKey: string, formatKey?: string) {
    if (!job) return;
    setErrorFor(null);
    setChoice({
      jobId: job.id,
      platform: platformKey,
      format:
        formatKey ??
        formats.find((item) => item.platform === platformKey)?.format ??
        "",
    });
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!job || !target || sending) return;
    const from = job.id;
    setSendingFrom(from);
    setErrorFor(null);
    try {
      const next = await request<Job>(
        `/api/v1/generations/${job.id}/variants`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            platform: target.platform,
            format: target.format,
          }),
        },
      );
      onCreated(from, next);
    } catch (err) {
      setErrorFor({
        jobId: from,
        message:
          err instanceof Error
            ? err.message
            : "We couldn’t start a new version. Try again.",
      });
    } finally {
      setSendingFrom((current) => (current === from ? "" : current));
    }
  }

  return { target, platformFormats, sending, error, choose, create };
}

export type VariantRequest = ReturnType<typeof useVariantRequest>;

/** The "Make another version" form under a finished result. */
export default function VariantForm({
  variant,
  platforms,
  hasMusic,
}: {
  variant: VariantRequest;
  platforms: Format[];
  hasMusic: boolean;
}) {
  const { target, platformFormats, sending, error, choose, create } = variant;
  // No format to offer (e.g. the config is still loading).
  if (!target) return null;
  return (
    <form
      className="variant-form"
      onSubmit={create}
      aria-labelledby="variant-heading"
    >
      <h3 id="variant-heading">Make another version</h3>
      <div className="field-row">
        <div>
          <label className="field-label" htmlFor="variant-platform">
            Platform <span className="sr-only">for the new version</span>
          </label>
          <select
            id="variant-platform"
            value={target.platform}
            disabled={sending}
            onChange={(e) => choose(e.target.value)}
          >
            {platforms.map((item) => (
              <option key={item.platform} value={item.platform}>
                {item.platform_label ?? item.platform}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="variant-format">
            Format <span className="sr-only">for the new version</span>
          </label>
          <select
            id="variant-format"
            value={target.format}
            disabled={sending}
            onChange={(e) => choose(target.platform, e.target.value)}
          >
            {platformFormats.map((item) => (
              <option key={item.format} value={item.format}>
                {item.label.replace(`${item.platform_label} `, "")} ·{" "}
                {item.aspect_ratio}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="field-hint">
        Reuses the same upload with fresh copy.
        {hasMusic && target.kind === "image"
          ? " Your music is left out — images have no sound."
          : ""}
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="secondary-button" disabled={sending}>
        {sending
          ? "Creating your new version…"
          : `Create a new ${target.label} version`}
      </button>
    </form>
  );
}
