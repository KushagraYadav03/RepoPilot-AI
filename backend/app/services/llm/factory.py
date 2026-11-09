
from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemini_provider import GeminiProvider


@lru_cache(maxsize=1)
def get_llm_provider() -> BaseLLMProvider:

    provider = settings.llm_provider.lower()

    if provider == "gemini":
        return GeminiProvider()

    raise ValueError(
        f"Unsupported LLM provider: {provider}"
    )
