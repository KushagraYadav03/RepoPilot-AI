
import asyncio

from app.services.llm_service import LLMService


async def main():

    llm_service = LLMService()

    response = await llm_service.generate(
        prompt="Explain what a REST API is in three sentences.",
        system_instruction=(
            "You are a helpful software engineering assistant."
        ),
    )

    print("Provider:", response.provider)
    print("Model:", response.model)
    print("Response:", response.text)


if __name__ == "__main__":
    asyncio.run(main())
