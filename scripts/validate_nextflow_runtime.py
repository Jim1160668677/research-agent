"""Run the pinned nf-core smoke profile through the application backend."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_agent.execution.nextflow import NextflowBackend


def _emit(event: str, payload: object) -> None:
    # Keep the validation stream portable across Windows code pages. Scientific
    # tools can emit arbitrary Unicode/replacement characters during probing;
    # escaped JSON remains lossless and cannot fail under a legacy console.
    print(json.dumps({"event": event, "payload": payload}, ensure_ascii=True), flush=True)


async def _run(args: argparse.Namespace) -> int:
    backend = NextflowBackend(root=args.root.resolve())
    preflight = await backend.preflight(
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        network_allowed=True,
    )
    _emit("preflight", preflight)
    if not preflight.get("ready"):
        return 2

    plan = await backend.build_plan(
        run_id=args.run_id,
        user_id=args.user_id,
        pipeline_id="nf-core/rnaseq",
        revision="3.26.0",
        profile="docker",
        parameters={
            "test_profile": True,
            "max_cpus": args.max_cpus,
            "max_memory": args.max_memory,
        },
        artifact_paths={},
        resume=args.resume,
        network_allowed=True,
        timeout_seconds=args.timeout,
    )
    _emit("plan", plan.public())
    result = await backend.execute(plan)
    _emit("result", result.to_dict())
    return 0 if result.status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("runtime-validation"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--max-cpus", type=int, default=4)
    parser.add_argument("--max-memory", default="7 GB")
    parser.add_argument("--timeout", type=int, default=7_200)
    parser.add_argument("--resume", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
