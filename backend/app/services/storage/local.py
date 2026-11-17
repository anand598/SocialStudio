import io
import os
import warnings
import shutil
from pathlib import Path
from uuid import UUID
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from app.core.config import get_settings

Image.MAX_IMAGE_PIXELS = 20_000_000
ALLOWED = {"image/jpeg": ({".jpg", ".jpeg"}, "JPEG"), "image/png": ({".png"}, "PNG"), "image/webp": ({".webp"}, "WEBP")}
IMAGE_FORMATS = {spec[1] for spec in ALLOWED.values()}
ALLOWED_VIDEO = {"video/mp4": {".mp4", ".m4v"}, "video/quicktime": {".mov"}, "video/webm": {".webm"}}
VIDEO_CONTAINERS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm"}
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}
ALLOWED_AUDIO = {"audio/mpeg": {".mp3"}, "audio/mp3": {".mp3"}, "audio/mp4": {".m4a"}, "audio/x-m4a": {".m4a"},
                 "audio/m4a": {".m4a"}, "audio/wav": {".wav"}, "audio/x-wav": {".wav"}, "audio/wave": {".wav"},
                 "audio/vnd.wave": {".wav"}}
AUDIO_CONTAINERS = {"mp3", "mov", "mp4", "m4a", "wav"}
AUDIO_CODECS = {"mp3", "aac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_u8"}
INVALID_IMAGE = "The image is invalid. Use a still image of at least 64 × 64 pixels and at most 20 megapixels."


def job_directory(job_id: UUID | str) -> Path:
    # UUID validation and generated filenames keep user strings out of paths.
    return Path(get_settings().local_storage_path).resolve() / str(UUID(str(job_id)))


def create_job_directory(job_id: UUID) -> Path:
    directory = job_directory(job_id)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise HTTPException(503, "Media storage is unavailable. Please try again shortly.") from exc
    return directory


def decode_image(data: bytes, expected_format: str | None = None) -> Image.Image:
    """Validate untrusted bytes and return a metadata-free RGB image. Raises ValueError."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                allowed = {expected_format} if expected_format else IMAGE_FORMATS
                if image.format not in allowed or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Unsupported content")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                normalized = ImageOps.exif_transpose(image).convert("RGBA")
                if min(normalized.size) < 64:
                    raise ValueError("Image too small")
                # Composite transparency on white; strip metadata and embedded payloads.
                canvas = Image.new("RGB", normalized.size, "white")
                canvas.paste(normalized, mask=normalized.getchannel("A"))
                canvas.thumbnail((2400, 2400))
                return canvas
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid image") from exc


def save_still(canvas: Image.Image, directory: Path) -> str:
    # Write then rename so a retried worker never exposes a half-written file.
    target = directory / "input.jpg"
    partial = directory / "input.partial.jpg"
    canvas.save(partial, "JPEG", quality=92)
    os.replace(partial, target)
    return str(target)


async def store_image(upload: UploadFile, job_id: UUID) -> str:
    settings = get_settings()
    spec = ALLOWED.get(upload.content_type or "")
    if not spec or Path(upload.filename or "").suffix.lower() not in spec[0]:
        raise HTTPException(415, "Upload a JPEG, PNG, or WebP image with a matching extension.")
    data = bytearray()
    while chunk := await upload.read(64 * 1024):
        data.extend(chunk)
        if len(data) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(413, "The image exceeds the upload size limit.")
    return await run_in_threadpool(normalize_image, bytes(data), spec[1], job_id)


def normalize_image(data: bytes, expected_format: str, job_id: UUID) -> str:
    try:
        canvas = decode_image(data, expected_format)
    except ValueError as exc:
        raise HTTPException(422, INVALID_IMAGE) from exc
    directory = create_job_directory(job_id)
    try:
        return save_still(canvas, directory)
    except OSError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(503, "Image storage is unavailable. Please try again shortly.") from exc


async def store_video(upload: UploadFile, job_id: UUID) -> tuple[str, str]:
    """Stream a video to disk, validate it with ffprobe, and extract a still for analysis.

    Returns (source video path, normalized keyframe path).
    """
    settings = get_settings()
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_VIDEO.get(upload.content_type or "", set()):
        raise HTTPException(415, "Upload an MP4, MOV, or WebM video with a matching extension.")
    directory = create_job_directory(job_id)
    source = directory / f"source{suffix}"
    try:
        size = 0
        with source.open("wb") as handle:
            # Stream to disk: video uploads are too large to buffer in memory.
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_video_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, "The video exceeds the upload size limit.")
                await run_in_threadpool(handle.write, chunk)
        still = await run_in_threadpool(validate_video, source, directory)
        return str(source), still
    except HTTPException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(503, "Video storage is unavailable. Please try again shortly.") from exc


def check_music_type(upload: UploadFile) -> str:
    """Cheap MIME/extension agreement check, done before any other upload is stored."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO.get(upload.content_type or "", set()):
        raise HTTPException(415, "Upload background music as an MP3, M4A, or WAV file with a matching extension.")
    return suffix


