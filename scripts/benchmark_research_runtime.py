"""Micro-benchmarks for deterministic local research-runtime paths."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))


def measured(name, calls, function):
    started = time.perf_counter()
    for _ in range(calls):
        function()
    elapsed = time.perf_counter() - started
    print(f"{name}: {calls} calls, {elapsed:.4f}s total, {elapsed / calls * 1000:.3f}ms/call")


def main():
    from research_agent.research.artifacts import ArtifactStore
    from research_agent.research.planner import ResearchPlanner
    from research_agent.research.services import normalize_evidence

    planner = ResearchPlanner()
    measured(
        "planner_full_scope",
        1000,
        lambda: planner.plan(
            "系统评价某干预、设计验证实验、分析数据并形成规范论文",
            domains=["literature", "experiment", "data", "writing", "integrity"],
        ),
    )
    records = [
        {
            "pmid": str(index),
            "title": f"Study {index} of treatment response",
            "abstract": "Bounded abstract.",
        }
        for index in range(200)
    ]
    measured("evidence_normalization_200", 200, lambda: normalize_evidence(records))

    with tempfile.TemporaryDirectory(prefix="research-runtime-benchmark-") as directory:
        root = Path(directory)
        table = root / "matrix.csv"
        with table.open("w", encoding="utf-8", newline="") as handle:
            handle.write("sample,group,value,missing\n")
            for index in range(50_000):
                handle.write(
                    f"S{index},{'A' if index % 2 else 'B'},{index / 10},{'' if index % 9 else 'NA'}\n"
                )
        store = ArtifactStore(root / "artifacts")
        measured("table_profile_50000", 3, lambda: store.profile_table(table))

    asyncio.run(benchmark_synchronization())


async def benchmark_synchronization():
    """Exercise aggregate scheduling without network or API credentials."""
    from research_agent.runtime_coordinator import RuntimeCoordinator

    coordinator = RuntimeCoordinator(max_concurrency=6)
    started = time.perf_counter()

    async def operation(index: int):
        async with coordinator.lease("benchmark", str(index)):
            await asyncio.sleep(0)

    count = 5000
    await asyncio.gather(*(operation(index) for index in range(count)))
    elapsed = time.perf_counter() - started
    print(
        f"runtime_coordinator_{count}: {count} operations, {elapsed:.4f}s total, "
        f"{elapsed / count * 1000:.3f}ms/operation"
    )


if __name__ == "__main__":
    main()
