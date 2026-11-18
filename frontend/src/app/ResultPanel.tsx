"use client";

import { API } from "../lib/api";
import {
  uniquePlatforms,
  type Format,
  type InputType,
  type Job,
} from "../lib/types";
import VariantForm, { useVariantRequest } from "./VariantForm";

function stagesFor(input: InputType, kind: "video" | "image") {
  return [
    input === "url"
      ? { key: "fetching", label: "Read the product page" }
      : {
          key: "validating",
          label: input === "video" ? "Prepare video" : "Prepare image",
        },
    {
      key: "analyzing",
      label: input === "video" ? "Watch the video" : "Understand the product",
    },
    { key: "writing_copy", label: "Write the story" },
    {
      key: "rendering",
      label: kind === "image" ? "Design your post" : "Render your video",
    },
    { key: "finalizing", label: "Check the result" },
  ];
}

function days(count: number) {
  return `${count} ${count === 1 ? "day" : "days"}`;
}

// Placeholder art until the open job has finished, labelled with the chosen format.
function PhoneMockup({ format }: { format: Format | undefined }) {
  return (
    <div className="mockup-stage">
      <div className="phone-frame">
        <div className="phone-top">
          social studio <span>•••</span>
        </div>
        <div className="phone-art">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <span className="asterisk">✳</span>
          <div className="phone-copy">
            Small image.
            <br />
            <em>Big energy.</em>
          </div>
          <span className="phone-pill">
            YOUR NEXT{" "}
            {(format?.platform_label ?? "post").toUpperCase()}{" "}
            {format?.kind === "image" ? "POST" : "VIDEO"}
          </span>
        </div>
        <div className="phone-bottom">
          <span>♡ &nbsp; ◇ &nbsp; ↗</span>
          <span>▱</span>
        </div>
      </div>
      <div className="floating-note">
        A fresh angle
        <br />
        <span>on your product.</span>
        <b aria-hidden="true">↖</b>
      </div>
    </div>
  );
}

/**
 * "02 The spotlight": the open job's progress, its finished preview and download (or the
 * failed / expired state) and "Make another version"; a mock-up until a job has finished.
 */