async def store_music(upload: UploadFile, directory: Path) -> str:
    """Stream an optional music track into an existing job directory and validate it with ffprobe.

    The caller removes the job directory if this raises.
    """
    settings = get_settings()
    suffix = check_music_type(upload)
    target = directory / f"music{suffix}"
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_music_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, "The music file exceeds the upload size limit.")
                await run_in_threadpool(handle.write, chunk)
    except OSError as exc:
        raise HTTPException(503, "Music storage is unavailable. Please try again shortly.") from exc
    await run_in_threadpool(validate_music, target)
    return str(target)


def validate_music(path: Path) -> None:
    from app.services.media.ffmpeg import probe
    settings = get_settings()
    invalid = HTTPException(422, f"The music file is invalid. Use an MP3, M4A, or WAV track between 1 second and "
                                 f"{settings.max_music_seconds // 60} minutes.")
    try:
        metadata = probe(path)
        stream = next(item for item in metadata["streams"] if item.get("codec_type") == "audio")
        duration = float(metadata["format"]["duration"])
        containers = set(metadata["format"]["format_name"].split(","))
        if not (containers & AUDIO_CONTAINERS and stream["codec_name"] in AUDIO_CODECS
                and 1 <= duration <= settings.max_music_seconds):
            raise ValueError("Unsupported audio")
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise invalid from exc


def validate_video(source: Path, directory: Path) -> str:
    from app.services.media.ffmpeg import probe, require_tools, run, video_stream
    from app.services.ai.provider import GenerationError
    settings = get_settings()
    invalid = HTTPException(422, f"The video is invalid. Use an H.264, HEVC, VP8/9 or AV1 video between 1 and "
                                 f"{settings.max_source_video_seconds} seconds, at most 4096 pixels on each side.")
    try:
        require_tools()
    except GenerationError as exc:
        raise HTTPException(503, "Video processing is unavailable on this server.") from exc
    try:
        metadata = probe(source)
        stream = video_stream(metadata)
        duration = float(metadata["format"]["duration"])
        containers = set(metadata["format"]["format_name"].split(","))
        valid = (containers & VIDEO_CONTAINERS and stream["codec_name"] in VIDEO_CODECS
                 and 64 <= int(stream["width"]) <= 4096 and 64 <= int(stream["height"]) <= 4096
                 and 1 <= duration <= settings.max_source_video_seconds)
        if not valid:
            raise ValueError("Unsupported video")
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise invalid from exc
    # A frame from early in the clip (past any fade-in) represents the product for analysis.
    frame = directory / "keyframe.png"
    try:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.0, duration / 3):.2f}", "-i", str(source),
             "-frames:v", "1", "-vf", "scale='min(1920,iw)':-2", str(frame)], timeout=30)
        canvas = decode_image(frame.read_bytes(), "PNG")
    except (GenerationError, ValueError, OSError) as exc:
        raise invalid from exc
    finally:
        frame.unlink(missing_ok=True)
    still = save_still(canvas, directory)
    build_storyboard(source, duration, directory)
    return still


STORYBOARD_CELL = 640


def build_storyboard(source: Path, duration: float, directory: Path) -> Path | None:
    """Sample four moments across the clip into one numbered 2x2 sheet for the vision model.

    One composite image (rather than four separate images) keeps multi-frame analysis inside the
    small context window that fits a 16 GB machine. Failure is non-fatal: analysis falls back to
    the single keyframe.
    """
    from app.services.media.ffmpeg import run
    from app.services.ai.provider import GenerationError
    from PIL import ImageDraw
    from app.services.media.renderer import font
    sheet = Image.new("RGB", (STORYBOARD_CELL * 2, STORYBOARD_CELL * 2), "#111111")
    draw = ImageDraw.Draw(sheet)
    label = font(30)
    try:
        for index, fraction in enumerate((0.1, 0.37, 0.63, 0.9)):
            frame = directory / f"storyboard-{index}.png"
            try:
                run(["ffmpeg", "-y", "-v", "error", "-ss", f"{duration * fraction:.2f}", "-i", str(source),
                     "-frames:v", "1", "-vf", f"scale={STORYBOARD_CELL}:{STORYBOARD_CELL}:force_original_aspect_ratio=decrease",
                     str(frame)], timeout=30)
                with Image.open(frame) as image:
                    cell = image.convert("RGB")
            finally:
                frame.unlink(missing_ok=True)
            x, y = (index % 2) * STORYBOARD_CELL, (index // 2) * STORYBOARD_CELL
            sheet.paste(cell, (x + (STORYBOARD_CELL - cell.width) // 2, y + (STORYBOARD_CELL - cell.height) // 2))
            draw.rounded_rectangle((x + 12, y + 12, x + 58, y + 58), radius=8, fill="#ffffff")
            draw.text((x + 26, y + 16), str(index + 1), font=label, fill="#111111")
        target = directory / "storyboard.jpg"
        sheet.save(target, "JPEG", quality=88)
        return target
    except (GenerationError, OSError, ValueError):
        return None
