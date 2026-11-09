
from app.services.llm.factory import get_llm_provider
from app.services.llm.base import LLMResponse


class LLMService:

    def __init__(self):
        self.provider = get_llm_provider()

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> LLMResponse:

        if not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        return await self.provider.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
