PY := .venv/bin/python

.PHONY: check test lint types fmt example solve report clean help

help:
	@echo "make check    lint + types + tests"
	@echo "make test     pytest"
	@echo "make lint     ruff"
	@echo "make types    mypy --strict"
	@echo "make fmt      ruff --fix"
	@echo "make example  solve the example instance (JSON on stdout)"
	@echo "make solve    solve YAML=<file> and write the JSON + both HTML pages"
	@echo "make report   re-render the HTML pages from an existing result (no re-solve)"
	@echo ""
	@echo "  make solve                                    the real 2026 instance (~30 min)"
	@echo "  make solve YAML=../instances/medium LIMIT=60       medium example (~1 min)"

check: lint types test

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

types:
	$(PY) -m mypy

fmt:
	$(PY) -m ruff check --fix .

# @ so the recipe is not echoed: stdout here must be JSON and nothing else.
example:
	@$(PY) -m scheduler solve ../instances/tiny.yaml

# One instance, one place to say which. Override any of these on the command
# line:  make solve YAML=../instances/medium LIMIT=60
YAML  ?= ../instances/telfer
LIMIT ?= 900
OUT   ?= ../instances/results
TITLE ?= Telfer
NAME  := $(basename $(notdir $(YAML)))

# Solve, then write the schedule page and the inputs page beside the result.
# LIMIT is per stage, and stage 4 always uses all of it -- budget 4x LIMIT.
solve:
	@mkdir -p $(OUT)
	$(PY) -m scheduler solve $(YAML) --time-limit $(LIMIT) -o $(OUT)/$(NAME).json
	@$(MAKE) --no-print-directory report YAML=$(YAML) OUT=$(OUT) TITLE='$(TITLE)'
	@echo ""
	@echo "  result   $(OUT)/$(NAME).json"
	@echo "  schedule $(OUT)/$(NAME)-schedule.html"
	@echo "  inputs   $(OUT)/$(NAME)-instance.html"

# Re-render the pages from a result that already exists: seconds, not half an
# hour, because it does not re-solve.
report:
	@mkdir -p $(OUT)
	$(PY) -m scheduler report $(YAML) -o $(OUT)/$(NAME)-instance.html \
		--title '$(TITLE) Instance'
	$(PY) -m scheduler report $(YAML) --result $(OUT)/$(NAME).json \
		-o $(OUT)/$(NAME)-schedule.html --title '$(TITLE) Schedule'

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
