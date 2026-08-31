from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.persistence_security import sanitize_for_persistence
from app.voice_adapter import VOICE_PROFILES


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_AUDIO_BYTES = 1024 * 1024 * 1024
MAX_OUTPUT_BYTES = 100 * 1024 * 1024
MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024
MAX_MODEL_CONFIG_BYTES = 5 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 1_000_000
MAX_TRANSCRIPT_SEGMENTS = 20_000
MAX_INITIAL_PROMPT_CHARS = 10_000
ALLOWED_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
ALLOWED_DEVICES = {"auto", "cpu", "cuda"}
ALLOWED_COMPUTE_TYPES = {"default", "int8", "int8_float16", "float16", "float32"}
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2})?$")
_SAFE_ENV_KEYS = {
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
    "LOCALAPPDATA", "APPDATA", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
}
_SECRET_ENV_TOKENS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "CREDENTIAL", "AUTH", "COOKIE", "SESSION")


def _safe_error(value: Any) -> str:
    cleaned = sanitize_for_persistence(str(value))
    return str(cleaned)[:6000]


def _safe_child_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None and not any(token in key.upper() for token in _SECRET_ENV_TOKENS):
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _reject_symlink_chain(path: Path, *, stop_at: Path | None = None) -> None:
    absolute = path.absolute()
    stop = stop_at.absolute() if stop_at is not None else None
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlinked voice path is not allowed: {current}")
        if stop is not None and current == stop:
            continue


def _ensure_regular(path: Path, *, max_bytes: int, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label} is missing or is not a regular file")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"{label} exceeds the {max_bytes:,}-byte limit")


