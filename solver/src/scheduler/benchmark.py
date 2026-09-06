"""Reproducible bounded runs: ``python -m scheduler.benchmark --help``."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from importlib import metadata
from pathlib import Path
from typing import Any

from . import config
from .audit import audit_result
from .config import Instance
from .progress import silent
from .solve import solve_instance


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return seconds


def _positive_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if count < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return count


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _git_state() -> dict[str, Any]:
    """Identify the checkout containing this module; installed wheels may lack one."""
    try:
        def git(*arguments: str) -> str:
            return subprocess.run(
                ["git", *arguments], cwd=Path(__file__).resolve().parent,
                capture_output=True, text=True, check=True, timeout=5,
            ).stdout.strip()

        return {
            "revision": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
        }
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None}


def _run(source: Path, repetition: int, solver: str, time_limit: float) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source": str(source), "repetition": repetition, "payload_sha256": None,
    }
    start = time.perf_counter()
    try:
        payload = config.load(source)
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        record["payload_sha256"] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        record["input_payload"] = json.loads(normalized)
        instance = Instance.from_payload(payload)
        result = solve_instance(instance, progress=silent, time_limit=time_limit, solver=solver)
        result_dict = result.to_dict()
        # Reject nonfinite results within the run boundary so other runs still execute.
        json.dumps(result_dict, allow_nan=False)
        findings = audit_result(instance, result)
        record.update(
            result=result_dict,
            audit={"passed": not findings, "issues": [asdict(issue) for issue in findings]},
        )
        if findings:
            raise ValueError(f"Independent schedule audit found {len(findings)} hard-rule failures")
        record["status"] = "success"
    except Exception as exc:  # A failed benchmark must not discard other repetitions.
        record.update(status="error", error={"type": type(exc).__name__, "message": str(exc)})
    record["elapsed_seconds"] = time.perf_counter() - start
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instances", nargs="+", type=Path)
    parser.add_argument("--time-limit", required=True, type=_positive_seconds,
                        help="positive finite seconds per solve stage, not per complete run")
    parser.add_argument("--repeat", type=_positive_count, default=1)
    parser.add_argument("--solver", choices=("highs", "gurobi"), default="highs")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    sources = [source.resolve() for source in args.instances]
    output = args.output.resolve()
    protected_roots = [
        source if source.is_dir() else source.parent
        for source in sources
        if source.is_dir() or (source.is_file() and source.name == "instance.yaml")
    ]
    if output in sources or any(output.is_relative_to(root) for root in protected_roots):
        parser.error("--output must be outside the input instance paths")

    document = {
        "schema_version": 1,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {name: _version(name) for name in
                         ("workload-scheduler", "highspy", "gurobipy", "pyyaml")},
            "git": _git_state(),
        },
        "solver": args.solver,
        "time_limit_per_stage_seconds": args.time_limit,
        "repetitions": args.repeat,
        "timing_scope": "load, hash, validate, build, solve, independent hard-rule audit, "
                        "and result serialization validation; "
                        "excludes environment collection and report file writing",
        "runs": [],
    }
    runs = [_run(source, repetition, args.solver, args.time_limit)
            for source in sources for repetition in range(1, args.repeat + 1)]
    document["runs"] = runs
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"Could not write benchmark report: {exc}", file=sys.stderr)
        return 1
    return int(any(run["status"] == "error" for run in runs))


if __name__ == "__main__":
    raise SystemExit(main())
