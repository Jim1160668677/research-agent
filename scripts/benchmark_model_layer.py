"""Offline model-adapter and process-wide scheduler micro-benchmarks."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    index = min(int(len(ordered) * value), len(ordered) - 1)
    return ordered[index]


async def main() -> None:
    from research_agent.llm.provider import AgnesCLIProvider, DeepSeekProvider, LLMMessage
    from research_agent.runtime_coordinator import RuntimeCoordinator

    class OfflineAgnes(AgnesCLIProvider):
        async def _process(self, arguments, *, timeout):
            if arguments == ["--version"]:
                return 0, "0.1.5\n", ""
            return (
                0,
                json.dumps(
                    {
                        "ok": True,
                        "model": self.model,
                        "text": "pong",
                        "raw": {
                            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
                        },
                    }
                ),
                "",
            )

    class OfflineDeepSeek(DeepSeekProvider):
        async def chat(self, messages, **kwargs):
            # Benchmark normalized request preparation without a paid network call.
            self._provider_request(kwargs)
            return {"content": messages[-1].content}

    async def measure(label, count, operation):
        durations = []
        for _ in range(count):
            started = time.perf_counter()
            await operation()
            durations.append((time.perf_counter() - started) * 1000)
        print(
            f"{label}: calls={count} mean_ms={statistics.mean(durations):.4f} "
            f"p50_ms={statistics.median(durations):.4f} p95_ms={percentile(durations, 0.95):.4f} "
            f"max_ms={max(durations):.4f}"
        )

    message = [LLMMessage("user", "ping")]
    deepseek = OfflineDeepSeek(api_key="benchmark-key")
    await measure("deepseek_request_contract", 10000, lambda: deepseek.chat(message))

    agnes = OfflineAgnes(api_key="benchmark-key", config={"cli_command": ["offline"]})
    await measure("agnes_json_contract", 5000, lambda: agnes.chat(message))

    coordinator = RuntimeCoordinator(max_concurrency=6)

    async def lease(index):
        async with coordinator.lease("benchmark", str(index)):
            await asyncio.sleep(0)

    started = time.perf_counter()
    await asyncio.gather(*(lease(index) for index in range(10000)))
    elapsed = (time.perf_counter() - started) * 1000
    print(
        f"runtime_coordinator: operations=10000 total_ms={elapsed:.3f} mean_ms={elapsed / 10000:.4f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
