"""
OpenRouter API client for dialog generation.

Uses OpenAI-compatible API with OpenRouter backend.
Supports Claude, GPT, and other models via unified interface.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (approximate, check openrouter.ai/models for current prices)
MODEL_PRICING = {
    "anthropic/claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "anthropic/claude-3.5-sonnet": {"input": 3.0, "output": 15.0},
    "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "openai/gpt-4o": {"input": 2.5, "output": 10.0},
}


@dataclass
class DialogResponse:
    """Response from dialog generation."""
    lines: list[dict]  # [{"role": "A", "text": "..."}]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    success: bool = True
    error: Optional[str] = None


class OpenRouterClient:
    """
    OpenRouter API client for dialog generation.

    Usage:
        client = OpenRouterClient()
        response = await client.generate_dialog(post_text, participants)
        print(response.lines)
    """

    SYSTEM_PROMPT = """Ты генерируешь КОРОТКИЕ комментарии для Telegram.

УЧАСТНИКИ:
{participants}

КРИТИЧЕСКИ ВАЖНО:
- Каждая реплика МАКСИМУМ 3-10 слов
- Пиши как в чате: коротко, без знаков препинания в конце
- НИКОГДА не используй: ого, вау, интересно, круто, класс, супер, отлично, прикольно, молодцы
- Соблюдай пол (М: видел/думал, Ж: видела/думала)
- Реагируй на КОНКРЕТИКУ поста, не абстрактно
- Без эмодзи

ПРИМЕРЫ ХОРОШИХ РЕПЛИК:
- "опять выросло, задолбало уже"
- "а чё так дорого то"
- "норм новость, давно пора"
- "ну хз, сомнительно как-то"
- "блин реально? не знала"

ФОРМАТ (только JSON, role = A/B/C/D):
{{
  "lines": [
    {{"role": "A", "text": "короткая реплика"}},
    {{"role": "B", "text": "ответ"}}
  ]
}}"""

    USER_PROMPT = """Пост из канала:
---
{post_text}
---

Сгенерируй диалог из {num_lines} реплик."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or config.OPENROUTER_API_KEY
        self.model = model or config.OPENROUTER_MODEL
        self.base_url = base_url or config.OPENROUTER_BASE_URL

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

    def _calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Calculate cost based on token usage."""
        pricing = MODEL_PRICING.get(model, {"input": 3.0, "output": 15.0})
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    async def generate_dialog(
        self,
        post_text: str,
        participants: list[dict],  # [{"role": "A", "name": "Мария", "gender": "Ж"}]
        num_lines: int = 3,
        model: Optional[str] = None,
        temperature: float = 0.8,
    ) -> DialogResponse:
        """
        Generate dialog for a post.

        Args:
            post_text: Text of the channel post
            participants: List of participants with role, name, gender
            num_lines: Number of dialog lines to generate
            model: Override default model
            temperature: Higher = more creative

        Returns:
            DialogResponse with generated lines
        """
        model = model or self.model

        # Format participants
        participants_str = "\n".join([
            f"- {p['role']}: {p['name']} ({'М' if p['gender'] == 'M' else 'Ж'})"
            for p in participants
        ])

        system = self.SYSTEM_PROMPT.format(participants=participants_str)
        user = self.USER_PROMPT.format(post_text=post_text, num_lines=num_lines)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://telegram-analyzer.local",
                        "X-Title": "Telegram Analyzer",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": 500,
                        "temperature": temperature,
                    },
                )

                if response.status_code != 200:
                    return DialogResponse(
                        lines=[],
                        success=False,
                        error=f"API error {response.status_code}: {response.text}",
                        model=model,
                    )

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # Parse usage
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost = self._calculate_cost(input_tokens, output_tokens, model)

                # Parse JSON from response
                try:
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0]
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0]
                    parsed = json.loads(content.strip())
                    lines = parsed.get("lines", [])
                except json.JSONDecodeError as e:
                    return DialogResponse(
                        lines=[],
                        success=False,
                        error=f"JSON parse error: {e}. Raw: {content[:200]}",
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost,
                    )

                return DialogResponse(
                    lines=lines,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    model=model,
                    success=True,
                )

        except httpx.TimeoutException:
            return DialogResponse(
                lines=[],
                success=False,
                error="Request timeout",
                model=model,
            )
        except Exception as e:
            logger.exception(f"OpenRouter error: {e}")
            return DialogResponse(
                lines=[],
                success=False,
                error=str(e),
                model=model,
            )


# Convenience function for quick testing
async def test_dialog():
    """Test dialog generation."""
    client = OpenRouterClient()

    post = """Курс доллара вырос до 95 рублей на фоне новых санкций.
Эксперты прогнозируют дальнейший рост в ближайшие недели."""

    participants = [
        {"role": "A", "name": "Максим", "gender": "M"},
        {"role": "B", "name": "Мария", "gender": "F"},
        {"role": "C", "name": "Сергей", "gender": "M"},
    ]

    result = await client.generate_dialog(post, participants, num_lines=4)

    print(f"Success: {result.success}")
    if result.success:
        for line in result.lines:
            name = next((p["name"] for p in participants if p["role"] == line["role"]), line["role"])
            print(f"  {name}: {line['text']}")
        print(f"\nTokens: {result.input_tokens} in / {result.output_tokens} out")
        print(f"Cost: ${result.cost_usd:.6f}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_dialog())
