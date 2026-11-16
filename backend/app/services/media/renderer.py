import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import UUID
from PIL import Image, ImageDraw, ImageFont, ImageOps
from app.core.config import get_settings
from app.core.platforms import INSTAGRAM_REEL
from app.schemas.content import SocialContent
from app.services.ai.provider import GenerationError
from app.services.storage.local import job_directory


def font(size: int):
    configured = get_settings().font_path
    candidates = [configured, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf"]
    for name in candidates:
        if name and Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def wrap_text(draw, text: str, face, width: int) -> list[str]:
    # Break oversized words too, so arbitrary user CTA cannot escape the canvas.
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=face) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        for char in word:
            if draw.textlength(line + char, font=face) > width:
                lines.append(line)
                line = char
            else:
                line += char
    if line:
        lines.append(line)
    return lines or [""]


def scene_image(source: str, text: str, brand: str, index: int, count: int, destination: Path):
    width, height = INSTAGRAM_REEL.width, INSTAGRAM_REEL.height
    canvas = Image.new("RGB", (width, height), "#102f2b")
    draw = ImageDraw.Draw(canvas)
    brand_font = font(30)
    for row, line in enumerate(wrap_text(draw, (brand or "PRODUCT SPOTLIGHT")[:80], brand_font, 908)[:2]):
        draw.text((86, 136 + row * 40), line, font=brand_font, fill="#ccedcb")
    with Image.open(source) as image:
        image = ImageOps.contain(image.convert("RGB"), (908, 960))
        x, y = (width - image.width) // 2, 340 + (960 - image.height) // 2
        draw.rounded_rectangle((70, 320, width - 70, 1320), radius=30, fill="#f4f3ec")
        canvas.paste(image, (x, y))
    face = font(66)
    lines = wrap_text(draw, text, face, 880)
    if len(lines) > 4:
        face = font(48)
        lines = wrap_text(draw, text, face, 880)
    for row, line in enumerate(lines[:5]):
        draw.text((90, 1420 + row * 79), line, font=face, fill="#ffffff")
    for i in range(count):
        left = 90 + i * 80
        draw.rounded_rectangle((left, 1800, left + 56, 1806), radius=3,
                               fill="#ccedcb" if i == index else "#496661")
    canvas.save(destination)


def run(command: list[str]):
    try:
        subprocess.run(command, check=True, capture_output=True,
                       timeout=get_settings().ffmpeg_timeout_seconds)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise GenerationError("RENDER_FAILED", "Video rendering failed or timed out. Check FFmpeg and retry.") from exc


def inspect_video(path: Path, expected_duration: float) -> dict:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                check=True, capture_output=True, timeout=15)
        metadata = json.loads(result.stdout)
        stream = next(item for item in metadata["streams"] if item["codec_type"] == "video")
        valid = (stream["width"] == INSTAGRAM_REEL.width and stream["height"] == INSTAGRAM_REEL.height
                 and stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
                 and abs(float(metadata["format"]["duration"]) - expected_duration) < 0.5
                 and "mp4" in metadata["format"]["format_name"] and path.stat().st_size > 0)
        if not valid:
            raise ValueError("Invalid media metadata")
        return metadata
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
        raise GenerationError("INVALID_OUTPUT", "The rendered output did not pass media validation. Please retry.") from exc


def render_video(job_id: UUID, source: str, content: SocialContent, brand: dict, run_token: UUID) -> tuple[Path, Path]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise GenerationError("FFMPEG_REQUIRED", "FFmpeg and ffprobe must be installed on the worker.")
    directory = job_directory(job_id)
    scratch = directory / f"render-{run_token}"
    scratch.mkdir(exist_ok=True)
    try:
        for i, scene in enumerate(content.scenes):
            scene_image(source, scene.text, brand.get("brand_name", ""), i, len(content.scenes), scratch / f"scene-{i}.png")
            frames = scene.duration_seconds * 24
            filters = (f"zoompan=z='min(zoom+0.00015,1.03)':d={frames}:s=1080x1920:fps=24,"
                       f"fade=t=in:st=0:d=0.2,fade=t=out:st={scene.duration_seconds-0.2}:d=0.2,format=yuv420p")
            run(["ffmpeg", "-y", "-v", "error", "-filter_threads", "1", "-i", str(scratch / f"scene-{i}.png"),
                 "-vf", filters, "-frames:v", str(frames), "-c:v", "libx264", "-threads", "2",
                 "-preset", "veryfast", "-crf", "23", "-an", str(scratch / f"clip-{i}.mp4")])
        manifest = scratch / "clips.txt"
        manifest.write_text("".join(f"file 'clip-{i}.mp4'\n" for i in range(len(content.scenes))))
        temporary = directory / f"output-{run_token}.partial.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "1", "-i", str(manifest),
             "-c", "copy", "-movflags", "+faststart", str(temporary)])
        inspect_video(temporary, sum(scene.duration_seconds for scene in content.scenes))
        # Decode every frame, not just the container metadata, before accepting the asset.
        run(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", str(temporary), "-f", "null", "-"])
        with Image.open(scratch / "scene-0.png") as image:
            image.thumbnail((540, 960))
            image.save(directory / f"thumbnail-{run_token}.jpg", quality=90)
        output = directory / f"output-{run_token}.mp4"
        os.replace(temporary, output)
        return output, directory / f"thumbnail-{run_token}.jpg"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
