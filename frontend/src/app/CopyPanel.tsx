"use client";

import type { Content, Job } from "../lib/types";

/** "03 Words to go with it": the finished job's caption, with copy and download. */
export default function CopyPanel({
  job,
  content,
  platform,
  copied,
  onCopied,
  onError,
}: {
  job: Job;
  content: Content;
  platform: string | undefined;
  copied: boolean;
  onCopied: () => void;
  onError: (message: string) => void;
}) {
  const caption =
    job.post_text ??
    `${content.caption}\n\n${content.call_to_action}\n\n${content.hashtags.join(" ")}`;

  async function copyCaption() {
    try {
      await navigator.clipboard.writeText(caption);
      onCopied();
    } catch {
      onError(
        "Clipboard is unavailable. Select the caption text or download it instead.",
      );
    }
  }

  function downloadCaption() {
    const blob = new Blob(
      [caption + "\n\n" + content.disclaimer_or_assumptions],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `caption-${job.id}.txt`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="copy-panel panel" aria-labelledby="copy-heading">
      <div className="panel-heading">
        <div>
          <span className="step-number">03</span>
          <h2 id="copy-heading">Words to go with it</h2>
        </div>
        <span className="small-label">YOUR CAPTION</span>
      </div>
      <div className="copy-grid">
        <div>
          <label className="field-label" htmlFor="caption">
            {platform === "youtube"
              ? "Title, description & hashtags"
              : "Caption & hashtags"}
          </label>
          <textarea id="caption" readOnly value={caption} rows={8} />
          <div className="copy-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={copyCaption}
            >
              {copied ? "Copied ✓" : "Copy caption"}
            </button>
            <button
              type="button"
              className="text-button"
              onClick={downloadCaption}
            >
              Download text ↓
            </button>
          </div>
        </div>
        <div className="review-note">
          <h3>A quick check before you share.</h3>
          <p>{content.disclaimer_or_assumptions}</p>
          {job.product_analysis && (
            <>
              <p>{job.product_analysis.confidence_or_limitations}</p>
              {job.product_analysis.facts_needing_user_confirmation.map(
                (fact, index) => (
                  <p key={index}>• {fact}</p>
                ),
              )}
            </>
          )}
          <p className="job-reference">Generation {job.id}</p>
        </div>
      </div>
    </section>
  );
}
