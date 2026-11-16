import io
import warnings
from pathlib import Path
from uuid import UUID
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException, UploadFile
from app.core.config import get_settings

Image.MAX_IMAGE_PIXELS = 20_000_000
ALLOWED = {"image/jpeg": ({".jpg", ".jpeg"}, "JPEG"), "image/png": ({".png"}, "PNG"), "image/webp": ({".webp"}, "WEBP")}


def job_directory(job_id: UUID | str) -> Path:
    # UUID validation and generated filenames keep user strings out of paths.
    return Path(get_settings().local_storage_path).resolve() / str(UUID(str(job_id)))


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
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != spec[1] or getattr(image, "n_frames", 1) != 1:
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
                directory = job_directory(job_id)
                directory.mkdir(parents=True, exist_ok=False)
                target = directory / "input.jpg"
                canvas.save(target, "JPEG", quality=92)
                return str(target)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, "The image is invalid. Use a still image of at least 64 × 64 pixels and at most 20 megapixels.") from exc
