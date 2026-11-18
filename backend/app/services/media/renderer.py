"""Template rendering for every registered output format.

Three paths, all driven by the format registry's exact dimensions:
  * image output          -> one poster (JPEG) in the promo design, dimension-verified;
  * video from a still    -> promo video (see promo.py): shot plan, motion, animated captions,
                             cross-fades; frames streamed to FFmpeg as silent H.264;
  * video from a video    -> source reframed onto the target aspect over a blurred fill,
                             trimmed to the format limit, with hook/CTA/brand overlays; audio kept.
Every video is ffprobe-checked and fully decoded before it is published atomically.
"""
import os
import re
import shutil
from pathlib import Path
from uuid import UUID
from PIL import Image, ImageDraw
from app.core.platforms import INSTAGRAM_REEL, OutputFormat
from app.schemas.content import SocialContent
from app.services.ai.provider import GenerationError
from app.services.media.ffmpeg import (AUDIO_OUT, encode_frames, has_audio, music_filter, probe, require_tools, run,
                                       video_stream)
from app.services.media.promo import FPS, Promo, fit_logo, hex_rgb, layout, text_on
from app.services.media.typography import BOLD_FONTS, REGULAR_FONTS, fit_text, font, wrap_text  # noqa: F401
from app.services.storage.local import job_directory

INK = "#102f2b"
# Opening title card for template videos, so the hook is the first thing viewers read.
HOOK_SECONDS = 2


def compose_frame(output: OutputFormat, source: str, text: str, brand: str, *, cta: str = "",
                  brand_color: str | None = None, logo: str | None = None) -> Image.Image:
    """Poster for image formats: photo- or brand-coloured backdrop, product card, headline, brand, CTA."""
    return Promo(output, source, [(text, 1)], brand=brand, cta=cta, brand_color=brand_color, logo=logo).poster()


def brand_anchor(output: OutputFormat) -> tuple[int, int]:
    """Top-left of the brand mark on reframed video, below the top app UI on vertical feeds."""
    margin = round(min(output.width, output.height) * 0.06)
    return margin, round(output.height * 0.1) if output.orientation == "portrait" else margin


def logo_overlay(output: OutputFormat, logo: str) -> Image.Image:
    """Transparent full-frame layer with the logo at the brand position."""
    layer = Image.new("RGBA", (output.width, output.height), (0, 0, 0, 0))
    mark = fit_logo(logo, output)
    layer.paste(mark, brand_anchor(output), mark)
    return layer


def overlay_image(output: OutputFormat, text: str, position: str, *, accent: bool = False,
                  accent_colour: tuple[int, int, int] | None = None) -> Image.Image:
    """Transparent full-frame overlay with a readable text box, for compositing onto source video."""
    width, height = output.width, output.height
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    margin = round(min(width, height) * 0.06)
    box_width = width - margin * 2 if output.orientation != "landscape" else round(width * 0.6)
    size = round(min(width, height) * (0.06 if position != "brand" else 0.03))
    face, lines, line_height = fit_text(draw, text, box_width - margin, round(size * 1.2 * 3), size, bold=True)
    text_width = max(draw.textlength(line, font=face) for line in lines)
    pad = round(size * 0.6)
    box_w, box_h = text_width + pad * 2, len(lines) * line_height + pad * 2
    portrait = output.orientation == "portrait"
    # Vertical feeds cover the top ~10% (tabs) and bottom ~20% (caption, username, music) with app UI.
    if position == "brand":
        left, top = brand_anchor(output)
    else:
        left = (width - box_w) // 2
        top = round(height * (0.15 if portrait else 0.08)) if position == "top" \
            else height - round(height * (0.22 if portrait else 0.1)) - box_h
    accent_fill = accent_colour or (204, 237, 203)
    fill = (*accent_fill, 240) if accent else (16, 47, 43, 205)
    ink = "#{:02x}{:02x}{:02x}".format(*text_on(accent_fill)) if accent else "#ffffff"
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=round(size * 0.5), fill=fill)
    for row, line in enumerate(lines):
        line_x = left + (box_w - draw.textlength(line, font=face)) / 2
        draw.text((line_x, top + pad + row * line_height), line, font=face, fill=ink)
    return layer


