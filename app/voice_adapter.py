from __future__ import annotations

import hashlib
import io
import math
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from array import array
from pathlib import Path
from typing import Any


VOICE_PROFILES: dict[str, dict[str, Any]] = {
    "sentinel": {
        "id": "sentinel",
        "name": "DPN Sentinel",
        "gender": "male",
        "engine": "piper",
        "model": "en_US-ryan-high",
        "fallback_models": ["en_GB-alan-medium"],
        "locale": "en-GB",
        "style": "Clear, natural male operations narrator with a British-inspired command cadence",
        "tone": "Confident and clean, with natural pacing, firm diction and reduced synthetic grain",
        "description": "A higher-quality original male assistant voice tuned for clear conversation and narration. It is not an imitation of any actor or copyrighted character.",
        "default_speed": 0.89,
        "default_tone": "clear",
        "system_rate": 170,
        "sentence_pause_ms": 225,
        "paragraph_pause_ms": 470,
        "clause_pause_ms": 115,
        "noise_scale": 0.31,
        "noise_w_scale": 0.39,
        "high_cut_hz": 11200,
        "softness": 0.10,
        "compression_threshold": 0.84,
        "compression_ratio": 1.45,
        "target_peak": 0.77,
        "max_makeup_gain": 1.02,
        "fade_ms": 7,
    },
    "aurora": {
        "id": "aurora",
        "name": "DPN Aurora",
        "gender": "female",
        "engine": "piper",
        "model": "en_GB-jenny_dioco-medium",
        "locale": "en-GB",
        "style": "Soft, gentle and unhurried female narrator and conversational companion",
        "tone": "Soft, reassuring and intimate, with lighter peaks, longer breathing room and relaxed phrasing",
        "description": "A distinctly gentle local neural voice tuned for comfortable conversation and long-form reading.",
        "default_speed": 0.78,
        "default_tone": "gentle",
        "system_rate": 142,
        "sentence_pause_ms": 390,
        "paragraph_pause_ms": 790,
        "clause_pause_ms": 190,
        "noise_scale": 0.30,
        "noise_w_scale": 0.40,
        "high_cut_hz": 6800,
        "softness": 0.68,
        "compression_threshold": 0.60,
        "compression_ratio": 3.1,
        "target_peak": 0.68,
        "fade_ms": 14,
    },
    "system": {
        "id": "system",
        "name": "System Voice",
        "gender": "system",
        "engine": "pyttsx3",
        "model": None,
        "locale": "system",
        "style": "Operating-system fallback voice",
        "tone": "Uses the closest locally installed system voice and a reduced reading rate",
        "description": "Uses an installed operating-system voice when Piper is unavailable.",
        "default_speed": 0.90,
        "default_tone": "natural",
        "system_rate": 150,
        "sentence_pause_ms": 260,
        "paragraph_pause_ms": 560,
        "clause_pause_ms": 130,
    },
}


VOICE_TONE_PRESETS: dict[str, dict[str, dict[str, float]]] = {
    "sentinel": {
        "clear": {"high_cut_hz": 11800, "softness": 0.06, "compression_threshold": 0.86, "compression_ratio": 1.35, "target_peak": 0.76, "max_makeup_gain": 1.01},
        "natural": {"high_cut_hz": 10800, "softness": 0.11, "compression_threshold": 0.83, "compression_ratio": 1.5, "target_peak": 0.77, "max_makeup_gain": 1.02},
        "warm": {"high_cut_hz": 9000, "softness": 0.18, "compression_threshold": 0.80, "compression_ratio": 1.65, "target_peak": 0.75, "max_makeup_gain": 1.02},
    },
    "aurora": {
        "gentle": {"high_cut_hz": 7000, "softness": 0.58, "compression_threshold": 0.64, "compression_ratio": 2.5, "target_peak": 0.67, "max_makeup_gain": 1.01},
        "natural": {"high_cut_hz": 8000, "softness": 0.42, "compression_threshold": 0.69, "compression_ratio": 2.0, "target_peak": 0.70, "max_makeup_gain": 1.02},
    },
    "system": {"natural": {}},
}


