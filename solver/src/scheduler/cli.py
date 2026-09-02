"""Scheduler command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .backends import BACKENDS, DEFAULT_BACKEND
from .errors import InvalidInstanceError, SchedulerError
from .instance import Instance
from .progress import silent, to_stderr
from .solve import solve_instance

__all__ = ["main"]


def _read_json(path: str) -> Any:
    raw = _read_file(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"{path}: invalid JSON ({exc})") from exc


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SchedulerError(f"{path}: {exc.strerror}") from exc


def _write(text: str, output: str | Path | None) -> None:
    """stdout when there is no path, otherwise the file. OSError becomes ours."""
    if output is None:
        print(text)
        return
    try:
        Path(output).write_text(text, encoding="utf-8")
    except OSError as exc:
        raise SchedulerError(f"{output}: {exc.strerror}") from exc
    print(f"wrote {output}", file=sys.stderr)


def _solve_output_paths(args: argparse.Namespace) -> tuple[Path, Path, Path] | None:
    """Return the result, schedule, and instance paths for a file-backed solve."""
    if args.instance == "-" and args.output is None:
        return None

    if args.output is not None:
        result = Path(args.output)
    else:
        source = Path(args.instance)
        folder = source if source.is_dir() else source.parent
        name = source.name if source.is_dir() else source.stem
        result = folder / "results" / f"{name}.json"

    stem = result.with_suffix("")
    schedule = Path(args.html) if args.html else stem.with_name(f"{stem.name}-schedule.html")
    instance = stem.with_name(f"{stem.name}-instance.html")
    try:
        result.parent.mkdir(parents=True, exist_ok=True)
        schedule.parent.mkdir(parents=True, exist_ok=True)
        instance.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SchedulerError(f"could not create the results directory: {exc}") from exc
    return result, schedule, instance


def _as_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str) + "\n"


def _read_instance(path: str) -> Any:
    """A YAML file or directory is config; anything else is legacy JSON."""
    if path == "-":
        raw = sys.stdin.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            from .config import loads as load_config_text

            return load_config_text(raw)
    config_path = Path(path)
    if config_path.is_dir() or path.lower().endswith((".yaml", ".yml")):
        from .config import load as load_config

        return load_config(config_path)
    return _read_json(path)


def _cmd_solve(args: argparse.Namespace) -> int:
    payload = _read_instance(args.instance)
    reporter = silent if args.quiet else to_stderr

    instance = Instance.from_payload(payload)
    if args.check:
        print(f"instance is valid: {instance.summary()}", file=sys.stderr)
        return 0

    result = solve_instance(
        instance, reporter, time_limit=args.time_limit, solver=args.solver
    )
    payload_result = result.to_dict()
    outputs = _solve_output_paths(args)
    if outputs is None:
        _write(_as_json(payload_result), None)
    else:
        from .report import instance_page, schedule_page

        result_path, schedule_path, instance_path = outputs
        _write(_as_json(payload_result), result_path)
        _write(schedule_page(payload, payload_result), schedule_path)
        _write(instance_page(payload), instance_path)

    if not args.quiet:
        print(
            f"\n{result.status} via {result.solver}: {len(result.assignments)} assignments "
            f"({len(result.unstaffed)} unstaffed, "
            f"{len(result.unscheduled)} unscheduled, "
            f"{len(result.off_campus)} off campus)",
            file=sys.stderr,
        )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """No --result renders the inputs; with one, the solved schedule."""
    from .report import instance_page, schedule_page

    payload = _read_instance(args.instance)
    Instance.from_payload(payload)  # a bad instance is worth catching here too
    if args.result is None:
        _write(instance_page(payload, title=args.title or "Scheduling Instance"), args.output)
    else:
        result = _read_json(args.result)
        _write(schedule_page(payload, result, title=args.title or "Solved Schedule"), args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scheduler",
        description="Course workload allocation solver.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    solve_cmd = subcommands.add_parser("solve", help="solve an instance")
    solve_cmd.add_argument(
        "instance",
        help="split-instance directory, YAML/JSON file, or - for stdin",
    )
    solve_cmd.add_argument(
        "-o", "--output", metavar="PATH",
        help="override the result JSON path (HTML reports are written beside it)",
    )
    solve_cmd.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    solve_cmd.add_argument(
        "--check", action="store_true", help="validate the instance and stop without solving"
    )
    solve_cmd.add_argument(
        "--solver", choices=BACKENDS, default=DEFAULT_BACKEND,
        help=f"which solver to use (default {DEFAULT_BACKEND}; gurobi needs a licence)",
    )
    solve_cmd.add_argument(
        "--time-limit", type=float, metavar="SECONDS",
        help="give up proving optimality after this long per stage; the result "
             "is still returned, with status 'feasible'",
    )
    solve_cmd.add_argument(
        "--html", metavar="PATH", help="override the schedule HTML path"
    )
    solve_cmd.set_defaults(handler=_cmd_solve)

    report_cmd = subcommands.add_parser(
        "report", help="render an instance, or a solved schedule, as an HTML page"
    )
    report_cmd.add_argument(
        "instance", help="split-instance directory, .yaml config, or legacy JSON instance"
    )
    report_cmd.add_argument(
        "--result", help="a result JSON; without it the page shows the inputs instead"
    )
    report_cmd.add_argument("-o", "--output", required=True, help="write the HTML page here")
    report_cmd.add_argument("--title", help="page title (default depends on the page)")
    report_cmd.set_defaults(handler=_cmd_report)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except InvalidInstanceError as exc:
        print(f"invalid instance: {exc}", file=sys.stderr)
        return 2
    except SchedulerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
