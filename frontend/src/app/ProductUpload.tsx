"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";
import { IMAGE_TYPES, VIDEO_TYPES } from "../lib/uploads";

/** The product image or video drop zone, with a preview of the chosen file. */
export default function ProductUpload({
  kind,
  file,
  limitMB,
  maxVideoSeconds,
  busy,
  onChange,
  onError,
}: {
  kind: "image" | "video";
  file: File | null;
  limitMB: number;
  maxVideoSeconds: number;
  busy: boolean;
  onChange: (file: File) => void;
  // Called with "" to clear a previous message.
  onError: (message: string) => void;
}) {
  const [mediaURL, setMediaURL] = useState("");
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const video = kind === "video";

  useEffect(() => {
    if (!file) {
      setMediaURL("");
      return;
    }
    const url = URL.createObjectURL(file);
    setMediaURL(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function selectFile(candidate?: File) {
    onError("");
    if (!candidate) return;
    if (!(video ? VIDEO_TYPES : IMAGE_TYPES).includes(candidate.type)) {
      onError(
        video
          ? "Choose an MP4, MOV, or WebM video."
          : "Choose a JPEG, PNG, or WebP image.",
      );
      return;
    }
    if (candidate.size > limitMB * 1024 * 1024) {
      onError(`Choose a ${kind} smaller than ${limitMB} MB.`);
      return;
    }
    onChange(candidate);
  }

  return (
    <>
      <label className="field-label" htmlFor="product-file">
        {video ? "Product video" : "Product image"}
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
            {video ? (
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
              onClick={() => picker.current?.click()}
              disabled={busy}
            >
              Change {kind}
            </button>
          </>
        ) : (
          <>
            <span className="upload-icon" aria-hidden="true">
              ↥
            </span>
            <p>Drop something worth sharing.</p>
            <span>
              Drag {video ? "a video" : "an image"} here, or{" "}
              <button
                type="button"
                onClick={() => picker.current?.click()}
                disabled={busy}
              >
                browse files
              </button>
            </span>
            <small>
              {video
                ? `MP4, MOV or WebM · Up to ${limitMB} MB · ${maxVideoSeconds} s max`
                : `JPEG, PNG or WebP · Up to ${limitMB} MB`}
            </small>
          </>
        )}
        <input
          id="product-file"
          ref={picker}
          type="file"
          className="sr-only"
          accept={(video ? VIDEO_TYPES : IMAGE_TYPES).join(",")}
          disabled={busy}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            selectFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </div>
      {file && (
        <p className="filename">
          {file.name} <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
        </p>
      )}
    </>
  );
}