class VoiceAdapter:
    """Offline STT/TTS with narration-oriented Piper voices and a system fallback.

    The adapter deliberately provides original named voice profiles rather than
    imitating a real person. Piper models are installed separately into the
    local data directory so the base release remains small.
    """

    AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".wma"}

    def __init__(self, workspace: Path, data_dir: Path | None = None):
        self.workspace = workspace.resolve()
        self.data_dir = (data_dir or (self.workspace.parent / "data")).resolve()
        self.output_dir = self.workspace / "generated" / "voice"
        self.upload_dir = self.workspace / "uploads" / "voice"
        self.voice_dir = self.data_dir / "voices"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self._piper_cache: dict[tuple[str, bool], Any] = {}
        self._whisper_cache: dict[tuple[str, str, str], Any] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _module_available(name: str) -> bool:
        try:
            __import__(name)
            return True
        except Exception:
            return False

    def _model_path(self, model: str) -> Path:
        return self.voice_dir / f"{model}.onnx"

    def _model_installed(self, model: str | None) -> bool:
        if not model:
            return False
        path = self._model_path(model)
        return path.exists() and path.with_suffix(".onnx.json").exists()

    def _active_model(self, profile: dict[str, Any]) -> str | None:
        primary = profile.get("model")
        if self._model_installed(primary):
            return str(primary)
        for fallback in profile.get("fallback_models", []):
            if self._model_installed(str(fallback)):
                return str(fallback)
        return str(primary) if primary else None

    @staticmethod
    def _tone_profile(profile: dict[str, Any], tone: str | None) -> dict[str, Any]:
        voice_id = str(profile.get("id", "system"))
        selected = str(tone or profile.get("default_tone", "natural"))
        presets = VOICE_TONE_PRESETS.get(voice_id, {})
        if selected not in presets:
            selected = str(profile.get("default_tone", "natural"))
        return {**profile, **presets.get(selected, {}), "active_tone": selected}

    def _profile_payload(self, profile: dict[str, Any]) -> dict[str, Any]:
        model = profile.get("model")
        installed = profile["engine"] == "pyttsx3" and self._module_available("pyttsx3")
        active_model = None
        if model:
            active_model = self._active_model(profile)
            installed = self._model_installed(active_model)
        primary_installed = self._model_installed(str(model)) if model else installed
        using_fallback = bool(active_model and model and active_model != model)
        return {
            **profile,
            "installed": bool(installed),
            "primary_installed": bool(primary_installed),
            "active_model": active_model,
            "using_fallback_model": using_fallback,
            "update_available": bool(model and installed and not primary_installed),
            "tone_options": list(VOICE_TONE_PRESETS.get(str(profile.get("id")), {"natural": {}}).keys()),
        }

    def profiles(self) -> dict[str, Any]:
        return {
            "ok": True,
            "profiles": [self._profile_payload(profile) for profile in VOICE_PROFILES.values()],
            "default_voice": "sentinel",
            "narrator_voice": "aurora",
            "reading_engine": "adaptive narration clarity engine v3",
        }

    def status(self) -> dict[str, Any]:
        piper_available = self._module_available("piper")
        whisper_available = self._module_available("faster_whisper")
        system_tts = self._module_available("pyttsx3")
        installed_profiles = [item["id"] for item in self.profiles()["profiles"] if item["installed"]]
        return {
            "ok": True,
            "stt": whisper_available,
            "tts": bool(piper_available or system_tts),
            "piper": piper_available,
            "system_tts": system_tts,
            "installed_profiles": installed_profiles,
            "voice_dir": str(self.voice_dir),
            "output_dir": self.output_dir.relative_to(self.workspace).as_posix(),
            "narration_processing": True,
        }

    def install_profile(self, voice_id: str) -> dict[str, Any]:
        profile = VOICE_PROFILES.get(voice_id)
        if not profile:
            return {"ok": False, "error": f"Unknown voice profile: {voice_id}"}
        if profile["engine"] == "pyttsx3":
            return {"ok": self._module_available("pyttsx3"), "voice": self._profile_payload(profile)}
        if not self._module_available("piper"):
            return {"ok": False, "error": "Piper is not installed. Run install_voice_windows.bat or install requirements-voice.txt."}
        model = str(profile["model"])
        if self._model_installed(model):
            return {"ok": True, "voice": self._profile_payload(profile), "already_installed": True}
        command = [sys.executable, "-m", "piper.download_voices", "--data-dir", str(self.voice_dir), model]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Voice download timed out after 30 minutes."}
        if result.returncode:
            return {"ok": False, "error": (result.stderr or result.stdout)[-6000:], "command": command}
        installed = self._model_path(model).exists()
        return {
            "ok": installed,
            "voice": self._profile_payload(profile),
            "output": (result.stdout or result.stderr)[-4000:],
            "error": None if installed else "Piper completed but the expected voice model was not found.",
        }

    def _resolve(self, path: str) -> Path:
        target = (self.workspace / path).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Audio path is outside the workspace") from exc
        return target

    @staticmethod
    def _speech_text(text: str) -> str:
        value = text.replace("\r", "\n")
        value = re.sub(r"```[\s\S]*?```", " Code block omitted from speech. ", value)
        value = re.sub(r"`([^`]+)`", r"\1", value)
        value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
        value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
        value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*[-*+]\s+", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*\d+[.)]\s+", "", value, flags=re.MULTILINE)
        value = value.replace("**", "").replace("__", "").replace("~~", "")
        value = re.sub(r"https?://\S+", " link ", value)
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n[ \t]+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()[:100_000]

    @staticmethod
    def _split_long_phrase(phrase: str, max_chars: int = 260) -> list[str]:
        phrase = phrase.strip()
        if len(phrase) <= max_chars:
            return [phrase] if phrase else []
        parts = re.split(r"(?<=[;:—])\s+", phrase)
        if len(parts) == 1:
            parts = re.split(r"(?<=,)\s+", phrase)
        output: list[str] = []
        current = ""
        for part in parts:
            candidate = f"{current} {part}".strip()
            if current and len(candidate) > max_chars:
                output.append(current)
                current = part.strip()
            else:
                current = candidate
        if current:
            output.append(current)
        if len(output) == 1 and len(output[0]) > max_chars:
            words = output[0].split()
            output = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > max_chars:
                    output.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                output.append(current)
        return output

    @classmethod
    def _narration_units(cls, text: str, profile: dict[str, Any]) -> list[tuple[str, int]]:
        """Split text into readable phrases with explicit breathing room."""
        sentence_pause = int(profile.get("sentence_pause_ms", 280))
        paragraph_pause = int(profile.get("paragraph_pause_ms", 620))
        clause_pause = int(profile.get("clause_pause_ms", 150))
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        units: list[tuple[str, int]] = []
        for paragraph_index, paragraph in enumerate(paragraphs):
            lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            paragraph_units: list[str] = []
            for line in lines:
                sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", line) if item.strip()]
                for sentence in sentences or [line]:
                    paragraph_units.extend(cls._split_long_phrase(sentence))
            for index, unit in enumerate(paragraph_units):
                is_last = index == len(paragraph_units) - 1
                if is_last:
                    pause = paragraph_pause if paragraph_index < len(paragraphs) - 1 else max(90, sentence_pause // 2)
                elif unit.endswith((";", ":", "—")):
                    pause = clause_pause
                else:
                    pause = sentence_pause
                units.append((unit, pause))
        return units or [(text.strip(), max(90, sentence_pause // 2))]

    def _load_piper(self, model: str, use_cuda: bool = False) -> Any:
        key = (model, bool(use_cuda))
        with self._lock:
            if key in self._piper_cache:
                return self._piper_cache[key]
            from piper import PiperVoice

            voice = PiperVoice.load(str(self._model_path(model)), use_cuda=bool(use_cuda))
            self._piper_cache[key] = voice
            return voice

    @staticmethod
    def _pcm16_array(frames: bytes) -> array:
        samples = array("h")
        samples.frombytes(frames)
        if sys.byteorder != "little":
            samples.byteswap()
        return samples

    @staticmethod
    def _pcm16_bytes(samples: array) -> bytes:
        result = array("h", samples)
        if sys.byteorder != "little":
            result.byteswap()
        return result.tobytes()

    @classmethod
    def _soften_pcm16(cls, frames: bytes, sample_rate: int, channels: int, profile: dict[str, Any]) -> bytes:
        """Reduce brittle high-frequency energy and sharp peaks without extra packages."""
        if not frames or channels < 1 or sample_rate < 1:
            return frames
        samples = cls._pcm16_array(frames)
        if not samples:
            return frames
        cutoff = max(2500.0, min(float(profile.get("high_cut_hz", 8500)), sample_rate * 0.46))
        alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / sample_rate)
        softness = max(0.0, min(float(profile.get("softness", 0.4)), 0.9))
        threshold = max(0.30, min(float(profile.get("compression_threshold", 0.7)), 0.95)) * 32767.0
        ratio = max(1.0, min(float(profile.get("compression_ratio", 2.4)), 8.0))
        states = [0.0] * channels
        processed = array("h")
        for index, raw in enumerate(samples):
            channel = index % channels
            filtered = states[channel] + alpha * (float(raw) - states[channel])
            states[channel] = filtered
            value = float(raw) * (1.0 - softness) + filtered * softness
            magnitude = abs(value)
            if magnitude > threshold:
                value = math.copysign(threshold + (magnitude - threshold) / ratio, value)
            processed.append(int(max(-32768, min(32767, round(value)))))

        peak = max(abs(value) for value in processed) or 1
        target_peak = max(0.35, min(float(profile.get("target_peak", 0.8)), 0.96)) * 32767.0
        max_makeup_gain = max(1.0, min(float(profile.get("max_makeup_gain", 1.03)), 1.16))
        gain = min(max_makeup_gain, target_peak / peak)
        if gain < 0.995 or gain > 1.005:
            for index, value in enumerate(processed):
                processed[index] = int(max(-32768, min(32767, round(value * gain))))

        fade_frames = int(sample_rate * max(0.0, min(float(profile.get("fade_ms", 10)), 50.0)) / 1000.0)
        total_frames = len(processed) // channels
        fade_frames = min(fade_frames, total_frames // 3)
        for frame_index in range(fade_frames):
            fade_in = (frame_index + 1) / max(1, fade_frames)
            fade_out = (fade_frames - frame_index) / max(1, fade_frames)
            for channel in range(channels):
                start = frame_index * channels + channel
                end = (total_frames - fade_frames + frame_index) * channels + channel
                processed[start] = int(processed[start] * fade_in)
                processed[end] = int(processed[end] * fade_out)
        return cls._pcm16_bytes(processed)

    def _speak_piper(
        self,
        text: str,
        target: Path,
        profile: dict[str, Any],
        speed: float,
        volume: float,
        use_cuda: bool,
    ) -> dict[str, Any]:
        from piper import SynthesisConfig

        model = self._active_model(profile)
        if not model:
            raise FileNotFoundError(f"Voice profile {profile['name']} has no configured model")
        model_path = self._model_path(model)
        config_path = model_path.with_suffix(".onnx.json")
        if not model_path.exists() or not config_path.exists():
            raise FileNotFoundError(f"Voice profile {profile['name']} is not installed")
        voice = self._load_piper(model, use_cuda)
        syn_config = SynthesisConfig(
            volume=max(0.1, min(float(volume), 2.0)),
            length_scale=max(0.70, min(1.75, 1.0 / max(0.57, min(float(speed), 1.42)))),
            noise_scale=max(0.1, min(float(profile.get("noise_scale", 0.45)), 1.0)),
            noise_w_scale=max(0.1, min(float(profile.get("noise_w_scale", 0.55)), 1.0)),
            normalize_audio=True,
        )
        units = self._narration_units(text, profile)
        output: wave.Wave_write | None = None
        output_params: tuple[int, int, int] | None = None
        total_pause_ms = 0
        try:
            for unit, pause_ms in units:
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav_file:
                    voice.synthesize_wav(unit, wav_file, syn_config=syn_config)
                buffer.seek(0)
                with wave.open(buffer, "rb") as generated:
                    channels = generated.getnchannels()
                    sample_width = generated.getsampwidth()
                    sample_rate = generated.getframerate()
                    frames = generated.readframes(generated.getnframes())
                if sample_width != 2:
                    raise RuntimeError(f"Unsupported Piper sample width: {sample_width * 8}-bit")
                params = (channels, sample_width, sample_rate)
                if output is None:
                    output = wave.open(str(target), "wb")
                    output.setnchannels(channels)
                    output.setsampwidth(sample_width)
                    output.setframerate(sample_rate)
                    output_params = params
                elif params != output_params:
                    raise RuntimeError("Piper returned inconsistent WAV formats between narration segments")
                softened = self._soften_pcm16(frames, sample_rate, channels, profile)
                output.writeframesraw(softened)
                bounded_pause = max(0, min(int(pause_ms), 2000))
                if bounded_pause:
                    silence_frames = int(sample_rate * bounded_pause / 1000.0)
                    output.writeframesraw(b"\x00" * silence_frames * sample_width * channels)
                    total_pause_ms += bounded_pause
        finally:
            if output is not None:
                output.close()
        return {
            "segments": len(units),
            "inserted_pause_ms": total_pause_ms,
            "processing": "sentence-aware pauses, de-harsh smoothing, gentle compression and click-safe fades",
        }

    @staticmethod
    def _choose_system_voice(engine: Any, gender: str) -> None:
        voices = engine.getProperty("voices") or []
        desired = "female" if gender == "female" else "male"
        preferred_terms = ("zira", "hazel", "susan", "female") if desired == "female" else ("david", "mark", "george", "male")
        for term in preferred_terms:
            for voice in voices:
                blob = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
                if term in blob:
                    engine.setProperty("voice", voice.id)
                    return
        if voices:
            engine.setProperty("voice", voices[0].id)

    def _speak_system(self, text: str, target: Path, profile: dict[str, Any], speed: float, volume: float) -> dict[str, Any]:
        import pyttsx3

        engine = pyttsx3.init()
        self._choose_system_voice(engine, str(profile.get("gender", "system")))
        base_rate = int(profile.get("system_rate", 150))
        engine.setProperty("rate", int(max(80, min(240, base_rate * (speed / max(0.55, float(profile.get("default_speed", 0.86))))))))
        engine.setProperty("volume", max(0.1, min(float(volume), 1.0)))
        engine.save_to_file(text, str(target))
        engine.runAndWait()
        return {"segments": 1, "inserted_pause_ms": 0, "processing": "system voice with reduced narration rate"}

    def speak(
        self,
        text: str,
        filename: str = "dpn-ai-speech.wav",
        rate: int = 175,
        voice_id: str = "sentinel",
        speed: float | None = None,
        volume: float = 1.0,
        use_cuda: bool = False,
        fallback: bool = True,
        tone: str | None = None,
    ) -> dict[str, Any]:
        profile = VOICE_PROFILES.get(voice_id)
        if not profile:
            return {"ok": False, "error": f"Unknown voice profile: {voice_id}"}
        profile = self._tone_profile(profile, tone)
        clean_text = self._speech_text(text)
        if not clean_text:
            return {"ok": False, "error": "There is no readable text to synthesize."}
        target = self.output_dir / Path(filename).with_suffix(".wav").name
        target.unlink(missing_ok=True)
        actual_speed = float(speed if speed is not None else profile.get("default_speed", max(0.55, min(1.8, rate / 175))))
        actual_speed = max(0.57, min(actual_speed, 1.42))
        started = time.monotonic()
        engine_used = str(profile["engine"])
        delivery: dict[str, Any] = {}
        try:
            if profile["engine"] == "piper":
                delivery = self._speak_piper(clean_text, target, profile, actual_speed, volume, use_cuda)
            else:
                delivery = self._speak_system(clean_text, target, profile, actual_speed, volume)
        except Exception as exc:
            if not fallback or not self._module_available("pyttsx3"):
                return {
                    "ok": False,
                    "error": str(exc),
                    "voice": self._profile_payload(profile),
                    "install_required": profile["engine"] == "piper" and not self._profile_payload(profile)["installed"],
                }
            try:
                target.unlink(missing_ok=True)
                fallback_profile = {**profile, "engine": "pyttsx3"}
                delivery = self._speak_system(clean_text, target, fallback_profile, actual_speed, volume)
                engine_used = "pyttsx3-fallback"
            except Exception as fallback_exc:
                target.unlink(missing_ok=True)
                return {"ok": False, "error": f"Neural TTS failed: {exc}. System fallback failed: {fallback_exc}"}
        if not target.exists() or target.stat().st_size < 44:
            return {"ok": False, "error": "The speech engine did not create a valid WAV file."}
        return {
            "ok": True,
            "path": target.relative_to(self.workspace).as_posix(),
            "voice": self._profile_payload(profile),
            "engine": engine_used,
            "speed": actual_speed,
            "volume": volume,
            "tone": profile.get("active_tone", profile.get("default_tone", "natural")),
            "delivery": delivery,
            "characters": len(clean_text),
            "size_bytes": target.stat().st_size,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "mime_type": "audio/wav",
        }

    def _whisper_model(self, model_size: str, device: str, compute_type: str) -> Any:
        key = (model_size, device, compute_type)
        with self._lock:
            if key not in self._whisper_cache:
                from faster_whisper import WhisperModel

                self._whisper_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
            return self._whisper_cache[key]

    def transcribe(
        self,
        path: str,
        model_size: str = "base",
        language: str | None = None,
        initial_prompt: str | None = None,
        device: str = "auto",
        compute_type: str = "int8",
    ) -> dict[str, Any]:
        try:
            target = self._resolve(path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": "Audio file not found"}
        if not self._module_available("faster_whisper"):
            return {"ok": False, "error": "faster-whisper is not installed. Run install_voice_windows.bat."}
        started = time.monotonic()
        try:
            model = self._whisper_model(model_size, device, compute_type)
            segments, info = model.transcribe(
                str(target),
                language=language or None,
                initial_prompt=initial_prompt or None,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 180},
                beam_size=5,
                word_timestamps=False,
            )
            segment_list = []
            for segment in segments:
                segment_text = segment.text.strip()
                if segment_text:
                    segment_list.append({"start": round(float(segment.start), 3), "end": round(float(segment.end), 3), "text": segment_text})
            transcript_text = " ".join(item["text"] for item in segment_list).strip()
        except ValueError as exc:
            if "empty" in str(exc).lower() or "max()" in str(exc).lower():
                return {"ok": False, "error": "No speech was detected in the recording."}
            return {"ok": False, "error": f"Transcription failed: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"Transcription failed: {type(exc).__name__}: {exc}"}
        return {
            "ok": True,
            "text": transcript_text,
            "segments": segment_list,
            "language": getattr(info, "language", language),
            "probability": getattr(info, "language_probability", None),
            "duration": getattr(info, "duration", None),
            "model": model_size,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "path": target.relative_to(self.workspace).as_posix(),
        }

    def save_upload(self, data: bytes, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".webm"
        if suffix not in self.AUDIO_SUFFIXES:
            suffix = ".webm"
        digest = hashlib.sha256(data).hexdigest()[:16]
        target = self.upload_dir / f"voice-{int(time.time())}-{digest}{suffix}"
        target.write_bytes(data)
        return target.relative_to(self.workspace).as_posix()

    def clear_caches(self) -> dict[str, Any]:
        with self._lock:
            piper_count = len(self._piper_cache)
            whisper_count = len(self._whisper_cache)
            self._piper_cache.clear()
            self._whisper_cache.clear()
        return {"ok": True, "piper_models_released": piper_count, "whisper_models_released": whisper_count}

    def diagnostics(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.voice_dir)
        return {
            **self.status(),
            "profiles": self.profiles()["profiles"],
            "cache": {"piper": len(self._piper_cache), "whisper": len(self._whisper_cache)},
            "disk_free_bytes": usage.free,
        }