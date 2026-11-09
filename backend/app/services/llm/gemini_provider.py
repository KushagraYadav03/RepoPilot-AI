
from google import genai
from google.genai import types

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider, LLMResponse


class GeminiProvider(BaseLLMProvider):

    def __init__(self):

        if not settings.gemini_api_key:
            raise ValueError("Gemini API key is missing")

        self.model = settings.llm_model

        self.client = genai.Client(
            api_key=settings.gemini_api_key
        )

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> LLMResponse:

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )

        if not response.text:
            raise RuntimeError("Gemini returned an empty response")

        return LLMResponse(
            text=response.text,
            provider="gemini",
            model=self.model,
        )
