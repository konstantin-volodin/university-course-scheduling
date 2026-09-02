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
from typing import Protocol

__all__ = ["Progress", "ProgressCallback", "silent", "to_stderr"]


class ProgressCallback(Protocol):
    """Called as the solve advances. Must not raise."""

    def __call__(self, stage: str, message: str) -> None: ...


def to_stderr(stage: str, message: str) -> None:
    """Default reporter. stderr, never stdout — stdout carries the JSON result."""
    print(f"[{stage}] {message}", file=sys.stderr, flush=True)


def silent(stage: str, message: str) -> None:
    """Report nothing."""


class Progress:
    """Forwards each line to a callback, tagged with the current stage."""

    def __init__(self, callback: ProgressCallback | None = None) -> None:
        self._callback: ProgressCallback = callback if callback is not None else to_stderr
        self.stage = "starting"

    def __call__(self, message: str) -> None:
        # A broken reporter must never kill an hour-long solve.
        with suppress(Exception):
            self._callback(self.stage, message)

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
        self(f"{message} ...")
        outcome = "done"

        def set_outcome(text: str) -> None:
            nonlocal outcome
            outcome = text

        started = time.perf_counter()
        yield set_outcome
        self(f"{message}: {outcome} ({time.perf_counter() - started:,.2f}s)")
