# University Course Scheduling

A mixed-integer programming scheduler for faculty, rooms, and weekly meeting bundles.
Start with the [editable template](instances/template/instance.yaml) and
[input guide](instances/README.md). Telfer rules are an explicit institution preset.

The [formulation manuscript source](solver/model/manuscript.tex) can be built with
`bash solver/model/build.sh`; the generated PDF is not versioned.

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
