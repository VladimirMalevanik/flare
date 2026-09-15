"""Manual smoke test: enrichment prompt against real Groq."""
import asyncio
import json
import os

from dotenv import load_dotenv
load_dotenv()

from groq import AsyncGroq

from app.ai_engine.enrichment_prompts import (
    SYSTEM_PROMPT, PROMPT_VERSION, SCHEMA_VERSION, build_enrichment_request,
)


async def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("GROQ_API_KEY is not set")

    model = os.getenv("LLM_DEFAULT_MODEL", "openai/gpt-oss-20b")

    content = """
    Вчера на созвоне с командой решили, что MVP запустим 15 мая.
    Но у нас до сих пор нет готового онбординга, и это блокирует первых пользователей.
    Аня взяла на себя подготовку текстов для onboarding, но deadline пока не назначен.
    """

    request = build_enrichment_request(content)
    request.update(
        model=model,
        temperature=0.2,
        max_completion_tokens=512,
        include_reasoning=False,
        stream=False,
    )

    async with AsyncGroq(api_key=api_key, base_url="https://api.groq.com") as client:
        response = await client.chat.completions.create(**request)

    raw = response.choices[0].message.content
    print(f"--- {PROMPT_VERSION} / {SCHEMA_VERSION} ---")
    print(f"--- model: {response.model} ---")
    print(raw)

    try:
        parsed = json.loads(raw)
        print("\n--- parsed JSON ---")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        print(f"\nJSON parse failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
    