class VoiceSecurityGuard:
    """Core runtime guard around optional voice engines and model downloads."""

    def __init__(self, voice: Any):
        self.voice = voice
        self.workspace = Path(voice.workspace).resolve()
        self.output_dir = Path(voice.output_dir)
        self.upload_dir = Path(voice.upload_dir)
        self.voice_dir = Path(voice.voice_dir)
        self._original_install_profile: Callable[..., Any] = voice.install_profile
        self._original_speak: Callable[..., Any] = voice.speak
        self._original_transcribe: Callable[..., Any] = voice.transcribe
        self._original_save_upload: Callable[..., Any] = voice.save_upload
        self._validate_roots()

    def _validate_roots(self) -> None:
        for path, label in (
            (self.workspace, "voice workspace"),
            (self.output_dir, "voice output directory"),
            (self.upload_dir, "voice upload directory"),
            (self.voice_dir, "voice model directory"),
        ):
            _reject_symlink_chain(path)
            if path.exists() and not path.is_dir():
                raise ValueError(f"{label} must be a directory")

    def _source(self, path: str) -> Path:
        raw = self.workspace / path
        _reject_symlink_chain(raw, stop_at=self.workspace)
        target = raw.resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Audio path is outside the workspace") from exc
        _ensure_regular(target, max_bytes=MAX_AUDIO_BYTES, label="Audio source")
        if target.suffix.lower() not in self.voice.AUDIO_SUFFIXES:
            raise ValueError("Unsupported audio file type")
        return target

    def _output_target(self, filename: str) -> Path:
        name = Path(filename).with_suffix(".wav").name
        if not name or len(name) > 180:
            raise ValueError("Invalid voice output filename")
        target = self.output_dir / name
        _reject_symlink_chain(self.output_dir)
        if target.is_symlink():
            raise ValueError("Voice output target may not be a symlink")
        return target

    def _model_files(self, model: str) -> tuple[Path, Path]:
        model_path = self.voice_dir / f"{model}.onnx"
        config_path = model_path.with_suffix(".onnx.json")
        _reject_symlink_chain(self.voice_dir)
        if model_path.is_symlink() or config_path.is_symlink():
            raise ValueError("Voice model files may not be symlinks")
        return model_path, config_path

    def install_profile(self, voice_id: str) -> dict[str, Any]:
        profile = VOICE_PROFILES.get(voice_id)
        if not profile:
            return {"ok": False, "error": f"Unknown voice profile: {voice_id}"}
        if profile.get("engine") == "pyttsx3":
            return {"ok": self.voice._module_available("pyttsx3"), "voice": self.voice._profile_payload(profile)}
        if not self.voice._module_available("piper"):
            return {"ok": False, "error": "Piper is not installed. Run install_voice_windows.bat or install requirements-voice.txt."}

        model = str(profile.get("model") or "")
        allowed_models = {
            str(item.get("model"))
            for item in VOICE_PROFILES.values()
            if item.get("engine") == "piper" and item.get("model")
        }
        if model not in allowed_models:
            return {"ok": False, "error": "Voice model is not allow-listed"}
        try:
            model_path, config_path = self._model_files(model)
            if model_path.exists() and config_path.exists():
                _ensure_regular(model_path, max_bytes=MAX_MODEL_BYTES, label="Voice model")
                _ensure_regular(config_path, max_bytes=MAX_MODEL_CONFIG_BYTES, label="Voice model configuration")
                return {"ok": True, "voice": self.voice._profile_payload(profile), "already_installed": True}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        command = [sys.executable, "-m", "piper.download_voices", "--data-dir", str(self.voice_dir), model]
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1800,
                cwd=str(self.voice_dir),
                env=_safe_child_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Voice download timed out after 30 minutes."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Voice download failed: {_safe_error(exc)}"}
        if result.returncode:
            return {"ok": False, "error": _safe_error(result.stderr or result.stdout or "Voice download failed")}

        try:
            model_path, config_path = self._model_files(model)
            _ensure_regular(model_path, max_bytes=MAX_MODEL_BYTES, label="Voice model")
            _ensure_regular(config_path, max_bytes=MAX_MODEL_CONFIG_BYTES, label="Voice model configuration")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "voice": self.voice._profile_payload(profile),
            "output": _safe_error(result.stdout or result.stderr or "")[:4000],
        }

    def speak(self, text: str, filename: str = "dpn-ai-speech.wav", **kwargs: Any) -> dict[str, Any]:
        if not isinstance(text, str) or len(text) > 100_000:
            return {"ok": False, "error": "Speech text exceeds the 100,000-character limit"}
        try:
            target = self._output_target(filename)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        temp_name = f".dpn-voice-{uuid4().hex}.wav"
        temp_path = self.output_dir / temp_name
        try:
            result = self._original_speak(text=text, filename=temp_name, **kwargs)
            if not isinstance(result, dict):
                return {"ok": False, "error": "Voice engine returned an invalid result"}
            if not result.get("ok"):
                if "error" in result:
                    result["error"] = _safe_error(result["error"])
                return result
            _ensure_regular(temp_path, max_bytes=MAX_OUTPUT_BYTES, label="Voice output")
            if temp_path.stat().st_size < 44:
                return {"ok": False, "error": "The speech engine did not create a valid WAV file."}
            if target.is_symlink():
                return {"ok": False, "error": "Voice output target may not be a symlink"}
            os.replace(temp_path, target)
            try:
                if os.name == "posix":
                    os.chmod(target, 0o600)
            except OSError:
                pass
            result["path"] = target.relative_to(self.workspace).as_posix()
            result["size_bytes"] = target.stat().st_size
            return result
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Speech generation failed: {_safe_error(exc)}"}
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def transcribe(
        self,
        path: str,
        model_size: str = "base",
        language: str | None = None,
        initial_prompt: str | None = None,
        device: str = "auto",
        compute_type: str = "int8",
    ) -> dict[str, Any]:
        if model_size not in ALLOWED_WHISPER_MODELS:
            return {"ok": False, "error": "Whisper model is not allow-listed"}
        if device not in ALLOWED_DEVICES or compute_type not in ALLOWED_COMPUTE_TYPES:
            return {"ok": False, "error": "Unsupported transcription runtime configuration"}
        if language and (len(language) > 16 or not _LANGUAGE_RE.fullmatch(language)):
            return {"ok": False, "error": "Invalid transcription language code"}
        if initial_prompt is not None and len(initial_prompt) > MAX_INITIAL_PROMPT_CHARS:
            return {"ok": False, "error": f"Initial prompt exceeds {MAX_INITIAL_PROMPT_CHARS:,} characters"}
        try:
            source = self._source(path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        result = self._original_transcribe(
            source.relative_to(self.workspace).as_posix(),
            model_size=model_size,
            language=language,
            initial_prompt=initial_prompt,
            device=device,
            compute_type=compute_type,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "Transcription engine returned an invalid result"}
        if not result.get("ok"):
            if "error" in result:
                result["error"] = _safe_error(result["error"])
            return result
        text = str(result.get("text") or "")
        segments = result.get("segments") or []
        if len(text) > MAX_TRANSCRIPT_CHARS or not isinstance(segments, list) or len(segments) > MAX_TRANSCRIPT_SEGMENTS:
            return {"ok": False, "error": "Transcription output exceeded safety limits"}
        return result

    def save_upload(self, data: bytes, filename: str) -> str:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("Voice upload must be bytes")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Voice upload exceeds the {MAX_UPLOAD_BYTES:,}-byte limit")
        suffix = Path(filename).suffix.lower() or ".webm"
        if suffix not in self.voice.AUDIO_SUFFIXES:
            suffix = ".webm"
        digest = __import__("hashlib").sha256(data).hexdigest()[:16]
        _reject_symlink_chain(self.upload_dir)
        for attempt in range(8):
            target = self.upload_dir / f"voice-{time.time_ns()}-{digest}-{attempt}{suffix}"
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                return target.relative_to(self.workspace).as_posix()
            except Exception:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        raise RuntimeError("Could not allocate a unique voice upload path")


def install_voice_security(registry: Any) -> VoiceSecurityGuard | None:
    """Install the voice guard into the core ToolRegistry and its registered callbacks.

    Loader unit tests may pass tiny stand-in registries. Those do not own a voice
    adapter and are intentionally left untouched.
    """
    voice = getattr(registry, "voice", None)
    tools = getattr(registry, "tools", None)
    if voice is None or not isinstance(tools, dict):
        return None
    existing = getattr(registry, "voice_security", None)
    if isinstance(existing, VoiceSecurityGuard):
        return existing

    guard = VoiceSecurityGuard(voice)
    registry.voice_security = guard
    voice.install_profile = guard.install_profile
    voice.speak = guard.speak
    voice.transcribe = guard.transcribe
    voice.save_upload = guard.save_upload
    callbacks = {
        "install_voice_profile": guard.install_profile,
        "transcribe_audio": guard.transcribe,
        "speak_text": guard.speak,
    }
    for name, callback in callbacks.items():
        registered = tools.get(name)
        if registered is not None and hasattr(registered, "function"):
            registered.function = callback
    return guard
