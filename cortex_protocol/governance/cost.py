"""Cost tracking and budget enforcement for agent runs.

Tracks tokens and USD cost per run, supports per-policy budget caps, and
feeds cost-aware events into the audit log. Model prices come from a
built-in table that can be overridden at runtime.

Prices are list prices in USD per 1M tokens. They are intentionally kept
close enough to reality for budget enforcement without pretending to be
authoritative. Override via `CostTracker(pricing_overrides={...})` when
you have negotiated rates or want to freeze a specific price for testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


# Prices in USD per 1,000,000 tokens. (input, output). Sourced from each
# provider's public pricing page as of 2026-04. Unknown models fall back
# to _UNKNOWN_MODEL_PRICE, which is intentionally pessimistic so budgets
# bite before real spend runs away.
_BUILTIN_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-opus-4-7":      (15.00, 75.00),
    "claude-opus-4":        (15.00, 75.00),
    "claude-sonnet-4-6":    ( 3.00, 15.00),
    "claude-sonnet-4":      ( 3.00, 15.00),
    "claude-haiku-4-5":     ( 1.00,  5.00),
    "claude-3-5-sonnet":    ( 3.00, 15.00),
    "claude-3-5-haiku":     ( 0.80,  4.00),
    "claude-3-opus":        (15.00, 75.00),
    # OpenAI
    "gpt-4o":               ( 2.50, 10.00),
    "gpt-4o-mini":          ( 0.15,  0.60),
    "gpt-4-turbo":          (10.00, 30.00),
    "o1":                   (15.00, 60.00),
    "o1-mini":              ( 3.00, 12.00),
    # Google
    "gemini-2.0-flash":     ( 0.10,  0.40),
    "gemini-1.5-pro":       ( 1.25,  5.00),
    "gemini-1.5-flash":     ( 0.075, 0.30),
}

# Fallback for models we do not recognize. Pessimistic (priced like Opus)
# so budget caps still trip and an explicit override is the remedy.
_UNKNOWN_MODEL_PRICE: tuple[float, float] = (15.00, 75.00)


@dataclass(frozen=True)
class ModelPrice:
    """List price for a model in USD per 1M tokens."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok / 1_000_000
            + output_tokens * self.output_per_mtok / 1_000_000
        )


class ModelPricing:
    """Resolves model names to per-token prices.

    Lookup order:
      1. Explicit overrides passed to __init__
      2. Built-in pricing table (_BUILTIN_PRICING)
      3. _UNKNOWN_MODEL_PRICE (pessimistic fallback)
    """

    def __init__(self, overrides: Optional[dict[str, tuple[float, float]]] = None):
        self._overrides = overrides or {}

    def for_model(self, model_name: str) -> ModelPrice:
        if model_name in self._overrides:
            inp, out = self._overrides[model_name]
        elif model_name in _BUILTIN_PRICING:
            inp, out = _BUILTIN_PRICING[model_name]
        else:
            # Try family-prefix match ("claude-sonnet-4-6-20250401" -> "claude-sonnet-4-6")
            matched = None
            for known in _BUILTIN_PRICING:
                if model_name.startswith(known):
                    matched = known
                    break
            if matched:
                inp, out = _BUILTIN_PRICING[matched]
            else:
                inp, out = _UNKNOWN_MODEL_PRICE
        return ModelPrice(input_per_mtok=inp, output_per_mtok=out)

    def known_models(self) -> list[str]:
        return sorted(set(_BUILTIN_PRICING) | set(self._overrides))


@dataclass
class UsageSample:
    """One token-and-cost sample from a single LLM call or tool invocation."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tool_name: Optional[str] = None
    turn: int = 0


@dataclass
class CostSnapshot:
    """Aggregate spend for a run, suitable for budget checks and audit logs."""

    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0
    samples: list[UsageSample] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


class CostTracker:
    """Accumulates usage per run and answers budget questions.

    Not thread-safe; create one per run. Each PolicyEnforcer owns one.
    """

    def __init__(self, pricing: Optional[ModelPricing] = None):
        self._pricing = pricing or ModelPricing()
        self._snapshot = CostSnapshot()

    @property
    def snapshot(self) -> CostSnapshot:
        return self._snapshot

    def record(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: Optional[float] = None,
        tool_name: Optional[str] = None,
        turn: int = 0,
    ) -> UsageSample:
        """Record one usage sample.

        If cost_usd is not supplied, it is computed from the pricing table.
        Callers that already know exact billed cost (e.g. from provider
        response metadata) should pass it explicitly.
        """
        if cost_usd is None:
            cost_usd = self._pricing.for_model(model).cost(input_tokens, output_tokens)

        sample = UsageSample(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tool_name=tool_name,
            turn=turn,
        )
        self._snapshot.samples.append(sample)
        self._snapshot.total_cost_usd += cost_usd
        self._snapshot.total_input_tokens += input_tokens
        self._snapshot.total_output_tokens += output_tokens
        # Intentionally does NOT bump total_tool_calls: the PolicyEnforcer
        # owns that counter via record_tool_call() at tool-invocation time,
        # so cost attribution (here) and call-count (there) stay independent.
        return sample

    def record_tool_call(self, tool_name: str, *, turn: int = 0) -> None:
        """Record that a tool was invoked. Does not add any cost."""
        self._snapshot.total_tool_calls += 1
        self._snapshot.samples.append(
            UsageSample(model="", tool_name=tool_name, turn=turn)
        )

    # ---- budget questions ----------------------------------------------

    def would_exceed_cost(self, max_cost_usd: float, next_call_cost_usd: float = 0.0) -> bool:
        return self._snapshot.total_cost_usd + next_call_cost_usd > max_cost_usd

    def would_exceed_tokens(self, max_tokens: int, next_call_tokens: int = 0) -> bool:
        return self._snapshot.total_tokens + next_call_tokens > max_tokens

    def would_exceed_tool_calls(self, max_tool_calls: int) -> bool:
        return self._snapshot.total_tool_calls + 1 > max_tool_calls


def aggregate_samples(samples: Iterable[UsageSample]) -> CostSnapshot:
    """Helper: build a CostSnapshot from an iterable of samples.

    Here `total_tool_calls` IS derived from samples (every sample with a
    tool_name counts once) because when reconstructing from historical
    audit events we don't have a separate counter — samples are the
    source of truth.
    """
    snap = CostSnapshot()
    for s in samples:
        snap.samples.append(s)
        snap.total_cost_usd += s.cost_usd
        snap.total_input_tokens += s.input_tokens
        snap.total_output_tokens += s.output_tokens
        if s.tool_name:
            snap.total_tool_calls += 1
    return snap
