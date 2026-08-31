from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class MediaTools:
    AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".wma"}
    VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"}
    MAX_OUTPUT_BYTES = 2_000_000_000
    MAX_AI_AUDIO_SECONDS = 1800

    def __init__(self, workspace: Path, timeout: int = 600):
        if workspace.is_symlink():
            raise ValueError("Media workspace root must not be a symlink")
        self.workspace = workspace.resolve()
        self.timeout = max(5, min(int(timeout), 3600))
        self.output_dir = self.workspace / "generated" / "media"
        self.analysis_dir = self.output_dir / "analysis"
        for directory in (self.output_dir, self.analysis_dir):
            if directory.exists() and directory.is_symlink():
                raise ValueError("Media output directories must not be symlinks")
            directory.mkdir(parents=True, exist_ok=True)

    def _tool(self, name: str) -> str | None:
        found = shutil.which(name)
        if not found:
            return None
        try:
            resolved = Path(found).resolve(strict=True)
            resolved.relative_to(self.workspace)
        except ValueError:
            return str(resolved)
        except OSError:
            return None
        # Do not execute a workspace-controlled ffmpeg/ffprobe through PATH.
        return None

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "ffmpeg": self._tool("ffmpeg"),
            "ffprobe": self._tool("ffprobe"),
            "audio_formats": sorted(self.AUDIO_SUFFIXES),
            "video_formats": sorted(self.VIDEO_SUFFIXES),
        }

    def _resolve(self, path: str) -> Path:
        lexical = Path(os.path.abspath(str(self.workspace / str(path))))
        try:
            lexical.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Media path is outside the workspace") from exc
        current = self.workspace
        for part in lexical.relative_to(self.workspace).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("Media paths must not traverse symlinks")
        target = lexical.resolve(strict=False)
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Media path is outside the workspace") from exc
        return target

    def _source(self, path: str) -> Path:
        target = self._resolve(path)
        if not target.exists() or not target.is_file():
            raise ValueError("Media file not found")
        if target.suffix.lower() not in self.AUDIO_SUFFIXES | self.VIDEO_SUFFIXES:
            raise ValueError("Unsupported media file extension")
        return target

    def _target(self, output_name: str, allowed_suffixes: set[str]) -> Path:
        safe_name = Path(str(output_name or "")).name
        if safe_name in {"", ".", ".."}:
            raise ValueError("A valid media output filename is required")
        target = self.output_dir / safe_name
        if target.suffix.lower() not in allowed_suffixes:
            raise ValueError("Unsupported media output extension")
        if target.is_symlink():
            raise ValueError("Media output target must not be a symlink")
        return target

    @staticmethod
    def _child_env() -> dict[str, str]:
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "LANG", "LC_ALL"}
        return {key: value for key, value in os.environ.items() if key.upper() in allowed}

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=self._child_env(),
            stdin=subprocess.DEVNULL,
        )

    def _temporary_output(self, target: Path) -> Path:
        fd, name = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=target.suffix, dir=self.output_dir)
        os.close(fd)
        return Path(name)

    @staticmethod
    def _extra_ffmpeg_args(extra_args: list[str] | None) -> tuple[bool, list[str] | str]:
        values = [str(item) for item in (extra_args or [])[:20]]
        parsed: list[str] = []
        index = 0
        presets = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}
        while index < len(values):
            option = values[index]
            if option not in {"-movflags", "-crf", "-preset"} or index + 1 >= len(values):
                return False, f"Extra ffmpeg argument is not allow-listed or is missing a value: {option}"
            value = values[index + 1]
            if option == "-movflags" and value not in {"+faststart", "faststart"}:
                return False, "Only faststart movflags are allowed"
            if option == "-crf":
                try:
                    crf = int(value)
                except ValueError:
                    return False, "CRF must be an integer"
                if crf < 0 or crf > 63:
                    return False, "CRF must be between 0 and 63"
            if option == "-preset" and value not in presets:
                return False, "Requested ffmpeg preset is not allow-listed"
            parsed.extend([option, value])
            index += 2
        return True, parsed

    def probe(self, path: str) -> dict[str, Any]:
        ffprobe = self._tool("ffprobe")
        if not ffprobe:
            return {"ok": False, "error": "ffprobe is not installed or an unsafe executable was found on PATH"}
        try:
            target = self._source(path)
            result = self._run([
                ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
                "-show_format", "-show_streams", "-of", "json", str(target),
            ])
        except (ValueError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc)}
        if result.returncode:
            return {"ok": False, "error": result.stderr[-4000:]}
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": "ffprobe returned invalid JSON"}
        return {"ok": True, "metadata": metadata}

    def transcode(self, input_path: str, output_name: str, video_codec: str = "libx264",
                  audio_codec: str = "aac", extra_args: list[str] | None = None) -> dict[str, Any]:
        ffmpeg = self._tool("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is not installed or an unsafe executable was found on PATH"}
        try:
            source = self._source(input_path)
            target = self._target(output_name, self.AUDIO_SUFFIXES | self.VIDEO_SUFFIXES)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        allowed_video = {"libx264", "libx265", "vp9", "copy"}
        allowed_audio = {"aac", "libopus", "mp3", "copy"}
        if video_codec not in allowed_video or audio_codec not in allowed_audio:
            return {"ok": False, "error": "Requested codec is not allow-listed"}
        extra_ok, parsed_extra = self._extra_ffmpeg_args(extra_args)
        if not extra_ok:
            return {"ok": False, "error": str(parsed_extra)}

        temporary = self._temporary_output(target)
        try:
            args = [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-i", str(source),
                "-c:v", video_codec, "-c:a", audio_codec,
                *parsed_extra, "-fs", str(self.MAX_OUTPUT_BYTES), str(temporary),
            ]
            result = self._run(args)
            if result.returncode:
                return {"ok": False, "error": result.stderr[-8000:]}
            if temporary.stat().st_size > self.MAX_OUTPUT_BYTES:
                return {"ok": False, "error": "Transcoded media exceeded the output size limit"}
            if target.is_symlink():
                return {"ok": False, "error": "Media output target became a symlink"}
            os.replace(temporary, target)
            return {"ok": True, "path": target.relative_to(self.workspace).as_posix(), "size_bytes": target.stat().st_size}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Media transcode timed out"}
        finally:
            temporary.unlink(missing_ok=True)

    def extract_audio(self, input_path: str, output_name: str | None = None) -> dict[str, Any]:
        ffmpeg = self._tool("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is not installed or an unsafe executable was found on PATH"}
        try:
            source = self._source(input_path)
            requested_name = Path(output_name or f"{source.stem}-speech.wav").with_suffix(".wav").name
            target = self._target(requested_name, {".wav"})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        temporary = self._temporary_output(target)
        try:
            result = self._run([
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", "-fs", str(self.MAX_OUTPUT_BYTES), str(temporary),
            ])
            if result.returncode:
                return {"ok": False, "error": result.stderr[-8000:]}
            if target.is_symlink():
                return {"ok": False, "error": "Media output target became a symlink"}
            os.replace(temporary, target)
            return {"ok": True, "path": target.relative_to(self.workspace).as_posix(), "size_bytes": target.stat().st_size}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Audio extraction timed out"}
        finally:
            temporary.unlink(missing_ok=True)

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
        ffmpeg = self._tool("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is required for automatic video understanding"}
        try:
            source = self._source(path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        max_frames = max(1, min(int(max_frames), 12))
        probe = self.probe(path)
        metadata = probe.get("metadata", {}) if probe.get("ok") else {}
        cache_dir = self.analysis_dir / self._cache_key(source)
        if cache_dir.exists() and cache_dir.is_symlink():
            return {"ok": False, "error": "Media analysis cache must not be a symlink"}
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_items = list(cache_dir.iterdir())
        if any(item.is_symlink() for item in cached_items):
            return {"ok": False, "error": "Media analysis cache contains a symlink"}
        frames = sorted(item for item in cache_dir.glob("frame-*.jpg") if item.is_file())[:max_frames]
        audio_target = cache_dir / "speech.wav"
        try:
            if source.suffix.lower() in self.VIDEO_SUFFIXES and not frames:
                duration = self._duration(metadata) or float(max_frames * 5)
                interval = max(1.0, duration / max_frames)
                pattern = cache_dir / "frame-%03d.jpg"
                video_result = self._run([
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-protocol_whitelist", "file,pipe", "-i", str(source), "-vf",
                    f"fps=1/{interval:.3f},scale=1280:-2:force_original_aspect_ratio=decrease",
                    "-frames:v", str(max_frames), "-q:v", "3", str(pattern),
                ])
                if video_result.returncode:
                    return {"ok": False, "error": video_result.stderr[-8000:], "metadata": metadata}
                frames = sorted(item for item in cache_dir.glob("frame-*.jpg") if item.is_file() and not item.is_symlink())[:max_frames]
            if audio_target.is_symlink():
                return {"ok": False, "error": "Media analysis audio target must not be a symlink"}
            if not audio_target.exists():
                audio_result = self._run([
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", "-t", str(self.MAX_AI_AUDIO_SECONDS), "-fs", str(self.MAX_OUTPUT_BYTES), str(audio_target),
                ])
                if audio_result.returncode:
                    audio_target = Path()
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Media AI preparation timed out", "metadata": metadata}
        return {
            "ok": True,
            "source": source.relative_to(self.workspace).as_posix(),
            "metadata": metadata,
            "duration": self._duration(metadata),
            "frames": [item.relative_to(self.workspace).as_posix() for item in frames],
            "audio_path": audio_target.relative_to(self.workspace).as_posix() if audio_target and audio_target.exists() else None,
            "cached": True,
        }