export default function ResultPanel({
  job,
  formats,
  resultFormat,
  selectedFormat,
  inputType,
  retentionDays,
  pollError,
  retrying,
  onRetry,
  onVariantCreated,
}: {
  job: Job | null;
  formats: Format[];
  // The open job's format, or the form's choice while there is none.
  resultFormat: Format | undefined;
  selectedFormat: Format | undefined;
  // The form's input type; used for the stage names when the job does not say.
  inputType: InputType;
  retentionDays: number;
  pollError: string;
  retrying: boolean;
  onRetry: () => void;
  onVariantCreated: (from: string, next: Job) => void;
}) {
  const variant = useVariantRequest(job, formats, onVariantCreated);
  const resultKind = job?.output_kind ?? resultFormat?.kind ?? "video";
  const resultLabel = resultFormat?.label ?? "creative";
  const stages = stagesFor(job?.input_type ?? inputType, resultKind);
  const activeStage = Math.max(
    stages.findIndex((stage) => stage.key === job?.stage),
    job?.stage === "validating" ? 0 : -1,
  );
  // Expired jobs keep their text, but their preview, download, retry and new versions are gone.
  const expired = job?.expired === true;
  const expiredNote = [
    `Files are deleted${retentionDays ? ` after ${days(retentionDays)}` : ""} to protect your media.`,
    // Only finished jobs show the caption panel.
    job?.status === "completed" && job.generated_content
      ? "The caption is still below — create a new one any time."
      : "Create a new one any time.",
  ].join(" ");
  const assetURL = job ? `${API}/api/v1/generations/${job.id}` : "";

  return (
    <section className="preview-panel panel" aria-labelledby="preview-heading">
      <div className="panel-heading">
        <div>
          <span className="step-number">02</span>
          <h2 id="preview-heading">The spotlight</h2>
        </div>
        <span className="small-label">YOUR CREATIVE</span>
      </div>
      <div className="preview-body">
        {job?.status === "completed" ? (
          <div
            className="finished-preview"
            style={{
              ["--preview-ratio" as string]: resultFormat
                ? `${resultFormat.width} / ${resultFormat.height}`
                : "9 / 16",
              ["--preview-width" as string]:
                resultFormat && resultFormat.width > resultFormat.height
                  ? "100%"
                  : resultFormat?.width === resultFormat?.height
                    ? "360px"
                    : "290px",
            }}
          >
            {expired ? (
              <div className="expired-frame" aria-hidden="true">
                <span>✳</span>
                MEDIA DELETED
              </div>
            ) : resultKind === "image" ? (
              <img
                key={job.id}
                src={`${assetURL}/preview`}
                alt={`Generated ${resultLabel}`}
              />
            ) : (
              <video
                key={job.id}
                controls
                playsInline
                preload="metadata"
                poster={`${assetURL}/thumbnail`}
                src={`${assetURL}/preview`}
                aria-label={`Generated ${resultLabel}`}
              />
            )}
            <span className="result-label">
              {resultFormat
                ? `${resultFormat.label.toUpperCase()} · ${resultFormat.width} × ${resultFormat.height}`
                : "READY FOR YOUR CLOSE-UP"}
            </span>
            {(job.variant ?? 1) > 1 && (
              <span className="version-tag">Version {job.variant}</span>
            )}
          </div>
        ) : (
          <PhoneMockup format={selectedFormat} />
        )}
        <div className="generation-status" role="status" aria-live="polite">
          {!job && (
            <>
              <h3>A blank canvas. A world of possibility.</h3>
              <p>
                Add a product image, video or link to get started.
                <br />
                Your finished creative will appear right here.
              </p>
            </>
          )}
          {job?.status === "queued" && (
            <>
              <h3>
                {job.stage === "retry_wait"
                  ? "Waiting to retry the AI service…"
                  : "Your request is in the queue."}
              </h3>
              <p>
                The worker will pick it up shortly. You can refresh this page
                safely.
              </p>
            </>
          )}
          {job?.status === "processing" && (
            <>
              <h3>{stages[activeStage]?.label ?? "Making your creative…"}</h3>
              <p>Good stories take a moment. We’ll keep you posted.</p>
            </>
          )}
          {expired && (
            <>
              <h3>This result has expired</h3>
              <p>{expiredNote}</p>
            </>
          )}
          {job?.status === "failed" && !expired && (
            <>
              <h3>Let’s give that another take.</h3>
              <p>{job.error_message}</p>
              <button
                className="secondary-button"
                type="button"
                onClick={onRetry}
                disabled={retrying}
              >
                Retry generation ↻
              </button>
            </>
          )}
          {job?.status === "completed" && !expired && (
            <>
              <h3>
                {resultKind === "image"
                  ? "Your product, ready to post."
                  : "Your product, ready to play."}
              </h3>
              <p>
                {job.generation_mode === "demo"
                  ? "Demo copy"
                  : "AI-assisted copy"}{" "}
                · Real{" "}
                {resultKind === "image"
                  ? "rendered image"
                  : job.input_type === "video"
                    ? "edit of your video"
                    : "promo video"}
                {job.has_music ? " · with your music" : ""}
              </p>
              <a
                className="primary-button download"
                href={`${assetURL}/download`}
              >
                Download {resultLabel} <span>↓</span>
              </a>
              {retentionDays > 0 && (
                <p className="retention-note">
                  Kept for {days(retentionDays)}
                </p>
              )}
            </>
          )}
          {pollError && (
            <p className="error" role="alert">
              {pollError} Reconnecting automatically…
            </p>
          )}
        </div>
        {job?.status === "completed" && !expired && (
          <VariantForm
            variant={variant}
            platforms={uniquePlatforms(formats)}
            hasMusic={!!job.has_music}
          />
        )}
        {(job?.status === "processing" || job?.status === "queued") && (
          <ol className="stage-list">
            {stages.map((stage, index) => (
              <li
                key={stage.key}
                className={
                  index === activeStage
                    ? "active"
                    : index < activeStage
                      ? "done"
                      : ""
                }
              >
                <span>{index < activeStage ? "✓" : index + 1}</span>
                {stage.label}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
