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
from typing import Protocol, TextIO

__all__ = [
    "Progress",
    "ProgressCallback",
    "TeeProgress",
    "TerminalProgress",
    "silent",
    "to_stderr",
]


class ProgressCallback(Protocol):
    """Called as the solve advances. Must not raise."""

    def __call__(self, stage: str, message: str) -> None: ...


def to_stderr(stage: str, message: str) -> None:
    """Default reporter. stderr, never stdout — stdout carries the JSON result."""
    timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
    print(f"{timestamp} [{stage}] {message}", file=sys.stderr, flush=True)


def silent(stage: str, message: str) -> None:
    """Report nothing."""


class TerminalProgress:
    """Compact live reporter for an interactive terminal.

    It deliberately has no dependency or background thread. Long operations
    publish updates through :meth:`Progress.update`; ordinary stage messages
    finish the current line. Non-TTY callers should use :func:`to_stderr`.
    """

    def __init__(self) -> None:
        self._line_open = False

    def __call__(self, stage: str, message: str) -> None:
        if self._line_open:
            print(file=sys.stderr)
        timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        print(f"{timestamp} [{stage}] {message}", file=sys.stderr, flush=True)
        self._line_open = False

    def update(self, stage: str, message: str) -> None:
        self._line_open = True
        print(f"\r\033[K[{stage}] {message}", end="", file=sys.stderr, flush=True)


class TeeProgress:
    """Send progress to a live reporter and a plain timestamped log file."""

    def __init__(self, reporter: ProgressCallback, log: TextIO) -> None:
        self.reporter = reporter
        self.log = log

    @staticmethod
    def _line(stage: str, message: str) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        return f"{timestamp} [{stage}] {message}\n"

    def __call__(self, stage: str, message: str) -> None:
        self.reporter(stage, message)
        self.log.write(self._line(stage, message))
        self.log.flush()

    def update(self, stage: str, message: str) -> None:
        update = getattr(self.reporter, "update", self.reporter)
        update(stage, message)
        self.log.write(self._line(stage, message))
        self.log.flush()


class Progress:
    """Forwards each line to a callback, tagged with the current stage."""

    def __init__(self, callback: ProgressCallback | None = None) -> None:
        self._callback: ProgressCallback = callback if callback is not None else to_stderr
        self.stage = "starting"

    def __call__(self, message: str) -> None:
        # A broken reporter must never kill an hour-long solve.
        with suppress(Exception):
            self._callback(self.stage, message)

    def update(self, message: str) -> None:
        """Replace the current terminal status, or report a normal line."""
        with suppress(Exception):
            update = getattr(self._callback, "update", self._callback)
            update(self.stage, message)

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
