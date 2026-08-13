"""Minimal opt-in live smoke test for the Agnes CLI provider.

The script never prints or persists AGNES_API_KEY.  It exits early when the
credential is absent so routine offline test runs cannot trigger a paid call.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_agent.llm.provider import AgnesCLIProvider, LLMMessage


async def main() -> None:
    api_key = os.environ.get("AGNES_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("AGNES_API_KEY is not configured; live smoke test skipped")

    provider = AgnesCLIProvider(
        api_key=api_key,
        model="agnes-2.0-flash",
        config={"timeout_seconds": 90, "max_attempts": 2},
    )
    response = await provider.chat(
        [LLMMessage(role="user", content="Reply with exactly pong.")],
        max_tokens=16,
    )
    print(
        json.dumps(
            {
                "content": response.content,
                "provider": response.provider,
                "model": response.model,
                "attempts": response.attempts,
                "latency_ms": response.latency_ms,
                "usage": response.usage,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
