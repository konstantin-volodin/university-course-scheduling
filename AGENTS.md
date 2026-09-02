# Repository Guidelines

## Project Structure & Module Organization

The maintained application lives in `solver/`. Package code is under `solver/src/scheduler/`: configuration and validation feed the model, `program.py` defines the solver-neutral MIP, `backends/` provides HiGHS and optional Gurobi adapters, and `cli.py` exposes the command line. Tests mirror these concerns in `solver/tests/`, with reusable fixtures in `conftest.py`. Human-edited and test instances belong in `instances/`; generated JSON and HTML outputs go in `instances/results/`. Treat `data_inputs/` spreadsheets as source data and generated report HTML as rebuildable artifacts.

## Build, Test, and Development Commands

Run development commands from `solver/`. Use `uv`, not Poetry or direct `pip`; `uv.lock` is committed.

- `uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -e ".[dev]"` creates the development environment.
- `make check` runs Ruff, strict mypy, and the full pytest suite.
- `make test` runs tests; target one with `uv run pytest tests/test_model.py::test_name`.
- `make fmt` applies Ruff's safe fixes.
- `make example` solves the tiny JSON fixture.
- `make solve YAML=../instances/medium LIMIT=60` performs a bounded example solve and writes results. Always specify a time limit for direct `scheduler solve` calls.

## Coding Style & Naming Conventions

Use four-space indentation, Python type annotations, and a 100-character line limit. Ruff enforces imports, naming, modernization, and common bug patterns; mypy checks `src/` in strict mode. Name modules and functions `snake_case`, classes `PascalCase`, and constants `UPPER_SNAKE_CASE`. Preserve the one-way core dependency flow: configuration/instance → model → program, with solver-specific behavior isolated in `backends/`.

## Testing Guidelines

Pytest uses strict markers and discovers `solver/tests/test_*.py`. Add focused regression tests beside the affected subsystem. Mark tests taking more than a second with `@pytest.mark.slow`. For model changes, verify legality and determinism as well as objective values. Run `make check` before submitting.

## Commit & Pull Request Guidelines

Recent commits use short, imperative, scoped subjects such as `report: cap a slot group` and `make: fix the report titles`. Keep each commit focused and explain consequential deletions. Pull requests should summarize behavior changes, identify the instance or fixture used, list exact verification commands and results, and link relevant issues. Include screenshots when report HTML changes; regenerate outputs instead of editing them manually. Never commit solver logs, licenses, credentials, or machine-specific virtual environments.
