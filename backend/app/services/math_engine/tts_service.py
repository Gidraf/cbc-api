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


# Microsoft moved speech off the host edge-tts 7.2.8 calls: since October 2026
# speech.platform.bing.com answers synthesis with 403 (rany2/edge-tts#490),
# while api.msedgeservices.com — where Edge itself now speaks — accepts the
# same token. EDGE_TTS_WSS_URL overrides it if Microsoft moves again.
_EDGE_WSS = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?Ocp-Apim-Subscription-Key={token}"


def _point_edge_at_current_host() -> None:
    import os

    try:
        import edge_tts.communicate as communicate
        import edge_tts.constants as constants
    except ImportError:
        return
    url = os.getenv("EDGE_TTS_WSS_URL", "").strip() or _EDGE_WSS.format(token=constants.TRUSTED_CLIENT_TOKEN)
    if "speech.platform.bing.com" in communicate.WSS_URL or os.getenv("EDGE_TTS_WSS_URL"):
        communicate.WSS_URL = constants.WSS_URL = url


def _rate() -> str:
    from ..platform_settings import get

    rate = str(get("narration_rate", "-8%") or "").strip() or "+0%"
    if not re.match(r"^[+-]\d{1,2}%$", rate):
        rate = rate if rate.startswith(("+", "-")) else f"+{rate}"
        rate = rate if rate.endswith("%") else f"{rate}%"
    return rate if re.match(r"^[+-]\d{1,2}%$", rate) else "+0%"


# Voices offered when the network cannot list Microsoft's: the ones a Kenyan
# classroom is most likely to want.
FALLBACK_VOICES: list[dict[str, str]] = [
    {"name": "en-KE-AsiliaNeural", "gender": "Female", "locale": "en-KE"},
    {"name": "en-KE-ChilembaNeural", "gender": "Male", "locale": "en-KE"},
    {"name": "en-US-AvaMultilingualNeural", "gender": "Female", "locale": "en-US"},
    {"name": "en-US-EmmaMultilingualNeural", "gender": "Female", "locale": "en-US"},
    {"name": "en-US-AndrewMultilingualNeural", "gender": "Male", "locale": "en-US"},
    {"name": "en-GB-SoniaNeural", "gender": "Female", "locale": "en-GB"},
    {"name": "en-ZA-LeahNeural", "gender": "Female", "locale": "en-ZA"},
    {"name": "en-NG-EzinneNeural", "gender": "Female", "locale": "en-NG"},
    {"name": "en-TZ-ImaniNeural", "gender": "Female", "locale": "en-TZ"},
    {"name": "sw-KE-ZuriNeural", "gender": "Female", "locale": "sw-KE"},
    {"name": "sw-KE-RafikiNeural", "gender": "Male", "locale": "sw-KE"},
]
_VOICE_LIST: dict[str, Any] = {}


def available_voices() -> list[dict[str, str]]:
    """English and Kiswahili voices Microsoft offers, listed once a day."""
    import time

    if _VOICE_LIST.get("at", 0) > time.time() - 86400:
        return _VOICE_LIST["voices"]
    voices: list[dict[str, str]] = []
    try:
        import edge_tts

        found = asyncio.run(edge_tts.list_voices())
        voices = [{"name": v["ShortName"], "gender": v.get("Gender", ""), "locale": v.get("Locale", "")}
                  for v in found if str(v.get("Locale", "")).split("-")[0] in ("en", "sw")]
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not list Microsoft voices (%s); offering the usual ones.", exc)
    voices = sorted(voices or FALLBACK_VOICES, key=lambda v: (not v["locale"].endswith("KE"), v["locale"], v["name"]))
    _VOICE_LIST.update(at=time.time(), voices=voices)
    return voices


# The sciences are explained in a British or American voice (the owner's
# choice): the clearest for scientific words. Microsoft's "Multilingual"
# voices are its most natural; Sonia, Libby, Ryan and Thomas are British.
SCIENCE_VOICES = {
    "british": {"female": ["en-GB-SoniaNeural", "en-GB-LibbyNeural"], "male": ["en-GB-RyanNeural", "en-GB-ThomasNeural"]},
    "american": {"female": ["en-US-AvaMultilingualNeural", "en-US-EmmaMultilingualNeural"],
                 "male": ["en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural"]},
}
_SCIENCE = ("science", "chemistry", "physics", "biology")


def is_science(subject: str = "") -> bool:
    low = (subject or "").lower()
    return any(w in low for w in _SCIENCE)


def science_voice(gender: str = "female", key: str = "") -> str:
    """A British or American voice for a science video (Settings → Science accent), the same each time for one item."""
    import hashlib

    try:
        from ..platform_settings import get

        accent = str(get("science_accent", "both") or "both").lower()
    except Exception:  # noqa: BLE001
        accent = "both"
    g = "male" if str(gender).lower().startswith("m") else "female"
    pool = (SCIENCE_VOICES["british"][g] + SCIENCE_VOICES["american"][g]) if accent not in SCIENCE_VOICES \
        else SCIENCE_VOICES[accent][g]
    n = int(hashlib.sha256(f"sci:{key}".encode()).hexdigest(), 16)
    return pool[n % len(pool)]


def voice_for(subject: str = "") -> str:
    try:
        from ..platform_settings import get

        chosen = str(get("narration_voice", "") or "").strip()
    except Exception:  # noqa: BLE001
        chosen = ""
    # The console's choice reads English lessons; a Kiswahili or French
    # lesson keeps a voice that speaks its language.
    if chosen and re.match(r"^[a-z]{2}-[A-Z]{2}-", chosen) and language_for(subject) == chosen[:2]:
        return chosen
    if is_science(subject):
        return science_voice("female", subject)
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

        _point_edge_at_current_host()
        try:
            rate = _rate()
        except Exception:  # noqa: BLE001
            rate = "+0%"

        # "name|pitch|rate": a voice raised or lowered (a student, an older teacher).
        parts = (voice or "").split("|")
        voice = parts[0]
        pitch = parts[1] if len(parts) > 1 and parts[1] else "+0Hz"
        if len(parts) > 2 and parts[2]:
            rate = parts[2]

        async def synthesise() -> bytes:
            audio = bytearray()
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
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

    def speak_bytes(self, text: str, voice: str = "") -> bytes | None:
        """The audio itself, not stored — for a caller that cuts its own
        file (a whiteboard video). Same engine order as a stored step."""
        from ..speech_text import for_speech

        voice = voice or self.voice or voice_for("")
        clean = for_speech((text or "").strip(), (voice or "en")[:2])
        engine = (getattr(settings, "tts_engine", "edge") or "edge").lower()
        if not clean or engine == "none":
            return None
        if engine == "openai":
            return self._openai(clean) or self._edge(clean, voice)
        if engine == "piper":
            return self._piper(clean, voice) or self._edge(clean, voice)
        return self._edge(clean, voice) or self._openai(clean)

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
        from ..speech_text import for_speech

        clean = for_speech((text or "").strip(), language_for(subject))
        if not clean:
            return None

        object_key = f"simulations/{simulation_id}/step_{step_index}.mp3"
        if object_storage.object_exists(object_key):
            from ...infra.storage import public_object_url

            return public_object_url(object_key)

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
