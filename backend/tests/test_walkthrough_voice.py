"""Narrating a walkthrough with the voice the device already has.

The player had two tiers: a synthesised MP3, or — with no file — a timer that
advanced on a word count. The middle is where nearly every walkthrough sits,
because narration costs a provider call per step to synthesise and a file per
step to store, so most steps had no recording and were read in silence.

Every browser can already speak. It costs nothing, needs no key, stores
nothing, works offline, and syncs by construction: `onend` fires when the
sentence finishes, which is exactly when the step should advance.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend-web"
SPEECH = (FRONTEND / "src/lib/speech.ts").read_text()
PLAYER = (FRONTEND / "src/ui/SimulationPlayer.tsx").read_text()


def _tts_module():
    """The tts_service MODULE, not the instance of the same name.

    `math_engine/__init__.py` does `from .tts_service import tts_service`,
    which rebinds the submodule's name in the package namespace to the object.
    So `import app.services.math_engine.tts_service` hands back the
    `TtsService` instance, and reaching for a module attribute on it raises.
    """
    import importlib

    return importlib.import_module("app.services.math_engine.tts_service")


# ── the three tiers ─────────────────────────────────────────────────────────

def test_the_player_tries_a_recording_then_the_device_then_a_timer() -> None:
    assert "currentStep.audio_url" in PLAYER
    assert "speakStep()" in PLAYER
    assert "onTimer()" in PLAYER


def test_every_tier_advances_on_the_words_finishing() -> None:
    """The point of speaking rather than timing: the step follows the
    narration instead of estimating how long it takes to say."""
    assert "audio.onended = advanceStep" in PLAYER
    assert "onEnd: advanceStep" in PLAYER


def test_a_missing_recording_falls_through_rather_than_going_silent() -> None:
    """Autoplay refused, or the file gone: the device can still read it."""
    assert "audio.onerror = () => speakStep()" in PLAYER
    assert "speakStep();" in PLAYER


def test_a_device_with_no_voice_still_advances() -> None:
    assert "if (!canSpeak() || !words)" in PLAYER
    assert "onTimer();" in PLAYER


def test_the_player_says_which_tier_is_carrying_the_step() -> None:
    """A silent step should not look broken."""
    assert '"file" : voicing === "device"' in PLAYER.replace("\n", " ") or \
           'voicing === "file"' in PLAYER
    assert "Read aloud by this device" in PLAYER
    assert "no recording needed" in PLAYER


# ── stopping, pausing, leaving ──────────────────────────────────────────────

def test_pausing_the_walkthrough_stops_the_talking() -> None:
    """Otherwise the narration carries on over a paused walkthrough — and
    finishes by advancing it."""
    assert "if (isPlaying) pauseSpeech();" in PLAYER
    assert "else resumeSpeech();" in PLAYER


def test_closing_a_walkthrough_stops_it_talking_over_the_next_thing() -> None:
    assert "speechRef.current?.cancel();" in PLAYER
    assert "stopSpeech();" in PLAYER


def test_changing_step_cancels_the_previous_sentence() -> None:
    assert PLAYER.count("speechRef.current?.cancel();") >= 2


# ── the quirks that make browser speech unreliable ──────────────────────────

def test_voices_that_load_late_are_picked_up() -> None:
    """On a first visit `getVoices()` returns [] until this fires — without it
    the first step of the first walkthrough is silent and the rest speak."""
    assert "voiceschanged" in SPEECH


def test_long_narration_is_kept_alive() -> None:
    """Chrome stops speaking after roughly fifteen seconds unless the queue is
    nudged, and a step's narration is routinely longer."""
    assert "keepAlive" in SPEECH
    assert "speechSynthesis.pause()" in SPEECH and "speechSynthesis.resume()" in SPEECH
    assert "clearInterval(keepAlive)" in SPEECH


def test_a_deliberate_cancel_is_not_reported_as_a_failure() -> None:
    assert '"interrupted"' in SPEECH and '"canceled"' in SPEECH


def test_a_voice_is_chosen_by_language_with_a_fallback() -> None:
    """Kenyan English is rarely installed. A lesson read in another accent is
    worth more than a lesson read in silence."""
    assert "en-KE" in SPEECH
    assert "startsWith(`${base}-`)" in SPEECH
    assert "v.default" in SPEECH


def test_it_ends_exactly_once() -> None:
    """`onend` and `onerror` can both fire; advancing twice skips a step."""
    assert "let finished = false" in SPEECH
    assert "if (finished) return;" in SPEECH


# ── the cost ────────────────────────────────────────────────────────────────

def test_narration_costs_nothing_by_default() -> None:
    """The engine is `edge` — Microsoft's neural voices, free and keyless — so
    narration is on. It was OpenAI, which charged a call per step for voices
    that have no Kenyan accent and no Kiswahili at all."""
    from app.settings import settings

    assert settings.tts_engine == "edge"
    assert settings.tts_synthesise is True


def test_the_paid_engine_is_a_choice_not_the_default() -> None:
    import inspect

    module = _tts_module()

    source = inspect.getsource(module.TtsService.synthesize_step_audio)
    # The engine the operator names is tried first, then the free one.
    assert '"openai": ("openai", "edge")' in source
    assert 'engine == "none"' in source, "and it can be turned off entirely"


