"use client";

import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
type InputType = "image" | "video" | "url";
type Format = {
  platform: string;
  platform_label: string;
  format: string;
  label: string;
  kind: "video" | "image";
  width: number;
  height: number;
  aspect_ratio: string;
  description: string;
};
type Config = {
  formats: Format[];
  input_types?: InputType[];
  generation_mode: "demo" | "ollama";
  max_upload_size_mb: number;
  max_video_upload_size_mb?: number;
  max_source_video_seconds?: number;
  max_music_upload_size_mb?: number;
  max_music_seconds?: number;
};
type Analysis = {
  product_name: string | null;
  product_category: string;
  visible_attributes: string[];
  confidence_or_limitations: string;
  facts_needing_user_confirmation: string[];
};
type Content = {
  title?: string;
  hook: string;
  short_description: string;
  benefits: string[];
  caption: string;
  call_to_action: string;
  hashtags: string[];
  disclaimer_or_assumptions: string;
};
type Job = {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  stage: string;
  input_type?: InputType;
  platform?: string;
  format?: string;
  output_kind?: "video" | "image";
  has_music?: boolean;
  post_text?: string | null;
  generation_mode: string;
  error_message: string | null;
  product_analysis: Analysis | null;
  generated_content: Content | null;
};
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const AUDIO_TYPES = [
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/x-m4a",
  "audio/m4a",
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/vnd.wave",
];
const VIDEO_TYPES = ["video/mp4", "video/quicktime", "video/webm"];
const inputTabs: { key: InputType; label: string; icon: string }[] = [
  { key: "image", label: "Image", icon: "▣" },
  { key: "video", label: "Video", icon: "▶" },
  { key: "url", label: "Product URL", icon: "↗" },
];

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

function isValidURL(value: string) {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    // The job-owner cookie must also reach a separately hosted API (NEXT_PUBLIC_API_URL).
    credentials: "include",
    signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(errorMessage(data?.detail), response.status);
  return data as T;
}

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

// The API answers 404 for missing jobs and for jobs created in another browser alike.
const UNAVAILABLE_JOB =
  "This result isn't available here. Results open only in the browser that created them — create a new one below.";

type ValidationIssue = { loc?: (string | number)[]; msg?: string };

