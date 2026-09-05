"""Narration audio for a walkthrough step.

Three engines, and the order matters more than the list.

`edge` is the default: Microsoft's neural voices, free, no key, and — the part
that matters here — it has **Kenyan** voices. `en-KE-AsiliaNeural` reads a
Grade 9 maths step in the accent the class actually speaks, and
`sw-KE-ZuriNeural` reads Kiswahili properly rather than as English words with
Swahili spelling. Neither the paid engine below nor the browser has either.

`openai` stays for anyone who wants those voices and has a key. It is not the
default because it costs a call per step to produce what edge produces free.

`piper` is there for a machine with no network at all: small, ONNX, runs on a
Raspberry Pi. It needs a voice model downloaded per language, so it is opt-in.

`none` is honest rather than empty: the player reads the step with the device's
own voice, and falls back to the step timer where the device has no voice for
that language. So a walkthrough is never silent because a synthesiser was
unavailable.

None of them is as good as a teacher. A step whose audio has been UPLOADED —
somebody's actual voice, recorded once — is never re-synthesised, because the
check below returns any file already at that key before it reaches an engine.
That is the intended path for the lessons that matter most.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from ...infra.storage import object_storage
from ...settings import settings

logger = logging.getLogger("cbc-tts-service")

# The voice for a language, chosen for who is listening rather than for how it
# scores. Kenyan first, then the nearest African English, then the language's
# own default.
VOICES: dict[str, str] = {
    "en": "en-KE-AsiliaNeural",
    "sw": "sw-KE-ZuriNeural",
    "ar": "ar-EG-SalmaNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "hi": "hi-IN-SwaraNeural",
}

# Which learning areas are taught IN another language. A maths lesson is
# narrated in English whatever else is on the timetable.
_SUBJECT_LANGUAGE: tuple[tuple[str, str], ...] = (
    ("kiswahili", "sw"),
    ("arabic", "ar"),
    ("french", "fr"),
    ("german", "de"),
    ("mandarin", "zh"),
    ("hindu religious", "hi"),
)


def language_for(subject: str = "") -> str:
    lowered = (subject or "").lower()
    for needle, code in _SUBJECT_LANGUAGE:
        if needle in lowered:
            return code
    return "en"


def voice_for(subject: str = "") -> str:
    configured = (getattr(settings, "tts_voice", "") or "").strip()
    # A configured voice that names a locale is a deliberate choice; the
    # OpenAI-style names ("alloy") are not edge voices and must not be passed on.
    if configured and re.match(r"^[a-z]{2}-[A-Z]{2}-", configured):
        return configured
    return VOICES.get(language_for(subject), VOICES["en"])


class TtsService:
    """Speech for one step, stored where the player can fetch it."""

    def __init__(self, voice: str = "", speed: float = 1.0) -> None:
        self.voice = voice
        self.speed = speed

    # ── engines ─────────────────────────────────────────────────────────────

    def _edge(self, text: str, voice: str) -> bytes | None:
        """Microsoft's neural voices. Free, no key, and Kenyan."""
        try:
            import edge_tts
        except ImportError:
            logger.info("edge-tts is not installed; no free engine available.")
            return None

        async def synthesise() -> bytes:
            audio = bytearray()
            communicate = edge_tts.Communicate(text, voice)
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    audio.extend(chunk["data"])
            return bytes(audio)

        try:
            return asyncio.run(synthesise()) or None
        except RuntimeError:
            # Already inside a loop — run it on its own so a worker that is
            # async does not have to care which engine it called.
            try:
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(synthesise()) or None
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("edge-tts failed: %s", exc)
                return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("edge-tts failed: %s", exc)
            return None

    def _piper(self, text: str, voice: str) -> bytes | None:
        """Piper: small, ONNX, runs on a Raspberry Pi, no network at all.

        Not installed by default because it needs a voice model downloaded per
        language. Set TTS_ENGINE=piper and PIPER_MODEL once you have one.
        """
        try:
            from piper import PiperVoice  # type: ignore
        except ImportError:
            logger.info("TTS_ENGINE=piper but piper-tts is not installed.")
            return None

        import io
        import wave

        model = (getattr(settings, "piper_model", "") or "").strip()
        if not model:
            logger.warning("TTS_ENGINE=piper needs PIPER_MODEL set to a .onnx voice.")
            return None
        try:
            loaded = PiperVoice.load(model)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as handle:
                loaded.synthesize(text, handle)
            return buffer.getvalue() or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("piper failed: %s", exc)
            return None

    def _openai(self, text: str) -> bytes | None:
        if not settings.openai_api_key:
            return None
        try:
            with httpx.Client(timeout=25.0) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}",
                             "Content-Type": "application/json"},
                    json={"model": "tts-1", "input": text[:4000],
                          "voice": getattr(settings, "tts_voice", "") or "alloy",
                          "speed": getattr(settings, "tts_speed", 1.0) or 1.0,
                          "response_format": "mp3"},
                )
            if response.status_code == 200:
                return response.content
            logger.warning("OpenAI TTS returned %d: %s",
                           response.status_code, response.text[:200])
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI TTS failed: %s", exc)
        return None

    # ── the one thing callers use ───────────────────────────────────────────

    def synthesize_step_audio(
        self,
        text: str,
        simulation_id: str,
        step_index: int,
        subject: str = "",
    ) -> str | None:
        """Speak one step and store it. Returns the URL, or None.

        None is not a failure to hide: the player reads the step aloud with the
        device's own voice when there is no file, so a walkthrough with no
        audio at all is still narrated and still advances on the words.
        """
        clean = (text or "").strip()
        if not clean:
            return None

        object_key = f"simulations/{simulation_id}/step_{step_index}.mp3"
        if object_storage.object_exists(object_key):
            return f"{settings.minio_public_base_url}/{settings.minio_bucket}/{object_key}"

        engine = (getattr(settings, "tts_engine", "edge") or "edge").lower()
        if engine == "none":
            return None

        voice = self.voice or voice_for(subject)

        # Named engines, tried in the order the operator asked for, then the
        # free one. Adding another — Kokoro, XTTS, anything self-hosted — is a
        # method and a line here; no call site changes.
        order = {
            "edge": ("edge", "openai"),
            "openai": ("openai", "edge"),
            "piper": ("piper", "edge"),
        }.get(engine, ("edge",))

        audio = None
        for name in order:
            if name == "edge":
                audio = self._edge(clean, voice)
            elif name == "openai":
                audio = self._openai(clean)
            elif name == "piper":
                audio = self._piper(clean, voice)
            if audio:
                break

        if not audio:
            return None

        try:
            saved = object_storage.save_bytes(object_key, audio, "audio/mpeg")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store narration for %s step %d: %s",
                           simulation_id, step_index, exc)
            return None

        logger.info("Narrated %s step %d with %s (%d bytes)",
                    simulation_id, step_index, voice, len(audio))
        return saved


tts_service = TtsService()
