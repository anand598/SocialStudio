"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
type Format = { platform: string; format: string; label: string; width: number; height: number; aspect_ratio: string };
type Config = { formats: Format[]; generation_mode: "demo" | "ollama"; max_upload_size_mb: number };
type Analysis = { product_name: string | null; product_category: string; visible_attributes: string[]; confidence_or_limitations: string; facts_needing_user_confirmation: string[] };
type Content = { hook: string; short_description: string; benefits: string[]; caption: string; call_to_action: string; hashtags: string[]; disclaimer_or_assumptions: string };
type Job = { id: string; status: "queued" | "processing" | "completed" | "failed"; stage: string; generation_mode: string; error_message: string | null; product_analysis: Analysis | null; generated_content: Content | null };
const stages = [
  { key: "validating", label: "Prepare image" },
  { key: "analyzing", label: "Understand the product" },
  { key: "writing_copy", label: "Write the story" },
  { key: "rendering", label: "Render your Reel" },
  { key: "finalizing", label: "Check the result" },
];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, signal: AbortSignal.timeout(30000) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed. Check the input and try again.");
  return data as T;
}

export default function Home() {
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [imageURL, setImageURL] = useState("");
  const [brand, setBrand] = useState("");
  const [description, setDescription] = useState("");
  const [cta, setCta] = useState("Explore the collection");
  const [job, setJob] = useState<Job | null>(null);
  const [jobID, setJobID] = useState("");
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const busy = submitting || job?.status === "queued" || job?.status === "processing";
  const selectedFormat = config?.formats[0];

  const loadConfig = useCallback(() => {
    setConfigError("");
    request<Config>("/api/v1/config/platforms").then(setConfig)
      .catch(() => setConfigError("We couldn’t connect to the service. Check that the API is running, then reconnect."));
  }, []);
  useEffect(loadConfig, [loadConfig]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.hash.slice(1)).get("job");
    if (id && /^[0-9a-f-]{36}$/i.test(id)) setJobID(id);
  }, []);
  useEffect(() => {
    if (!file) { setImageURL(""); return; }
    const url = URL.createObjectURL(file);
    setImageURL(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    if (!jobID) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Job>(`/api/v1/generations/${jobID}`);
        if (cancelled) return;
        setJob(next); setPollError("");
        if (next.status === "completed" || next.status === "failed") return;
      } catch (err) {
        if (cancelled) return;
        setPollError(err instanceof Error ? err.message : "Connection interrupted. Reconnecting…");
      }
      timer = setTimeout(poll, 2500);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobID]);

  function selectFile(candidate?: File) {
    setError("");
    if (!candidate) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(candidate.type)) {
      setError("Choose a JPEG, PNG, or WebP image."); return;
    }
    if (candidate.size > (config?.max_upload_size_mb ?? 15) * 1024 * 1024) {
      setError(`Choose an image smaller than ${config?.max_upload_size_mb ?? 15} MB.`); return;
    }
    setFile(candidate);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !selectedFormat || busy) return;
    setSubmitting(true); setError("");
    const body = new FormData();
    body.set("file", file); body.set("platform", selectedFormat.platform); body.set("format", selectedFormat.format);
    body.set("brand_name", brand); body.set("brand_description", description); body.set("call_to_action", cta);
    try {
      const next = await request<Job>("/api/v1/generations", { method: "POST", body });
      setJob(next); setJobID(next.id);
      window.history.replaceState(null, "", `#job=${next.id}`);
    } catch (err) { setError(err instanceof Error ? err.message : "Upload failed. Try again."); }
    finally { setSubmitting(false); }
  }

  async function retry() {
    if (!job || submitting) return;
    setSubmitting(true); setError("");
    try {
      const next = await request<Job>(`/api/v1/generations/${job.id}/retry`, { method: "POST" });
      setJob(next);
      // Restart the polling effect for this same persisted job.
      setJobID(""); setTimeout(() => setJobID(next.id), 0);
    } catch (err) { setError(err instanceof Error ? err.message : "Retry failed."); }
    finally { setSubmitting(false); }
  }

  const content = job?.generated_content;
  const caption = content ? `${content.caption}\n\n${content.call_to_action}\n\n${content.hashtags.join(" ")}` : "";
  async function copyCaption() {
    try { await navigator.clipboard.writeText(caption); setCopied(true); }
    catch { setError("Clipboard is unavailable. Select the caption text or download it instead."); }
  }
  function downloadCaption() {
    const blob = new Blob([caption + "\n\n" + content?.disclaimer_or_assumptions], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = `caption-${job?.id}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const activeStage = stages.findIndex(stage => stage.key === job?.stage);

  return <div className="studio-shell">
    <header className="topbar">
      <a className="wordmark" href="/" aria-label="Social Studio home"><span className="mark">s</span> social studio<span className="wordmark-dot">.</span></a>
      <div className="topbar-right"><span className="connection-dot" />Your next creative starts here</div>
    </header>
    <main>
      <section className="intro">
        <div><div className="eyebrow">PRODUCT IN. STORY OUT.</div><h1>Make a little<br /><em>scroll-stopping</em> magic.</h1>
          <p>A product image, a few words, a fresh perspective.<br className="desktop-break" /> Create an Instagram Reel that puts your product first.</p></div>
        <div className="intro-note"><span>01 / THE CREATIVE STUDIO</span><p>AI-assisted storytelling.<br />Real, template-rendered video.<br />Made from your image.</p><div className="tiny-stars">✳ &nbsp; ✳ &nbsp; ✳</div></div>
      </section>
      {config?.generation_mode === "demo" && <div className="notice demo-notice"><strong>Demo mode is on.</strong> Copy uses a deterministic template; no AI image analysis is performed. Your uploaded image is rendered into a real MP4.</div>}
      {configError && <div className="notice error" role="alert">{configError} <button type="button" onClick={loadConfig}>Reconnect</button></div>}
      <div className="workspace">
        <form className="editor panel" onSubmit={submit}>
          <div className="panel-heading"><div><span className="step-number">01</span><h2>Set the scene</h2></div><span className="small-label">YOUR INPUT</span></div>
          <label className="field-label" htmlFor="product-image">Product image</label>
          <div className={`upload-zone ${dragging ? "dragging" : ""} ${imageURL ? "has-image" : ""}`}
            onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }}
            onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) selectFile(event.dataTransfer.files[0]); }}>
            {imageURL ? <><img src={imageURL} alt="Selected product" className="uploaded-image" /><button type="button" className="change-image" onClick={() => input.current?.click()} disabled={busy}>Change image</button></>
              : <><span className="upload-icon" aria-hidden="true">↥</span><p>Drop something worth sharing.</p><span>Drag an image here, or <button type="button" onClick={() => input.current?.click()} disabled={busy}>browse files</button></span><small>JPEG, PNG or WebP · Up to {config?.max_upload_size_mb ?? 15} MB</small></>}
            <input id="product-image" ref={input} type="file" className="sr-only" accept="image/jpeg,image/png,image/webp" disabled={busy}
              onChange={(event: ChangeEvent<HTMLInputElement>) => { selectFile(event.target.files?.[0]); event.target.value = ""; }} />
          </div>
          {file && <p className="filename">{file.name} <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span></p>}
          <div className="field-row"><div><label className="field-label" htmlFor="platform">Platform</label><select id="platform" value={selectedFormat?.platform ?? ""} disabled={!selectedFormat || busy} onChange={() => {}}><option value={selectedFormat?.platform ?? ""}>{selectedFormat ? "Instagram" : "Loading…"}</option></select></div>
            <div><label className="field-label" htmlFor="format">Format</label><select id="format" value={selectedFormat?.format ?? ""} disabled={!selectedFormat || busy} onChange={() => {}}><option value={selectedFormat?.format ?? ""}>{selectedFormat ? `Reel · ${selectedFormat.aspect_ratio}` : "Loading…"}</option></select></div></div>
          <div className="form-divider" />
          <div className="section-caption">MAKE IT YOURS <span>Optional</span></div>
          <label className="field-label" htmlFor="brand">Brand name</label><input id="brand" value={brand} onChange={e => setBrand(e.target.value)} maxLength={80} placeholder="e.g. Sunday Supply" disabled={busy} />
          <label className="field-label" htmlFor="description">Product context <span>Facts you can confirm</span></label><textarea id="description" value={description} onChange={e => setDescription(e.target.value)} maxLength={500} placeholder="Help the AI understand your product. Avoid unverified claims." rows={2} disabled={busy} />
          <label className="field-label" htmlFor="cta">Call to action</label><input id="cta" value={cta} onChange={e => setCta(e.target.value)} maxLength={100} placeholder="Explore the collection" disabled={busy} />
          {error && <p className="notice error" role="alert">{error}</p>}
          <button type="submit" className="primary-button" disabled={!file || !selectedFormat || busy}>{submitting ? "Uploading your image…" : busy ? "Your creative is in the making…" : <>Create my Reel <span aria-hidden="true">↗</span></>}</button>
          <p className="form-footnote">{selectedFormat ? `${selectedFormat.width} × ${selectedFormat.height} MP4` : "Instagram Reel"} · Silent video · Review before publishing</p>
        </form>
        <section className="preview-panel panel" aria-labelledby="preview-heading">
          <div className="panel-heading"><div><span className="step-number">02</span><h2 id="preview-heading">The spotlight</h2></div><span className="small-label">YOUR CREATIVE</span></div>
          <div className="preview-body">
            {job?.status === "completed" ? <div className="finished-preview"><video key={job.id} controls playsInline preload="metadata" poster={`${API}/api/v1/generations/${job.id}/thumbnail`} src={`${API}/api/v1/generations/${job.id}/preview`} aria-label="Generated Instagram Reel" /><span className="result-label">READY FOR YOUR CLOSE-UP</span></div>
              : <div className="mockup-stage"><div className="phone-frame"><div className="phone-top">social studio <span>•••</span></div><div className="phone-art"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><span className="asterisk">✳</span><div className="phone-copy">Small image.<br /><em>Big energy.</em></div><span className="phone-pill">YOUR NEXT REEL</span></div><div className="phone-bottom"><span>♡ &nbsp; ◇ &nbsp; ↗</span><span>▱</span></div></div><div className="floating-note">A fresh angle<br /><span>on your product.</span><b aria-hidden="true">↖</b></div></div>}
            <div className="generation-status" role="status" aria-live="polite">
              {!job && <><h3>A blank canvas. A world of possibility.</h3><p>Add your product image to get started.<br />Your finished Reel will appear right here.</p></>}
              {job?.status === "queued" && <><h3>{job.stage === "retry_wait" ? "Waiting to retry the AI service…" : "Your image is in the queue."}</h3><p>The worker will pick it up shortly. You can refresh this page safely.</p></>}
              {job?.status === "processing" && <><h3>{stages[activeStage]?.label ?? "Making your creative…"}</h3><p>Good stories take a moment. We’ll keep you posted.</p></>}
              {job?.status === "failed" && <><h3>Let’s give that another take.</h3><p>{job.error_message}</p><button className="secondary-button" type="button" onClick={retry} disabled={submitting}>Retry generation ↻</button></>}
              {job?.status === "completed" && <><h3>Your product, ready to play.</h3><p>{job.generation_mode === "demo" ? "Demo copy · Real template-rendered video" : "AI-assisted copy · Template-rendered video"}</p><a className="primary-button download" href={`${API}/api/v1/generations/${job.id}/download`}>Download Reel <span>↓</span></a></>}
              {pollError && <p className="error" role="alert">{pollError} Reconnecting automatically…</p>}
            </div>
            {(job?.status === "processing" || job?.status === "queued") && <ol className="stage-list">{stages.map((stage, index) => <li key={stage.key} className={index === activeStage ? "active" : index < activeStage ? "done" : ""}><span>{index < activeStage ? "✓" : index + 1}</span>{stage.label}</li>)}</ol>}
          </div>
        </section>
      </div>
      {job?.status === "completed" && content && <section className="copy-panel panel" aria-labelledby="copy-heading"><div className="panel-heading"><div><span className="step-number">03</span><h2 id="copy-heading">Words to go with it</h2></div><span className="small-label">YOUR CAPTION</span></div><div className="copy-grid"><div><label className="field-label" htmlFor="caption">Caption & hashtags</label><textarea id="caption" readOnly value={caption} rows={8} /><div className="copy-actions"><button type="button" className="secondary-button" onClick={copyCaption}>{copied ? "Copied ✓" : "Copy caption"}</button><button type="button" className="text-button" onClick={downloadCaption}>Download text ↓</button></div></div><div className="review-note"><h3>A quick check before you share.</h3><p>{content.disclaimer_or_assumptions}</p>{job.product_analysis && <><p>{job.product_analysis.confidence_or_limitations}</p>{job.product_analysis.facts_needing_user_confirmation.map((fact, index) => <p key={index}>• {fact}</p>)}</>}<p className="job-reference">Generation {job.id}</p></div></div></section>}
      <footer><span>Made for stories worth sharing.</span><span>INSTAGRAM REELS · TEMPLATE-BASED RENDERING</span></footer>
    </main>
  </div>;
}
