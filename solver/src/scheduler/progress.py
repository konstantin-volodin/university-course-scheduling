"""Progress reporting.

A solve takes minutes to hours, so the caller needs to see it move. Everything
the solver has to say goes to a callback, as it happens — which is what a
caller polling a status row or tailing a log actually needs. Nothing is
accumulated here: a caller who wants a transcript appends to a list.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime

__all__ = [
    "Progress",
    "ProgressCallback",
    "format_line",
    "silent",
    "to_stderr",
]


type ProgressCallback = Callable[[str, str], None]


def to_stderr(stage: str, message: str) -> None:
    """Default reporter. stderr, never stdout — stdout carries the JSON result."""
    print(format_line(stage, message), file=sys.stderr, flush=True)


def format_line(stage: str, message: str) -> str:
    """One consistent timestamped format for console and diagnostic files."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level = "WARNING" if stage == "warning" else "INFO"
    return f"{timestamp} {level:7} [{stage}] {message}"


def silent(stage: str, message: str) -> None:
    """Report nothing."""


class Progress:
    """Forwards each line to a callback, tagged with the current stage."""

    def __init__(self, callback: ProgressCallback | None = None) -> None:
        self._callback: ProgressCallback = callback if callback is not None else to_stderr
        self.stage = "starting"

    def __call__(self, message: str, *, stage: str | None = None) -> None:
        # A broken reporter must never kill an hour-long solve.
        with suppress(Exception):
            self._callback(stage or self.stage, message)

    @contextmanager
    def step(self, stage: str, message: str) -> Iterator[Callable[[str], None]]:
        """Time a step, then report how it went.

        The body is handed a function to set the outcome text, so a step can say
        "1,284 variables" rather than a bare "done".

            with progress.step("building", "viable set") as done:
                ...
                done(f"{len(viable):,} variables")
        """
        self.stage = stage
        outcome: str | None = None

        def set_outcome(text: str) -> None:
            nonlocal outcome
            outcome = text

        started = time.perf_counter()
        yield set_outcome
        elapsed = time.perf_counter() - started
        suffix = f": {outcome}" if outcome is not None else ""
        self(f"done in {elapsed:,.2f}s - {message}{suffix}")
