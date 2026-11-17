"""Bounded FFmpeg/ffprobe invocation shared by upload validation and rendering.

All commands are argument arrays with generated paths only; no user string reaches a shell.
"""
import json
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from app.core.config import get_settings
from app.services.ai.provider import GenerationError


def require_tools() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise GenerationError("FFMPEG_REQUIRED", "FFmpeg and ffprobe must be installed on the worker.")


def run(command: list[str], timeout: int | None = None) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True,
                       timeout=timeout or get_settings().ffmpeg_timeout_seconds)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise GenerationError("RENDER_FAILED", "Video processing failed or timed out. Check FFmpeg and retry.") from exc


def music_filter(duration: float, loudness: int = -16) -> str:
    """Normalize a music track, fade it in/out, and pad or trim it to exactly `duration` seconds."""
    fade_out = max(0.0, duration - 1.5)
    return (f"loudnorm=I={loudness}:TP=-1.5:LRA=11,aresample=48000,afade=t=in:st=0:d=0.6,apad,"
            f"atrim=0:{duration:.3f},afade=t=out:st={fade_out:.3f}:d=1.5")


AUDIO_OUT = ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]


def encode_frames(frames: Iterable, width: int, height: int, fps: int, target: Path,
                  timeout: int | None = None, music: str | None = None, duration: float = 0.0) -> None:
    """Stream RGB Pillow frames into an H.264/yuv420p MP4 (with optional music), bounded by the FFmpeg timeout."""
    deadline = time.monotonic() + (timeout or get_settings().ffmpeg_timeout_seconds)
    audio = (["-i", music, "-map", "0:v", "-map", "1:a:0", "-af", music_filter(duration), *AUDIO_OUT]
             if music else ["-an"])
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "-", *audio, "-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    failure = GenerationError("RENDER_FAILED", "Video processing failed or timed out. Check FFmpeg and retry.")
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise failure from exc
    try:
        for frame in frames:
            if time.monotonic() > deadline:
                raise failure
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        if process.wait(timeout=max(1.0, deadline - time.monotonic())) != 0:
            raise failure
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise failure from exc
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def probe(path: Path) -> dict:
    """Return ffprobe stream/format metadata, or raise ValueError for unreadable media."""
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                check=True, capture_output=True, timeout=20)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("Unreadable media") from exc


def video_stream(metadata: dict) -> dict:
    return next(item for item in metadata.get("streams", []) if item.get("codec_type") == "video")


def has_audio(metadata: dict) -> bool:
    return any(item.get("codec_type") == "audio" for item in metadata.get("streams", []))
