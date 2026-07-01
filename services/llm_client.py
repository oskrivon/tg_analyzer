"""
LLM API client with cost tracking.

Supports:
- Anthropic API (Claude)
- OpenRouter API (multiple models)

Features:
- Token usage tracking
- Cost estimation
- Retry logic
- Structured JSON responses
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Literal

import config

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (as of 2024-2025)
MODEL_PRICING = {
    # Anthropic direct
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "claude-3-5-haiku-20241022": {"input": 1.0, "output": 5.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    # OpenRouter - DeepSeek (CHEAPEST!)
    "deepseek/deepseek-chat": {"input": 0.20, "output": 0.77},  # V3
    "deepseek/deepseek-r1": {"input": 0.55, "output": 2.19},
    "deepseek/deepseek-r1-distill-llama-70b": {"input": 0.70, "output": 0.80},
    # OpenRouter - Claude
    "anthropic/claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "anthropic/claude-3.5-sonnet": {"input": 3.0, "output": 15.0},
    "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
    # OpenRouter - OpenAI
    "openai/gpt-4o": {"input": 2.5, "output": 10.0},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.6},
    # OpenRouter - Other
    "google/gemini-pro-1.5": {"input": 1.25, "output": 5.0},
    "meta-llama/llama-3.1-70b-instruct": {"input": 0.52, "output": 0.75},
}


@dataclass
class LLMResponse:
    """Response from LLM with metadata."""
    content: str
    parsed_json: Optional[dict] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    success: bool = True
    error: Optional[str] = None


@dataclass
class LLMUsageStats:
    """Cumulative usage statistics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    costs_by_model: dict = field(default_factory=dict)


class LLMClient:
    """
    LLM API client with token tracking and cost estimation.

    Supports both Anthropic API and OpenRouter.

    Usage:
        # Anthropic (default)
        client = LLMClient()

        # OpenRouter
        client = LLMClient(provider="openrouter")

        response = client.analyze(system_prompt, user_prompt)
        print(f"Cost: ${response.cost_usd:.4f}")
        print(f"JSON: {response.parsed_json}")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        provider: Literal["anthropic", "openrouter"] = "anthropic",
    ):
        self.provider = provider
        self.max_tokens = max_tokens

        if provider == "openrouter":
            self.api_key = api_key or config.OPENROUTER_API_KEY
            self.model = model or config.OPENROUTER_MODEL
            if not self.api_key:
                raise ValueError("OPENROUTER_API_KEY not set. Add it to .env file.")

            from openai import OpenAI
            self.client = OpenAI(
                base_url=config.OPENROUTER_BASE_URL,
                api_key=self.api_key,
            )
        else:
            self.api_key = api_key or config.ANTHROPIC_API_KEY
            self.model = model or config.LLM_MODEL
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set. Add it to .env file.")

            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)

        self.stats = LLMUsageStats()

    def _calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Calculate cost based on token usage."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-3-haiku-20240307"])
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def _update_stats(self, response: LLMResponse):
        """Update cumulative statistics."""
        self.stats.total_requests += 1
        if response.success:
            self.stats.successful_requests += 1
            self.stats.total_input_tokens += response.input_tokens
            self.stats.total_output_tokens += response.output_tokens
            self.stats.total_cost_usd += response.cost_usd

            if response.model not in self.stats.costs_by_model:
                self.stats.costs_by_model[response.model] = 0.0
            self.stats.costs_by_model[response.model] += response.cost_usd
        else:
            self.stats.failed_requests += 1

    def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """
        Send analysis request to LLM.

        Args:
            system_prompt: System instructions (role, output format)
            user_prompt: The actual content to analyze
            model: Override default model
            max_tokens: Override default max tokens
            temperature: Lower = more deterministic (default 0.3 for JSON)

        Returns:
            LLMResponse with parsed JSON if successful
        """
        model = model or self.model
        max_tokens = max_tokens or self.max_tokens

        try:
            if self.provider == "openrouter":
                # OpenRouter uses OpenAI-compatible API
                message = self.client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                )
                content = message.choices[0].message.content if message.choices else ""
                input_tokens = message.usage.prompt_tokens if message.usage else 0
                output_tokens = message.usage.completion_tokens if message.usage else 0
            else:
                # Anthropic API
                message = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_prompt}
                    ],
                )
                content = message.content[0].text if message.content else ""
                input_tokens = message.usage.input_tokens
                output_tokens = message.usage.output_tokens

            total_tokens = input_tokens + output_tokens
            cost = self._calculate_cost(input_tokens, output_tokens, model)

            # Try to parse JSON
            parsed_json = None
            try:
                # Handle markdown code blocks
                json_str = content
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]
                parsed_json = json.loads(json_str.strip())
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from response: {content[:200]}...")

            response = LLMResponse(
                content=content,
                parsed_json=parsed_json,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                model=model,
                success=True,
            )

        except Exception as e:
            logger.exception(f"LLM API error: {e}")
            response = LLMResponse(
                content="",
                success=False,
                error=str(e),
                model=model,
            )

        self._update_stats(response)
        return response

    def get_stats(self) -> dict:
        """Get current usage statistics."""
        return {
            "total_requests": self.stats.total_requests,
            "successful_requests": self.stats.successful_requests,
            "failed_requests": self.stats.failed_requests,
            "total_input_tokens": self.stats.total_input_tokens,
            "total_output_tokens": self.stats.total_output_tokens,
            "total_tokens": self.stats.total_input_tokens + self.stats.total_output_tokens,
            "total_cost_usd": round(self.stats.total_cost_usd, 4),
            "costs_by_model": {k: round(v, 4) for k, v in self.stats.costs_by_model.items()},
        }

    def print_stats(self):
        """Print formatted statistics."""
        stats = self.get_stats()
        print("\n" + "=" * 50)
        print("LLM Usage Statistics")
        print("=" * 50)
        print(f"Requests: {stats['successful_requests']}/{stats['total_requests']} successful")
        print(f"Tokens: {stats['total_tokens']:,} (in: {stats['total_input_tokens']:,}, out: {stats['total_output_tokens']:,})")
        print(f"Total Cost: ${stats['total_cost_usd']:.4f}")
        if stats['costs_by_model']:
            print("\nCost by Model:")
            for model, cost in stats['costs_by_model'].items():
                print(f"  {model}: ${cost:.4f}")
        print("=" * 50)