def inspect_video(path: Path, expected_duration: float, output: OutputFormat = INSTAGRAM_REEL) -> dict:
    try:
        metadata = probe(path)
        stream = video_stream(metadata)
        valid = (stream["width"] == output.width and stream["height"] == output.height
                 and stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
                 and abs(float(metadata["format"]["duration"]) - expected_duration) < 0.5
                 and "mp4" in metadata["format"]["format_name"] and path.stat().st_size > 0)
        if not valid:
            raise ValueError("Invalid media metadata")
        return metadata
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise GenerationError("INVALID_OUTPUT", "The rendered output did not pass media validation. Please retry.") from exc


def publish_video(temporary: Path, directory: Path, run_token: UUID, duration: float, output: OutputFormat) -> Path:
    inspect_video(temporary, duration, output)
    # Decode every frame, not just the container metadata, before accepting the asset.
    run(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", str(temporary), "-f", "null", "-"])
    final = directory / f"output-{run_token}.mp4"
    os.replace(temporary, final)
    return final


def save_thumbnail(image: Image.Image, directory: Path, run_token: UUID) -> Path:
    thumbnail = image.convert("RGB").copy()
    thumbnail.thumbnail((540, 960))
    path = directory / f"thumbnail-{run_token}.jpg"
    thumbnail.save(path, quality=90)
    return path


def render_image(directory: Path, output: OutputFormat, source: str, content: SocialContent, brand: dict,
                 run_token: UUID) -> tuple[Path, Path]:
    poster = compose_frame(output, source, content.hook, brand.get("brand_name", ""), cta=content.call_to_action,
                           brand_color=brand.get("brand_color"), logo=brand.get("logo_path"))
    temporary = directory / f"output-{run_token}.partial.jpg"
    poster.save(temporary, "JPEG", quality=92, optimize=True)
    try:
        with Image.open(temporary) as check:
            if check.format != "JPEG" or check.size != (output.width, output.height):
                raise ValueError("Invalid image output")
    except (OSError, ValueError) as exc:
        raise GenerationError("INVALID_OUTPUT", "The rendered image did not pass validation. Please retry.") from exc
    final = directory / f"output-{run_token}.jpg"
    os.replace(temporary, final)
    return final, save_thumbnail(poster, directory, run_token)


def slideshow_scenes(content: SocialContent) -> list[tuple[str, int]]:
    """On-screen captions and durations: the hook opens unless the first scene already says it.

    Models often split the hook across the opening scenes, so overlap in either direction counts.
    """
    scenes = [(scene.text, scene.duration_seconds) for scene in content.scenes]
    def key(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())
    hook, first = key(content.hook), key(scenes[0][0])
    if hook and first and hook not in first and first not in hook:
        scenes.insert(0, (content.hook, HOOK_SECONDS))
    return scenes


def render_slideshow(directory: Path, scratch: Path, output: OutputFormat, source: str, content: SocialContent,
                     brand: dict, run_token: UUID, music: str | None = None) -> tuple[Path, Path]:
    video = Promo(output, source, slideshow_scenes(content), brand=brand.get("brand_name", ""),
                  cta=content.call_to_action, brand_color=brand.get("brand_color"), logo=brand.get("logo_path"))
    temporary = directory / f"output-{run_token}.partial.mp4"
    encode_frames(video.frames(), output.width, output.height, FPS, temporary, music=music, duration=video.duration)
    # Cover image: the opening shot once its caption has landed.
    thumbnail = save_thumbnail(video.frame(min(1.2, video.duration / 2)), directory, run_token)
    return publish_video(temporary, directory, run_token, video.duration, output), thumbnail


def render_from_video(directory: Path, scratch: Path, output: OutputFormat, source_video: str, content: SocialContent,
                      brand: dict, run_token: UUID, music: str | None = None) -> tuple[Path, Path]:
    try:
        metadata = probe(Path(source_video))
        duration = round(min(float(metadata["format"]["duration"]), output.max_video_seconds), 2)
    except (ValueError, KeyError) as exc:
        raise GenerationError("INVALID_SOURCE", "The source video could not be read. Upload it again.") from exc
    width, height = output.width, output.height
    hook_end = round(min(3.5, duration * 0.45), 2)
    cta_start = round(max(duration - 3.5, duration * 0.55), 2)
    overlay_image(output, content.hook, "top").save(scratch / "hook.png")
    colour = brand.get("brand_color")
    overlay_image(output, content.call_to_action, "bottom", accent=True,
                  accent_colour=hex_rgb(colour) if colour else None).save(scratch / "cta.png")
    # The logo, when given, stands in for the brand name.
    if brand.get("logo_path"):
        logo_overlay(output, brand["logo_path"]).save(scratch / "brand.png")
    elif brand.get("brand_name"):
        overlay_image(output, brand["brand_name"], "brand").save(scratch / "brand.png")
    has_brand = (scratch / "brand.png").is_file()
    inputs = ["-i", source_video]
    for name in ["hook", "cta"] + (["brand"] if has_brand else []):
        inputs += ["-loop", "1", "-framerate", "30", "-t", str(duration), "-i", str(scratch / f"{name}.png")]
    # Fill the frame with a blurred, darkened copy and centre the uncropped source on top,
    # so any source aspect becomes the platform aspect without distortion or losing the product.
    graph = (f"[0:v]fps=30,split=2[bgsrc][fgsrc];"
             f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
             f"boxblur=24:2,eq=brightness=-0.12[bg];"
             f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
             f"[base][1:v]overlay=0:0:enable='between(t,0,{hook_end})'[v1];"
             f"[v1][2:v]overlay=0:0:enable='gte(t,{cta_start})'[v2];")
    graph += "[v2][3:v]overlay=0:0,format=yuv420p[out]" if has_brand else "[v2]format=yuv420p[out]"
    if music:
        # Music sits quietly under the clip's own sound (or plays alone if the clip is silent).
        index = len([arg for arg in inputs if arg == "-i"])
        inputs += ["-i", music]
        if has_audio(metadata):
            graph += (f";[0:a]aresample=48000[src];[{index}:a]{music_filter(duration, loudness=-20)},volume=0.35[bgm];"
                      f"[src][bgm]amix=inputs=2:duration=first:normalize=0[aout]")
        else:
            graph += f";[{index}:a]{music_filter(duration)}[aout]"
        audio = ["-map", "[aout]", *AUDIO_OUT]
    elif has_audio(metadata):
        audio = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    else:
        audio = ["-an"]
    temporary = directory / f"output-{run_token}.partial.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-filter_threads", "2", *inputs, "-filter_complex", graph,
         "-map", "[out]", *audio, "-t", str(duration), "-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
         "-crf", "23", "-movflags", "+faststart", str(temporary)])
    final = publish_video(temporary, directory, run_token, duration, output)
    still = scratch / "thumbnail.png"
    run(["ffmpeg", "-y", "-v", "error", "-ss", str(min(1.0, hook_end / 2)), "-i", str(final), "-frames:v", "1", str(still)])
    with Image.open(still) as frame:
        return final, save_thumbnail(frame, directory, run_token)


def render_output(job_id: UUID, output: OutputFormat, still: str, content: SocialContent, brand: dict,
                  run_token: UUID, source_video: str | None = None, music: str | None = None) -> tuple[Path, Path]:
    directory = job_directory(job_id)
    if output.kind == "image":
        return render_image(directory, output, still, content, brand, run_token)
    require_tools()
    scratch = directory / f"render-{run_token}"
    scratch.mkdir(exist_ok=True)
    try:
        if source_video:
            return render_from_video(directory, scratch, output, source_video, content, brand, run_token, music)
        return render_slideshow(directory, scratch, output, still, content, brand, run_token, music)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def render_video(job_id: UUID, source: str, content: SocialContent, brand: dict, run_token: UUID) -> tuple[Path, Path]:
    """Backward-compatible entry point: still image to Instagram Reel."""
    return render_output(job_id, INSTAGRAM_REEL, source, content, brand, run_token)
