# University Course Scheduling

This repository contains a mixed-integer programming (MIP) model for producing a 2020
Telfer course schedule. See the [model manuscript](solver/model/manuscript.pdf).

The full input is defined in [`instances/telfer/`](instances/telfer/). Smaller examples are
available in [`instances/`](instances/).

## Run

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
cd solver
uv python install 3.14
uv sync --python 3.14 --extra dev
uv run scheduler solve ../instances/telfer --time-limit 900
```

Validate the instance without solving it:

```bash
uv run scheduler solve ../instances/telfer --check
```

See [`solver/README.md`](solver/README.md) for more commands.