def test_the_voice_follows_the_learning_area() -> None:
    """A Kiswahili lesson narrated by an English voice is the same defect as a
    Kiswahili lesson scripted in English."""
    from app.services.math_engine.tts_service import voice_for

    assert voice_for("Mathematics") == "en-KE-AsiliaNeural"
    assert voice_for("Kiswahili") == "sw-KE-ZuriNeural"
    assert voice_for("Arabic").startswith("ar-")
    assert voice_for("French").startswith("fr-")
    # A maths lesson is narrated in English whatever else is on the timetable.
    assert voice_for("Integrated Science") == "en-KE-AsiliaNeural"


def test_an_openai_voice_name_is_not_passed_to_edge() -> None:
    """`alloy` is not an edge voice, and TTS_VOICE may still hold one."""
    module = _tts_module()

    original = module.settings.tts_voice
    try:
        module.settings.tts_voice = "alloy"
        assert module.voice_for("Mathematics") == "en-KE-AsiliaNeural"
        module.settings.tts_voice = "en-KE-ChilembaNeural"
        assert module.voice_for("Mathematics") == "en-KE-ChilembaNeural"
    finally:
        module.settings.tts_voice = original


def test_the_worker_tells_the_engine_which_learning_area() -> None:
    import inspect

    from app.services.math_engine import audio_jobs

    source = inspect.getsource(audio_jobs.run_audio_job)
    assert "curriculum_link" in source
    assert "subject=subject" in source


def test_the_request_can_still_ask_for_one() -> None:
    from app.routes.math import SimulateRequest

    field = SimulateRequest.model_fields["enable_tts"]
    assert field.default is None, "unset means follow the setting"

    request = SimulateRequest(problem="x", enable_tts=True)
    assert request.enable_tts is True


def test_the_route_follows_the_setting_when_nothing_is_asked() -> None:
    import inspect

    from app.routes import math as math_routes

    source = inspect.getsource(math_routes.create_simulation)
    assert "settings.tts_synthesise if payload.enable_tts is None" in source


def test_a_walkthrough_with_no_audio_is_still_watchable() -> None:
    """The whole tier design rests on this: a track with no files is not a
    broken track."""
    from app.services.math_engine import simulation_builder
    from app.services.math_engine.objects import SolutionStep, SolutionTrace

    trace = SolutionTrace(
        problem="p", final_answer="x = 5",
        steps=[SolutionStep(1, "Divide", "3x=15", "x=5", "x = 5",
                            "Divide both sides by three.")])

    import unittest.mock as mock
    with mock.patch.object(simulation_builder, "execute", lambda *a, **k: None), \
         mock.patch.object(simulation_builder, "enqueue_audio", lambda *a, **k: ""):
        track = simulation_builder.build_simulation_track(
            problem="p", solution_trace=trace,
            curriculum_link={"grade": "grade-9", "subject": "Mathematics"},
            enable_tts=False,
        )

    assert track.steps[0].audio_url is None
    assert track.steps[0].narration, "and the words are there for the device to read"
    assert track.steps[0].duration_ms > 0, "and a timing if it cannot"


# ── a teacher's own voice ───────────────────────────────────────────────────

def test_a_recorded_step_is_never_re_synthesised() -> None:
    """No synthesiser is as good as a teacher. A recording is stored at exactly
    the key an engine would use, and the engine returns any file already there
    before it calls anything — so a recorded step is never overwritten and
    never costs anything again."""
    module = _tts_module()
    source = inspect.getsource(module.TtsService.synthesize_step_audio)

    checked = source.split("object_exists")[0]
    assert "engine" not in checked, \
        "the stored file must be returned BEFORE an engine is chosen"
    assert "object_storage.object_exists(object_key)" in source


def test_the_upload_writes_to_the_key_the_engine_would_use() -> None:
    from app.routes import math as math_routes

    source = inspect.getsource(math_routes.upload_step_audio)
    assert 'f"simulations/{simulation_id}/step_{step_index}.mp3"' in source


def test_a_recording_is_marked_as_one() -> None:
    """The player shows a microphone rather than a speaker, because a teacher
    reading it is worth knowing about."""
    from app.routes import math as math_routes

    source = inspect.getsource(math_routes.upload_step_audio)
    assert '"audio_source"] = "recorded"' in source
    assert 'audio_source === "recorded"' in PLAYER
    assert "A teacher's own recording" in PLAYER


def test_only_audio_can_be_uploaded_as_audio() -> None:
    from app.routes import math as math_routes

    source = inspect.getsource(math_routes.upload_step_audio)
    assert "is not audio" in source
    assert "audio/mpeg" in source


def test_a_step_that_does_not_exist_is_refused_with_the_count() -> None:
    from app.routes import math as math_routes

    source = inspect.getsource(math_routes.upload_step_audio)
    assert "has no step" in source


def test_the_walkthrough_reports_how_much_is_voiced() -> None:
    from app.routes import math as math_routes

    source = inspect.getsource(math_routes.upload_step_audio)
    assert "steps_voiced" in source
    assert '"ready" if voiced == len(steps) else "partial"' in source


# ── engines are pluggable ───────────────────────────────────────────────────

def test_another_engine_is_a_method_and_a_line() -> None:
    """Kokoro, XTTS, anything self-hosted: no call site changes."""
    module = _tts_module()
    source = inspect.getsource(module.TtsService.synthesize_step_audio)

    assert '"edge": ("edge", "openai")' in source
    assert '"piper": ("piper", "edge")' in source


def test_an_engine_that_is_not_installed_says_so_and_falls_back() -> None:
    module = _tts_module()
    source = inspect.getsource(module.TtsService._piper)

    assert "ImportError" in source
    assert "return None" in source, "so the next engine is tried"
