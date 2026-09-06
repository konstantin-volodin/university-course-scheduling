PY := .venv/bin/python

.PHONY: check test lint types fmt example solve report clean help

help:
	@echo "make check    lint + types + tests"
	@echo "make test     pytest"
	@echo "make lint     ruff"
	@echo "make types    mypy --strict"
	@echo "make fmt      ruff --fix"
	@echo "make example  solve the example instance and write all three outputs"
	@echo "make solve    solve YAML=<file> and write the JSON + both HTML pages"
	@echo "make report   re-render the HTML pages from an existing result (no re-solve)"
	@echo ""
	@echo "  make solve                                    Telfer (900 seconds per stage)"
	@echo "  make solve YAML=../instances/medium LIMIT=60       medium (60 seconds per stage)"

check: lint types test

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

types:
	$(PY) -m mypy

fmt:
	$(PY) -m ruff check --fix .

example:
	$(PY) -m scheduler solve ../instances/tiny --time-limit 30

# One instance, one place to say which. Override any of these on the command
# line:  make solve YAML=../instances/medium LIMIT=60
YAML  ?= ../instances/telfer
LIMIT ?= 900
# Outputs live in the instance folder's results/ -- the same place solve writes.
DIR   := $(if $(wildcard $(YAML)/.),$(YAML),$(patsubst %/,%,$(dir $(YAML))))
OUT   ?= $(DIR)/results

# Solve, then write the schedule page and the inputs page beside the result.
# LIMIT is per stage -- budget up to 10x LIMIT, plus preprocessing and reports.
solve:
	$(PY) -m scheduler solve $(YAML) --time-limit $(LIMIT)

# Re-render the pages from a result that already exists: seconds, not half an
# hour, because it does not re-solve.
report:
	@mkdir -p $(OUT)
	$(PY) -m scheduler report $(YAML) -o $(OUT)/instance.html
	$(PY) -m scheduler report $(YAML) --result $(OUT)/result.json \
		-o $(OUT)/schedule.html

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
