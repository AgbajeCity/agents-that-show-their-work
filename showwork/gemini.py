"""Gemini narrator.

Gemini writes the explanation. It never computes a number. The agent checks
its text against the fact sheet before showing it.

Needs `pip install google-genai` and a GEMINI_API_KEY environment variable.
Set GEMINI_MODEL to use a different model.
"""

from __future__ import annotations

import os

SYSTEM_INSTRUCTION = """You explain a cost-to-serve analysis to a product team.
Rules:
- Use only the facts in the fact sheet. Do not calculate anything new.
- Write every number exactly as it appears in the fact sheet, followed
  straight away by its fact ID in square brackets, for example $12.34 [F2].
- Do not write any other number, including years, counts or percentages.
- If the question assumes something the facts contradict, say plainly that
  the data does not support it.
- If a plan's evidence is thin, say so and leave it out of any ranking.
- Keep it under 120 words."""


class GeminiNarrator:
    def __init__(self, model: str | None = None) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client()
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

    def __call__(self, question: str, facts: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=f"Fact sheet:\n{facts}\n\nQuestion: {question}",
            # Temperature stays at the model default. Repeatability comes from
            # Python doing the arithmetic, not from sampling settings.
            config=self._types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
        )
        return (response.text or "").strip()
