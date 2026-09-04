from __future__ import annotations

import hashlib
import logging
from typing import Any

from ...infra.db import execute, to_json
from .narration_agent import narration_agent
from .objects import SolutionTrace
from .simulation_schema import SimulationStep, SimulationTrack
from .audio_jobs import enqueue_audio

logger = logging.getLogger("cbc-simulation-builder")


def build_simulation_track(
    problem: str,
    solution_trace: SolutionTrace,
    curriculum_link: dict[str, Any],
    title: str = "",
    source_type: str = "question_solution",
    source_id: str = "",
    enable_tts: bool = True,
) -> SimulationTrack:
    """Assembles a SolutionTrace into a timed, narrated SimulationTrack.

    Narration audio is NOT synthesised here. `enable_tts` now means "queue the
    narration", because doing it inline held the request open for up to 25
    seconds per step. The track is returned and stored immediately; the player
    falls back to each step's `duration_ms` until the worker fills the audio in.
    """
    seed = f"{curriculum_link.get('grade')}:{curriculum_link.get('subject')}:{problem}:{title}"
    sim_id = f"sim_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"
    grade = str(curriculum_link.get("grade") or "grade-7")

    steps: list[SimulationStep] = []
    total_duration = 0

    for idx, st in enumerate(solution_trace.steps):
        # 1. Spoken narration for this step
        narration = st.explanation or narration_agent.narrate_solution_step(
            operation=st.operation,
            latex=st.latex,
            expression_before=st.expression_before,
            expression_after=st.expression_after,
            grade=grade,
        )

        # 2. Approximate duration based on words if audio is synthesized or not
        word_count = len(narration.split())
        duration_ms = max(3500, word_count * 350)
        total_duration += duration_ms

        # 3. Audio arrives later, from the queue — see audio_jobs.
        audio_url = None

        steps.append(
            SimulationStep(
                index=idx,
                duration_ms=duration_ms,
                latex=st.latex,
                plain=st.expression_after or st.latex,
                narration=narration,
                audio_url=audio_url,
                svg_highlight=st.operation.lower().replace(" ", "_"),
                animation_type="reveal",
            )
        )

    track = SimulationTrack(
        simulation_id=sim_id,
        curriculum_link=curriculum_link,
        title=title or f"Solution Walkthrough: {problem[:40]}",
        total_duration_ms=total_duration,
        source_type=source_type,
        steps=steps,
    )

    # Persist in DB
    try:
        execute(
            """
            INSERT INTO math_simulations (
                simulation_id, curriculum_link, source_type, source_id, title, track, audio_status, updated_at
            )
            VALUES (
                :sim_id, CAST(:curriculum_link AS jsonb), :source_type, :source_id, :title, CAST(:track AS jsonb), :audio_status, NOW()
            )
            ON CONFLICT (simulation_id) DO UPDATE SET
                track = EXCLUDED.track,
                title = EXCLUDED.title,
                audio_status = EXCLUDED.audio_status,
                updated_at = NOW()
            """,
            {
                "sim_id": sim_id,
                "curriculum_link": to_json(curriculum_link),
                "source_type": source_type,
                "source_id": source_id,
                "title": track.title,
                "track": to_json(track.to_dict()),
                "audio_status": "pending" if enable_tts else "off",
            },
        )
        persisted = True
    except Exception as exc:
        logger.warning("Could not persist simulation track %s: %s", sim_id, exc)
        persisted = False

    # Only queue narration for a walkthrough the worker can actually load.
    if enable_tts and persisted and steps:
        enqueue_audio(sim_id, curriculum_link)

    return track
