from __future__ import annotations

from enum import StrEnum


class Provider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class PipelineStage(StrEnum):
    NOTES_GENERATION = "notes_generation"
    DIAGRAM_GENERATION = "diagram_generation"
    ACTIVITY_GENERATION = "activity_generation"
    QUESTION_GENERATION = "question_generation"
    REVIEWER_PANEL = "reviewer_panel"
    REGENERATION = "regeneration"


OFFICIAL_BASE_URLS: dict[Provider, str] = {
    Provider.OPENAI: "https://api.openai.com/v1",
    Provider.ANTHROPIC: "https://api.anthropic.com",
    Provider.GEMINI: "https://generativelanguage.googleapis.com",
}

ALLOWED_PROVIDERS = {p.value for p in Provider}
ALLOWED_STAGES = {s.value for s in PipelineStage}
