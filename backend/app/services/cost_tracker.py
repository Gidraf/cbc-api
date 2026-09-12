from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..infra.db import execute, to_json

logger = logging.getLogger("cbc-cost")

# Published model pricing: USD per 1 million tokens
# Source: https://openai.com/pricing, https://anthropic.com/pricing, https://ai.google.dev/pricing
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI — standard tier, short context, from the pricing page as pasted
    # by the operator on 2026-09-12. Reasoning tokens are billed as output.
    # `cached` is the cached-input rate. More specific ids sit ABOVE their
    # family id because lookup is by prefix.
    "gpt-6-astra": {"input": 10.00, "cached": 1.00, "output": 50.00},
    "gpt-5.6-sol": {"input": 4.00, "cached": 0.40, "output": 20.00},
    "gpt-5.6-terra": {"input": 2.00, "cached": 0.20, "output": 12.00},
    "gpt-5.6-luna": {"input": 0.20, "cached": 0.02, "output": 1.20},
    "gpt-5.6-cyber": {"input": 12.50, "cached": 1.25, "output": 75.00},
    "gpt-5.5-pro": {"input": 30.00, "output": 180.00},
    "gpt-5.5-cyber": {"input": 12.50, "cached": 1.25, "output": 75.00},
    "gpt-5.5": {"input": 5.00, "cached": 0.50, "output": 30.00},
    "gpt-5.4-pro": {"input": 30.00, "output": 180.00},
    "gpt-5.4-mini": {"input": 0.75, "cached": 0.075, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "cached": 0.02, "output": 1.25},
    "gpt-5.4": {"input": 2.50, "cached": 0.25, "output": 15.00},
    "gpt-5.3-codex": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.2-pro": {"input": 21.00, "output": 168.00},
    "gpt-5.2": {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.1": {"input": 1.25, "cached": 0.125, "output": 10.00},
    "gpt-5-pro": {"input": 15.00, "output": 120.00},
    "gpt-5-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "cached": 0.005, "output": 0.40},
    "gpt-5": {"input": 1.25, "cached": 0.125, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "cached": 0.10, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "cached": 0.025, "output": 0.40},
    "gpt-4.1": {"input": 2.00, "cached": 0.50, "output": 8.00},
    "o4-mini": {"input": 1.10, "cached": 0.275, "output": 4.40},
    "o3-pro": {"input": 20.00, "output": 80.00},
    "o3-mini": {"input": 1.10, "cached": 0.55, "output": 4.40},
    "o3": {"input": 2.00, "cached": 0.50, "output": 8.00},
    "o1-pro": {"input": 150.00, "output": 600.00},
    "o1": {"input": 15.00, "cached": 7.50, "output": 60.00},
    "gpt-4o-mini": {"input": 0.15, "cached": 0.075, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "cached": 0.075, "output": 0.60},
    "gpt-4o-2024-05-13": {"input": 5.00, "output": 15.00},
    "gpt-4o": {"input": 2.50, "cached": 1.25, "output": 10.00},
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
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    # Retired by Google, kept so an old job's recorded cost still resolves.
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
    # Of the prompt tokens, how many were served from the provider's prompt
    # cache at the cached rate. Six per-lesson calls share one 11,000-token
    # prefix; billing all six at the full rate overstated a run by a third.
    cached_tokens: int = 0


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
    cached = max(0, min(usage.cached_tokens, usage.prompt_tokens))
    input_cost = ((usage.prompt_tokens - cached) / 1_000_000) * pricing["input"] \
        + (cached / 1_000_000) * pricing.get("cached", pricing["input"])
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
    # A GPT-5 id this table has not met (a dated snapshot, a point release)
    # is priced as its size class rather than as $0 — a run that reports no
    # cost is a run whose cost nobody notices until the invoice.
    lower = model.lower()
    if lower.startswith("gpt-5") or lower.startswith("gpt-6"):
        family = ("gpt-5-nano" if "nano" in lower
                  else "gpt-5-mini" if "mini" in lower
                  else "gpt-5.5-pro" if "pro" in lower
                  else "gpt-5.4")
        logger.info("Pricing '%s' as %s (no exact entry).", model, family)
        return MODEL_PRICING[family]
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
