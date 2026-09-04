from __future__ import annotations

import logging
from typing import Any

import httpx

from ...infra.storage import object_storage
from ...settings import settings

logger = logging.getLogger("cbc-tts-service")


class TtsService:
    """Text-to-Speech audio synthesizer that stores MP3 clips in MinIO."""

    def __init__(self, voice: str = "alloy", speed: float = 1.0) -> None:
        self.voice = voice
        self.speed = speed

    def synthesize_step_audio(
        self,
        text: str,
        simulation_id: str,
        step_index: int,
    ) -> str | None:
        """Synthesizes narration text to MP3 and saves it to MinIO.
        
        Returns the public MinIO URL of the audio file, or None if TTS is unavailable.
        """
        if not text or not text.strip():
            return None

        clean_text = text.strip()
        object_key = f"simulations/{simulation_id}/step_{step_index}.mp3"

        # Check if already generated
        if object_storage.object_exists(object_key):
            return f"{settings.minio_public_base_url}/{settings.minio_bucket}/{object_key}"

        # 1. Try OpenAI TTS if API key is present
        if settings.openai_api_key:
            try:
                url = "https://api.openai.com/v1/audio/speech"
                headers = {
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "tts-1",
                    "input": clean_text[:4000],
                    "voice": getattr(settings, "tts_voice", self.voice) or "alloy",
                    "speed": getattr(settings, "tts_speed", self.speed) or 1.0,
                    "response_format": "mp3",
                }
                with httpx.Client(timeout=25.0) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        audio_bytes = resp.content
                        saved_url = object_storage.save_bytes(object_key, audio_bytes, "audio/mpeg")
                        logger.info("Synthesized audio for %s step %d (%d bytes)", simulation_id, step_index, len(audio_bytes))
                        return saved_url
                    logger.warning("OpenAI TTS returned status %d: %s", resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.warning("TTS generation failed for %s step %d: %s", simulation_id, step_index, exc)

        return None


tts_service = TtsService()
