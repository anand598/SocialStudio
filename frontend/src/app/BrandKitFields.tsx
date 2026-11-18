"use client";

import { useRef } from "react";
import type { InputType } from "../lib/types";
import { AUDIO_TYPES, IMAGE_TYPES } from "../lib/uploads";

export type BrandKit = {
  brand: string;
  description: string;
  cta: string;
  // "" means no brand colour: the palette then comes from the product photo.
  brandColor: string;
  logo: File | null;
  music: File | null;
};

export const INITIAL_BRAND_KIT: BrandKit = {
  brand: "",
  description: "",
  cta: "Explore the collection",
  brandColor: "",
  logo: null,
  music: null,
};

/** The optional "Make it yours" fields: brand name, context, CTA, colour, logo and music. */
export default function BrandKitFields({
  kit,
  onChange,
  inputType,
  musicApplies,
  logoLimit,
  musicLimit,
  busy,
  onError,
}: {
  kit: BrandKit;
  onChange: (patch: Partial<BrandKit>) => void;
  inputType: InputType;
  // Music only applies to video outputs.
  musicApplies: boolean;
  logoLimit: number;
  musicLimit: number;
  busy: boolean;
  // Called with "" to clear a previous message.
  onError: (message: string) => void;
}) {
  const { brand, description, cta, brandColor, logo, music } = kit;
  const musicInput = useRef<HTMLInputElement>(null);
  const logoInput = useRef<HTMLInputElement>(null);

  function selectMusic(candidate?: File) {
    onError("");
    if (!candidate) return;
    if (!AUDIO_TYPES.includes(candidate.type)) {
      onError("Choose an MP3, M4A, or WAV track.");
      return;
    }
    if (candidate.size > musicLimit * 1024 * 1024) {
      onError(`Choose a music track smaller than ${musicLimit} MB.`);
      return;
    }
    onChange({ music: candidate });
  }

  function selectLogo(candidate?: File) {
    onError("");
    if (!candidate) return;
    if (!IMAGE_TYPES.includes(candidate.type)) {
      onError("Choose a PNG, JPEG, or WebP logo.");
      return;
    }
    if (candidate.size > logoLimit * 1024 * 1024) {
      onError(`Choose a logo smaller than ${logoLimit} MB.`);
      return;
    }
    onChange({ logo: candidate });
  }

  function removeLogo() {
    onChange({ logo: null });
    if (logoInput.current) logoInput.current.value = "";
  }

  function removeMusic() {
    onChange({ music: null });
    if (musicInput.current) musicInput.current.value = "";
  }

  return (
    <>
      <div className="section-caption">
        MAKE IT YOURS <span>Optional</span>
      </div>
      <label className="field-label" htmlFor="brand">
        Brand name
      </label>
      <input
        id="brand"
        value={brand}
        onChange={(e) => onChange({ brand: e.target.value })}
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
        onChange={(e) => onChange({ description: e.target.value })}
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
        onChange={(e) => onChange({ cta: e.target.value })}
        maxLength={100}
        placeholder="Explore the collection"
        disabled={busy}
      />
      <label className="field-label" htmlFor="brand-color">
        Brand colour <span>Optional · button and backdrop tint</span>
      </label>
      <div className="music-field">
        <input
          id="brand-color"
          type="color"
          className="color-input"
          aria-label="Brand colour"
          value={brandColor || "#183d36"}
          onChange={(e) => onChange({ brandColor: e.target.value })}
          disabled={busy}
        />
        <span className="color-value">
          {brandColor ? brandColor.toUpperCase() : "From your product photo"}
        </span>
        {brandColor && (
          <span className="music-chosen">
            <button
              type="button"
              onClick={() => onChange({ brandColor: "" })}
              disabled={busy}
              aria-label="Remove brand colour"
            >
              Remove
            </button>
          </span>
        )}
      </div>
      <label className="field-label" htmlFor="logo">
        Logo <span>Optional · PNG, JPEG, WebP up to {logoLimit} MB</span>
      </label>
      <div className="music-field">
        <input
          id="logo"
          ref={logoInput}
          type="file"
          accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
          onChange={(e) => selectLogo(e.target.files?.[0])}
          disabled={busy}
          className="music-input"
        />
        <label htmlFor="logo" className="music-button" aria-hidden="true">
          {logo ? "Change logo" : "＋ Add a logo"}
        </label>
        {logo && (
          <span className="music-chosen">
            <span>{logo.name}</span>
            <button
              type="button"
              onClick={removeLogo}
              disabled={busy}
              aria-label="Remove logo"
            >
              Remove
            </button>
          </span>
        )}
      </div>
      <p className="field-hint">
        A transparent PNG works best. It replaces the brand name on the
        creative.
      </p>
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
            <label htmlFor="music" className="music-button" aria-hidden="true">
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
    </>
  );
}
