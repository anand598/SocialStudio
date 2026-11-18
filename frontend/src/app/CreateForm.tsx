"use client";

import { FormEvent, useState } from "react";
import {
  uniquePlatforms,
  type Config,
  type Format,
  type InputType,
} from "../lib/types";
import BrandKitFields, {
  type BrandKit,
  INITIAL_BRAND_KIT,
} from "./BrandKitFields";
import ProductUpload from "./ProductUpload";

const inputTabs: { key: InputType; label: string; icon: string }[] = [
  { key: "image", label: "Image", icon: "▣" },
  { key: "video", label: "Video", icon: "▶" },
  { key: "url", label: "Product URL", icon: "↗" },
];

function isValidURL(value: string) {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * "01 Set the scene": the product source, the target format and the optional brand kit.
 * It owns the draft and builds the request body; sending it is up to `onSubmit`.
 */
export default function CreateForm({
  config,
  inputType,
  onInputTypeChange,
  selectedFormat,
  onFormatChange,
  busy,
  submitting,
  error,
  onError,
  onSubmit,
}: {
  config: Config | null;
  // The input type and format are lifted: the result panel previews them before a job exists.
  inputType: InputType;
  onInputTypeChange: (next: InputType) => void;
  selectedFormat: Format | undefined;
  onFormatChange: (platform: string, format: string) => void;
  busy: boolean;
  submitting: boolean;
  error: string;
  // Called with "" to clear a previous message.
  onError: (message: string) => void;
  onSubmit: (body: FormData) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [productURL, setProductURL] = useState("");
  const [kit, setKit] = useState<BrandKit>(INITIAL_BRAND_KIT);
  const formats = config?.formats ?? [];
  const platforms = uniquePlatforms(formats);
  const platformFormats = formats.filter(
    (item) => item.platform === selectedFormat?.platform,
  );
  const imageLimit = config?.max_upload_size_mb ?? 15;
  const videoLimit = config?.max_video_upload_size_mb ?? 100;
  const musicLimit = config?.max_music_upload_size_mb ?? 20;
  const logoLimit = config?.max_logo_upload_size_mb ?? 2;
  // Music only applies to video outputs; it is kept if the user switches back to a video format.
  const musicApplies = selectedFormat?.kind === "video";
  const withMusic = musicApplies && kit.music !== null;
  const hasInput = inputType === "url" ? isValidURL(productURL) : file !== null;

  function chooseInput(next: InputType) {
    if (busy || next === inputType) return;
    onInputTypeChange(next);
    setFile(null);
    onError("");
  }

  function choosePlatform(next: string) {
    onFormatChange(
      next,
      formats.find((item) => item.platform === next)?.format ?? "",
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!hasInput || !selectedFormat || busy) return;
    const body = new FormData();
    body.set("input_type", inputType);
    if (inputType === "url") body.set("source_url", productURL.trim());
    else if (file) body.set("file", file);
    body.set("platform", selectedFormat.platform);
    body.set("format", selectedFormat.format);
    body.set("brand_name", kit.brand);
    body.set("brand_description", kit.description);
    body.set("call_to_action", kit.cta);
    if (withMusic && kit.music) body.set("music", kit.music);
    if (kit.brandColor) body.set("brand_color", kit.brandColor.toUpperCase());
    if (kit.logo) body.set("logo", kit.logo);
    onSubmit(body);
  }

  return (
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
            Product page URL <span>Public product page or image link</span>
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
        <ProductUpload
          kind={inputType}
          file={file}
          limitMB={inputType === "video" ? videoLimit : imageLimit}
          maxVideoSeconds={config?.max_source_video_seconds ?? 180}
          busy={busy}
          onChange={setFile}
          onError={onError}
        />
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
            onChange={(e) =>
              selectedFormat &&
              onFormatChange(selectedFormat.platform, e.target.value)
            }
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
              {selectedFormat.kind === "video" ? "MP4 video" : "JPEG image"}
            </strong>
            <span>{selectedFormat.description}</span>
          </div>
        </div>
      )}
      <div className="form-divider" />
      <BrandKitFields
        kit={kit}
        onChange={(patch) => setKit((current) => ({ ...current, ...patch }))}
        inputType={inputType}
        musicApplies={musicApplies}
        logoLimit={logoLimit}
        musicLimit={musicLimit}
        busy={busy}
        onError={onError}
      />
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
  );
}