// FastAPI returns a string for handled errors and a list for request validation errors.
function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const issues = (detail as ValidationIssue[])
      .slice(0, 3)
      .map((issue) => {
        const field = issue.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field} — ${issue.msg}` : issue.msg;
      })
      .filter(Boolean);
    if (issues.length)
      return `The server rejected the request: ${issues.join("; ")}.`;
  }
  return "The request could not be completed. Check the input and try again.";
}

export default function Home() {
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState("");
  const [inputType, setInputType] = useState<InputType>("image");
  const [file, setFile] = useState<File | null>(null);
  const [mediaURL, setMediaURL] = useState("");
  const [productURL, setProductURL] = useState("");
  const [platform, setPlatform] = useState("instagram");
  const [formatKey, setFormatKey] = useState("reel");
  const [brand, setBrand] = useState("");
  const [description, setDescription] = useState("");
  const [cta, setCta] = useState("Explore the collection");
  const [music, setMusic] = useState<File | null>(null);
  const musicInput = useRef<HTMLInputElement>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [jobID, setJobID] = useState("");
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const busy =
    submitting || job?.status === "queued" || job?.status === "processing";
  const formats = config?.formats ?? [];
  const platforms = formats.filter(
    (item, index) =>
      formats.findIndex((other) => other.platform === item.platform) === index,
  );
  const platformFormats = formats.filter((item) => item.platform === platform);
  const selectedFormat =
    platformFormats.find((item) => item.format === formatKey) ??
    platformFormats[0];
  const jobFormat = formats.find(
    (item) => item.platform === job?.platform && item.format === job?.format,
  );
  const resultFormat = jobFormat ?? selectedFormat;
  const resultKind = job?.output_kind ?? resultFormat?.kind ?? "video";
  const stages = stagesFor(job?.input_type ?? inputType, resultKind);
  const imageLimit = config?.max_upload_size_mb ?? 15;
  const videoLimit = config?.max_video_upload_size_mb ?? 100;
  const musicLimit = config?.max_music_upload_size_mb ?? 20;
  // Music only applies to video outputs; it is kept if the user switches back to a video format.
  const musicApplies = selectedFormat?.kind === "video";
  const withMusic = musicApplies && music !== null;
  const hasInput = inputType === "url" ? isValidURL(productURL) : file !== null;

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
  useEffect(() => {
    // The #job= fragment is the shareable result link; follow it on load and on
    // back/forward or pasted-link navigation, which change the hash without a reload.
    const restore = () => {
      const id = new URLSearchParams(window.location.hash.slice(1)).get("job");
      if (id && /^[0-9a-f-]{36}$/i.test(id)) {
        setJobID(id);
      } else {
        // No job in the URL (e.g. Back to the start page): show the empty studio.
        setJobID("");
        setJob(null);
      }
    };
    restore();
    window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
  }, []);
  useEffect(() => {
    if (!file) {
      setMediaURL("");
      return;
    }
    const url = URL.createObjectURL(file);
    setMediaURL(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    setUnavailable(false);
    if (!jobID) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Job>(`/api/v1/generations/${jobID}`);
        if (cancelled) return;
        setJob(next);
        setPollError("");
        if (next.status === "completed" || next.status === "failed") return;
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setJob(null);
          setPollError("");
          setUnavailable(true);
          return;
        }
        setPollError(
          err instanceof Error
            ? err.message
            : "Connection interrupted. Reconnecting…",
        );
      }
      timer = setTimeout(poll, 2500);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobID]);

  function chooseInput(next: InputType) {
    if (busy || next === inputType) return;
    setInputType(next);
    setFile(null);
    setError("");
  }

  function choosePlatform(next: string) {
    setPlatform(next);
    setFormatKey(formats.find((item) => item.platform === next)?.format ?? "");
  }

  function selectFile(candidate?: File) {
    setError("");
    if (!candidate) return;
    const video = inputType === "video";
    if (!(video ? VIDEO_TYPES : IMAGE_TYPES).includes(candidate.type)) {
      setError(
        video
          ? "Choose an MP4, MOV, or WebM video."
          : "Choose a JPEG, PNG, or WebP image.",
      );
      return;
    }
    const limit = video ? videoLimit : imageLimit;
    if (candidate.size > limit * 1024 * 1024) {
      setError(`Choose a ${inputType} smaller than ${limit} MB.`);
      return;
    }
    setFile(candidate);
  }

  function selectMusic(candidate?: File) {
    setError("");
    if (!candidate) return;
    if (!AUDIO_TYPES.includes(candidate.type)) {
      setError("Choose an MP3, M4A, or WAV track.");
      return;
    }
    if (candidate.size > musicLimit * 1024 * 1024) {
      setError(`Choose a music track smaller than ${musicLimit} MB.`);
      return;
    }
    setMusic(candidate);
  }

  function removeMusic() {
    setMusic(null);
    if (musicInput.current) musicInput.current.value = "";
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!hasInput || !selectedFormat || busy) return;
    setSubmitting(true);
    setError("");
    const body = new FormData();
    body.set("input_type", inputType);
    if (inputType === "url") body.set("source_url", productURL.trim());
    else if (file) body.set("file", file);
    body.set("platform", selectedFormat.platform);
    body.set("format", selectedFormat.format);
    body.set("brand_name", brand);
    body.set("brand_description", description);
    body.set("call_to_action", cta);
    if (withMusic && music) body.set("music", music);
    try {
      const next = await request<Job>("/api/v1/generations", {
        method: "POST",
        body,
      });
      setJob(next);
      setJobID(next.id);
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
      setJob(next);
      // Restart the polling effect for this same persisted job.
      setJobID("");
      setTimeout(() => setJobID(next.id), 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const content = job?.generated_content;
  const caption = content
    ? (job?.post_text ??
      `${content.caption}\n\n${content.call_to_action}\n\n${content.hashtags.join(" ")}`)
    : "";
  const resultLabel = resultFormat?.label ?? "creative";
  async function copyCaption() {
    try {
      await navigator.clipboard.writeText(caption);
      setCopied(true);
    } catch {
      setError(
        "Clipboard is unavailable. Select the caption text or download it instead.",
      );
    }
  }
  function downloadCaption() {
    const blob = new Blob(
      [caption + "\n\n" + content?.disclaimer_or_assumptions],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `caption-${job?.id}.txt`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const activeStage = Math.max(
    stages.findIndex((stage) => stage.key === job?.stage),
    job?.stage === "validating" ? 0 : -1,
  );
  const assetURL = job ? `${API}/api/v1/generations/${job.id}` : "";

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
          <form className="editor panel" onSubmit={submit}>
            <div className="panel-heading">
              <div>
                <span className="step-number">01</span>
                <h2>Set the scene</h2>
              </div>
              <span className="small-label">YOUR INPUT</span>
            </div>
            <div className="input-tabs" role="tablist" aria-label="Input type">
              {inputTabs.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={inputType === tab.key}
                  className={inputType === tab.key ? "active" : ""}
                  onClick={() => chooseInput(tab.key)}
                  disabled={busy}
                >
                  <span aria-hidden="true">{tab.icon}</span> {tab.label}
                </button>
              ))}
            </div>
            {inputType === "url" ? (
              <>
                <label className="field-label" htmlFor="product-url">
                  Product page URL{" "}
                  <span>Public product page or image link</span>
                </label>
                <input
                  id="product-url"
                  type="url"
                  inputMode="url"
                  value={productURL}
                  onChange={(e) => setProductURL(e.target.value)}
                  maxLength={2048}
                  placeholder="https://shop.example.com/products/desk-lamp"
                  disabled={busy}
                  aria-invalid={productURL !== "" && !isValidURL(productURL)}
                />
                <p className="field-hint">
                  {productURL !== "" && !isValidURL(productURL)
                    ? "Enter a full http:// or https:// address."
                    : "We read the page’s product image, title and description. Some stores block automated access — upload the image instead if so."}
                </p>
              </>
            ) : (
              <>
                <label className="field-label" htmlFor="product-file">
                  {inputType === "video" ? "Product video" : "Product image"}
                </label>
                <div
                  className={`upload-zone ${dragging ? "dragging" : ""} ${mediaURL ? "has-image" : ""}`}
                  onDragOver={(event) => {
                    event.preventDefault();
                    if (!busy) setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    if (!busy) selectFile(event.dataTransfer.files[0]);
                  }}
                >
                  {mediaURL ? (
                    <>
                      {inputType === "video" ? (
                        <video
                          src={mediaURL}
                          className="uploaded-image"
                          muted
                          playsInline
                          controls
                          aria-label="Selected product video"
                        />
                      ) : (
                        <img
                          src={mediaURL}
                          alt="Selected product"
                          className="uploaded-image"
                        />
                      )}
                      <button
                        type="button"
                        className="change-image"
                        onClick={() => input.current?.click()}
                        disabled={busy}
                      >
                        Change {inputType}
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="upload-icon" aria-hidden="true">
                        ↥
                      </span>
                      <p>Drop something worth sharing.</p>
                      <span>
                        Drag {inputType === "video" ? "a video" : "an image"}{" "}
                        here, or{" "}
                        <button
                          type="button"
                          onClick={() => input.current?.click()}
                          disabled={busy}
                        >
                          browse files
                        </button>
                      </span>
                      <small>
                        {inputType === "video"
                          ? `MP4, MOV or WebM · Up to ${videoLimit} MB · ${config?.max_source_video_seconds ?? 180} s max`
                          : `JPEG, PNG or WebP · Up to ${imageLimit} MB`}
                      </small>
                    </>
                  )}
                  <input
                    id="product-file"
                    ref={input}
                    type="file"
                    className="sr-only"
                    accept={(inputType === "video"
                      ? VIDEO_TYPES
                      : IMAGE_TYPES
                    ).join(",")}
                    disabled={busy}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => {
                      selectFile(event.target.files?.[0]);
                      event.target.value = "";
                    }}
                  />
                </div>
                {file && (
                  <p className="filename">
                    {file.name}{" "}
                    <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                  </p>
                )}
              </>
            )}
            <div className="field-row">
              <div>
                <label className="field-label" htmlFor="platform">
                  Platform
                </label>
                <select
                  id="platform"
                  value={selectedFormat?.platform ?? ""}
                  disabled={!selectedFormat || busy}
                  onChange={(e) => choosePlatform(e.target.value)}
                >
                  {platforms.length === 0 && <option value="">Loading…</option>}
                  {platforms.map((item) => (
                    <option key={item.platform} value={item.platform}>
                      {item.platform_label ?? item.platform}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="field-label" htmlFor="format">
                  Format
                </label>
                <select
                  id="format"
                  value={selectedFormat?.format ?? ""}
                  disabled={!selectedFormat || busy}
                  onChange={(e) => setFormatKey(e.target.value)}
                >
                  {platformFormats.length === 0 && (
                    <option value="">Loading…</option>
                  )}
                  {platformFormats.map((item) => (
                    <option key={item.format} value={item.format}>
                      {item.label.replace(`${item.platform_label} `, "")} ·{" "}
                      {item.aspect_ratio}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {selectedFormat && (
              <div className="format-card" aria-live="polite">
                <span
                  className="format-shape"
                  style={{
                    aspectRatio: `${selectedFormat.width} / ${selectedFormat.height}`,
                  }}
                  aria-hidden="true"
                />
                <div>
                  <strong>
                    {selectedFormat.width} × {selectedFormat.height} ·{" "}
                    {selectedFormat.kind === "video"
                      ? "MP4 video"
                      : "JPEG image"}
                  </strong>
                  <span>{selectedFormat.description}</span>
                </div>
              </div>
            )}
            <div className="form-divider" />
            <div className="section-caption">
              MAKE IT YOURS <span>Optional</span>
            </div>
            <label className="field-label" htmlFor="brand">
              Brand name
            </label>
            <input
              id="brand"
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
              maxLength={80}
              placeholder="e.g. Sunday Supply"
              disabled={busy}
            />
            <label className="field-label" htmlFor="description">
              Product context <span>Facts you can confirm</span>
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              placeholder="Help the AI understand your product. Avoid unverified claims."
              rows={2}
              disabled={busy}
            />
            <label className="field-label" htmlFor="cta">
              Call to action
            </label>
            <input
              id="cta"
              value={cta}
              onChange={(e) => setCta(e.target.value)}
              maxLength={100}
              placeholder="Explore the collection"
              disabled={busy}
            />
            {musicApplies && (
              <>
                <label className="field-label" htmlFor="music">
                  Background music <span>Optional · MP3, M4A, WAV</span>
                </label>
                <div className="music-field">
                  <input
                    id="music"
                    ref={musicInput}
                    type="file"
                    accept=".mp3,.m4a,.wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/wav"
                    onChange={(e) => selectMusic(e.target.files?.[0])}
                    disabled={busy}
                    className="music-input"
                  />
                  {/* The native input stays focusable for keyboards and screen readers; this pill is its visible face. */}
                  <label
                    htmlFor="music"
                    className="music-button"
                    aria-hidden="true"
                  >
                    {music ? "Change track" : "♪ Add a track"}
                  </label>
                  {music && (
                    <span className="music-chosen">
                      <span>{music.name}</span>
                      <button
                        type="button"
                        onClick={removeMusic}
                        disabled={busy}
                        aria-label="Remove music"
                      >
                        Remove
                      </button>
                    </span>
                  )}
                </div>
                <p className="field-hint">
                  Use a track you have the rights to.{" "}
                  {inputType === "video"
                    ? "It plays quietly under your clip's own sound."
                    : "It is trimmed to the video and faded in and out."}
                </p>
              </>
            )}
            {error && (
              <p className="notice error" role="alert">
                {error}
              </p>
            )}
            <button
              type="submit"
              className="primary-button"
              disabled={!hasInput || !selectedFormat || busy}
            >
              {submitting ? (
                inputType === "url" ? (
                  "Checking the link…"
                ) : (
                  `Uploading your ${inputType}…`
                )
              ) : busy ? (
                "Your creative is in the making…"
              ) : (
                <>
                  Create my {selectedFormat?.label ?? "creative"}{" "}
                  <span aria-hidden="true">↗</span>
                </>
              )}
            </button>
            <p className="form-footnote">
              {inputType === "video" && selectedFormat?.kind === "video"
                ? `Your clip, reframed · Original audio kept${withMusic ? " · With your music" : ""}`
                : selectedFormat?.kind === "image"
                  ? "Designed still"
                  : `Animated promo · ${withMusic ? "With your music" : "Silent video"}`}{" "}
              · Review before publishing
            </p>
          </form>
          <section
            className="preview-panel panel"
            aria-labelledby="preview-heading"
          >
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
                  {resultKind === "image" ? (
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
                </div>
              ) : (
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
                        {(
                          selectedFormat?.platform_label ?? "post"
                        ).toUpperCase()}{" "}
                        {selectedFormat?.kind === "image" ? "POST" : "VIDEO"}
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
              )}
              <div
                className="generation-status"
                role="status"
                aria-live="polite"
              >
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
                      The worker will pick it up shortly. You can refresh this
                      page safely.
                    </p>
                  </>
                )}
                {job?.status === "processing" && (
                  <>
                    <h3>
                      {stages[activeStage]?.label ?? "Making your creative…"}
                    </h3>
                    <p>Good stories take a moment. We’ll keep you posted.</p>
                  </>
                )}
                {job?.status === "failed" && (
                  <>
                    <h3>Let’s give that another take.</h3>
                    <p>{job.error_message}</p>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={retry}
                      disabled={submitting}
                    >
                      Retry generation ↻
                    </button>
                  </>
                )}
                {job?.status === "completed" && (
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
                  </>
                )}
                {pollError && (
                  <p className="error" role="alert">
                    {pollError} Reconnecting automatically…
                  </p>
                )}
              </div>
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
        </div>
        {job?.status === "completed" && content && (
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
                  {resultFormat?.platform === "youtube"
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
        )}
        <footer>
          <span>Made for stories worth sharing.</span>
          <span>INSTAGRAM · TIKTOK · YOUTUBE · TEMPLATE-BASED RENDERING</span>
        </footer>
      </main>
    </div>
  );
}
