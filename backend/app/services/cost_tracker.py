from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..infra.db import execute, to_json

logger = logging.getLogger("cbc-cost")

# Published model pricing: USD per 1 million tokens
# Source: https://openai.com/pricing, https://anthropic.com/pricing, https://ai.google.dev/pricing
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-05-13": {"input": 2.50, "output": 10.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    # Anthropic
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    # Google Gemini
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    # Ollama / local models — free
    "llama3.1": {"input": 0.0, "output": 0.0},
    "llama3": {"input": 0.0, "output": 0.0},
    "qwen2.5:7b": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
    "phi3": {"input": 0.0, "output": 0.0},
    "codellama": {"input": 0.0, "output": 0.0},
}


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class CostResult:
    model: str
    provider: str
    token_usage: TokenUsage
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


def calculate_cost(model: str, provider: str, usage: TokenUsage) -> CostResult:
    """Calculate USD cost for a single LLM call based on token usage and model pricing."""
    pricing = _lookup_pricing(model, provider)
    input_cost = (usage.prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.completion_tokens / 1_000_000) * pricing["output"]
    return CostResult(
        model=model,
        provider=provider,
        token_usage=usage,
        input_cost_usd=round(input_cost, 6),
        output_cost_usd=round(output_cost, 6),
        total_cost_usd=round(input_cost + output_cost, 6),
    )


def _lookup_pricing(model: str, provider: str) -> dict[str, float]:
    """Look up pricing for a model. Tries exact match, then prefix match, then provider default."""
    # Exact match
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Prefix match (e.g. 'gpt-4o-mini-2024-07-18' matches 'gpt-4o-mini')
    for known_model, pricing in MODEL_PRICING.items():
        if model.startswith(known_model) or known_model.startswith(model):
            return pricing
    # Ollama is always free
    if provider == "ollama":
        return {"input": 0.0, "output": 0.0}
    # Unknown model — log and return zero
    logger.warning("No pricing found for model '%s' (provider: %s). Cost will be $0.", model, provider)
    return {"input": 0.0, "output": 0.0}


def format_cost_summary(stage_costs: list[CostResult]) -> dict[str, Any]:
    """Aggregate cost results across all pipeline stages into a summary."""
    total_prompt = sum(c.token_usage.prompt_tokens for c in stage_costs)
    total_completion = sum(c.token_usage.completion_tokens for c in stage_costs)
    total_tokens = sum(c.token_usage.total_tokens for c in stage_costs)
    total_cost = sum(c.total_cost_usd for c in stage_costs)

    stages = []
    for c in stage_costs:
        stages.append({
            "model": c.model,
            "provider": c.provider,
            "prompt_tokens": c.token_usage.prompt_tokens,
            "completion_tokens": c.token_usage.completion_tokens,
            "total_tokens": c.token_usage.total_tokens,
            "cost_usd": c.total_cost_usd,
        })

    by_provider: dict[str, float] = {}
    for c in stage_costs:
        by_provider[c.provider] = by_provider.get(c.provider, 0.0) + c.total_cost_usd

    return {
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "cost_by_provider": {k: round(v, 6) for k, v in by_provider.items()},
        "stages": stages,
    }


def persist_stage_cost(run_id: str, stage: str, cost: CostResult) -> None:
    """Save a single stage cost record to the database."""
    try:
        execute(
            """
            INSERT INTO generation_costs (run_id, pipeline_stage, provider, model,
                prompt_tokens, completion_tokens, total_tokens,
                input_cost_usd, output_cost_usd, total_cost_usd)
            VALUES (:run_id, :stage, :provider, :model,
                :prompt_tokens, :completion_tokens, :total_tokens,
                :input_cost_usd, :output_cost_usd, :total_cost_usd)
            """,
            {
                "run_id": run_id,
                "stage": stage,
                "provider": cost.provider,
                "model": cost.model,
                "prompt_tokens": cost.token_usage.prompt_tokens,
                "completion_tokens": cost.token_usage.completion_tokens,
                "total_tokens": cost.token_usage.total_tokens,
                "input_cost_usd": cost.input_cost_usd,
                "output_cost_usd": cost.output_cost_usd,
                "total_cost_usd": cost.total_cost_usd,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist cost for run %s stage %s: %s", run_id, stage, exc)
