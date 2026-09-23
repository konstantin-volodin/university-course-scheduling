"""Scheduler command line interface."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .backends import BACKENDS, DEFAULT_BACKEND
from .config import Instance
from .errors import InvalidInstanceError, SchedulerError
from .progress import ProgressCallback, TeeProgress, TerminalProgress, silent, to_stderr
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


def _solve_output_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path] | None:
    """Return the result, schedule, and instance paths for a file-backed solve."""
    if args.instance == "-" and args.output is None:
        return None

    if args.output is not None:
        result = Path(args.output)
    else:
        source = Path(args.instance)
        folder = source if source.is_dir() else source.parent
        result = folder / "results" / "result.json"

    # The pages already sit in the instance's own results/, so a name prefix
    # would only repeat the folder: instance/results/instance-instance.html.
    schedule = Path(args.html) if args.html else result.with_name("schedule.html")
    instance = result.with_name("instance.html")
    objective = result.with_name("objective.md")
    targets = [result, schedule, instance, objective, result.with_name("solve.log")]
    resolved = [target.resolve() for target in targets]
    if len(set(resolved)) != len(resolved) or any(
        target.exists() and previous.exists() and target.samefile(previous)
        for index, target in enumerate(targets) for previous in targets[:index]
    ):
        raise SchedulerError("solve output paths must be distinct, including solve.log")
    if args.instance != "-":
        source = Path(args.instance)
        if source.is_dir():
            source = source / "instance.yaml"
        inputs = {source.resolve()}
        if source.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            manifest = yaml.safe_load(source.read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and isinstance(manifest.get("files"), dict):
                for paths in manifest["files"].values():
                    for path in [paths] if isinstance(paths, str) else paths:
                        inputs.add((source.parent / path).resolve())
        if inputs.intersection(resolved) or any(
            target.exists() and source.exists() and target.samefile(source)
            for target in targets for source in inputs
        ):
            raise SchedulerError("solve outputs must not overwrite the input instance")
    try:
        result.parent.mkdir(parents=True, exist_ok=True)
        schedule.parent.mkdir(parents=True, exist_ok=True)
        instance.parent.mkdir(parents=True, exist_ok=True)
        objective.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SchedulerError(f"could not create the results directory: {exc}") from exc
    return result, schedule, instance, objective


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
    instance = Instance.from_payload(payload)
    if args.check:
        print(f"instance is valid: {instance.summary()}", file=sys.stderr)
        return 0

    outputs = _solve_output_paths(args)
    live_reporter = silent if args.quiet else (
        TerminalProgress() if sys.stderr.isatty() else to_stderr
    )
    log_file = None
    if outputs is not None:
        log_file = (outputs[0].with_name("solve.log")).open("w", encoding="utf-8")
        reporter: ProgressCallback = TeeProgress(live_reporter, log_file)
    else:
        reporter = live_reporter
    try:
        result = solve_instance(
            instance, reporter, time_limit=args.time_limit, solver=args.solver
        )
    finally:
        if log_file is not None:
            log_file.close()
    payload_result = result.to_dict()
    if outputs is None:
        _write(_as_json(payload_result), None)
    else:
        from .report import instance_page, objective_markdown, schedule_page

        result_path, schedule_path, instance_path, objective_path = outputs
        _write(_as_json(payload_result), result_path)
        _write(schedule_page(payload, payload_result), schedule_path)
        _write(instance_page(payload), instance_path)
        _write(objective_markdown(payload_result), objective_path)

    if result.unscheduled:
        print(
            f"warning: incomplete timetable: {len(result.unscheduled)} of "
            f"{len(result.assignments)} sections have no timeslot. Solver feasibility "
            "allows unscheduled placeholders; it does not mean the timetable is ready to use.",
            file=sys.stderr,
        )
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


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a finite, positive number of seconds")
    return seconds


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
        "--time-limit", type=_positive_seconds, metavar="SECONDS",
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
    except (SchedulerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
