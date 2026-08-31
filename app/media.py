from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class MediaTools:
    AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".wma"}
    VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"}

    def __init__(self, workspace: Path, timeout: int = 600):
        self.workspace = workspace.resolve()
        self.timeout = timeout
        self.output_dir = self.workspace / "generated" / "media"
        self.analysis_dir = self.output_dir / "analysis"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.analysis_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"),
            "audio_formats": sorted(self.AUDIO_SUFFIXES),
            "video_formats": sorted(self.VIDEO_SUFFIXES),
        }

    def _resolve(self, path: str) -> Path:
        target = (self.workspace / path).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Media path is outside the workspace") from exc
        return target

    def probe(self, path: str) -> dict[str, Any]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return {"ok": False, "error": "ffprobe is not installed or not on PATH"}
        target = self._resolve(path)
        if not target.exists():
            return {"ok": False, "error": "Media file not found"}
        result = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(target)], capture_output=True, text=True, timeout=self.timeout)
        if result.returncode:
            return {"ok": False, "error": result.stderr[-4000:]}
        return {"ok": True, "metadata": json.loads(result.stdout)}

    def transcode(self, input_path: str, output_name: str, video_codec: str = "libx264",
                  audio_codec: str = "aac", extra_args: list[str] | None = None) -> dict[str, Any]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is not installed or not on PATH"}
        source = self._resolve(input_path)
        if not source.exists():
            return {"ok": False, "error": "Input media file not found"}
        target = self.output_dir / Path(output_name).name
        allowed_video = {"libx264", "libx265", "vp9", "copy"}
        allowed_audio = {"aac", "libopus", "mp3", "copy"}
        if video_codec not in allowed_video or audio_codec not in allowed_audio:
            return {"ok": False, "error": "Requested codec is not allow-listed"}
        args = [ffmpeg, "-y", "-i", str(source), "-c:v", video_codec, "-c:a", audio_codec]
        for value in (extra_args or [])[:20]:
            if value.startswith("-") and value not in {"-movflags", "-crf", "-preset", "+faststart"}:
                return {"ok": False, "error": f"Extra argument is not allow-listed: {value}"}
            args.append(value)
        args.append(str(target))
        result = subprocess.run(args, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode:
            return {"ok": False, "error": result.stderr[-8000:]}
        return {"ok": True, "path": target.relative_to(self.workspace).as_posix(), "size_bytes": target.stat().st_size}

    def extract_audio(self, input_path: str, output_name: str | None = None) -> dict[str, Any]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is not installed or not on PATH"}
        source = self._resolve(input_path)
        if not source.exists() or not source.is_file():
            return {"ok": False, "error": "Input media file not found"}
        target = self.output_dir / Path(output_name or f"{source.stem}-speech.wav").with_suffix(".wav").name
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
            capture_output=True, text=True, timeout=self.timeout,
        )
        if result.returncode:
            return {"ok": False, "error": result.stderr[-8000:]}
        return {"ok": True, "path": target.relative_to(self.workspace).as_posix(), "size_bytes": target.stat().st_size}

    @staticmethod
    def _cache_key(source: Path) -> str:
        stat = source.stat()
        return hashlib.sha256(f"{source}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:20]

    @staticmethod
    def _duration(metadata: dict[str, Any]) -> float | None:
        try:
            value = (metadata.get("format") or {}).get("duration")
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def prepare_ai_context(self, path: str, max_frames: int = 6) -> dict[str, Any]:
        """Extract bounded keyframes and speech audio for multimodal model context."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is required for automatic video understanding"}
        source = self._resolve(path)
        if not source.exists() or not source.is_file():
            return {"ok": False, "error": "Media file not found"}
        max_frames = max(1, min(int(max_frames), 12))
        probe = self.probe(path)
        metadata = probe.get("metadata", {}) if probe.get("ok") else {}
        cache_dir = self.analysis_dir / self._cache_key(source)
        cache_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted(cache_dir.glob("frame-*.jpg"))
        audio_target = cache_dir / "speech.wav"
        if source.suffix.lower() in self.VIDEO_SUFFIXES and not frames:
            duration = self._duration(metadata) or float(max_frames * 5)
            interval = max(1.0, duration / max_frames)
            pattern = cache_dir / "frame-%03d.jpg"
            video_result = subprocess.run(
                [
                    ffmpeg, "-y", "-i", str(source), "-vf",
                    f"fps=1/{interval:.3f},scale=1280:-2:force_original_aspect_ratio=decrease",
                    "-frames:v", str(max_frames), "-q:v", "3", str(pattern),
                ],
                capture_output=True, text=True, timeout=self.timeout,
            )
            if video_result.returncode:
                return {"ok": False, "error": video_result.stderr[-8000:], "metadata": metadata}
            frames = sorted(cache_dir.glob("frame-*.jpg"))[:max_frames]
        if not audio_target.exists():
            audio_result = subprocess.run(
                [ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_target)],
                capture_output=True, text=True, timeout=self.timeout,
            )
            if audio_result.returncode:
                audio_target = Path()
        return {
            "ok": True,
            "source": source.relative_to(self.workspace).as_posix(),
            "metadata": metadata,
            "duration": self._duration(metadata),
            "frames": [item.relative_to(self.workspace).as_posix() for item in frames],
            "audio_path": audio_target.relative_to(self.workspace).as_posix() if audio_target and audio_target.exists() else None,
            "cached": True,
        }