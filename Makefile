SHELL := /bin/bash

.PHONY: help init install lint lint-fix format test clean

help:
	@echo "Targets:"
	@echo "  make init     Sync dependencies from uv.lock"
	@echo "  make install  Alias for init"
	@echo "  make test     Run pytest"
	@echo "  make lint     Run ruff check"
	@echo "  make format   Run ruff format"
	@echo "  make clean    Remove .venv and caches"
	@echo ""
	@echo "Note: make cannot activate your shell. After init, if needed:"
	@echo "  source .envrc"

init:
	@echo "Syncing dependencies (uv.lock)..."
	@uv sync
	@venv="$(CURDIR)/.venv"; \
	if [ -n "$$VIRTUAL_ENV" ] && [ "$$VIRTUAL_ENV" = "$$venv" ]; then \
		echo "venv already active."; \
	else \
		echo "Not active — run: source .envrc"; \
	fi

install: init

lint: init
	@uv run ruff check .

lint-fix: init
	@uv run ruff check --fix .

format: init
	@uv run ruff format .

test: init
	@uv run pytest

clean:
	@rm -rf .venv .ruff_cache .pytest_cache .coverage htmlcov
	@find . -type d -name '__pycache__' -not -path './.git/*' -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '*.egg-info' -not -path './.git/*' -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '.pytest_cache' -not -path './.git/*' -exec rm -rf {} + 2>/dev/null || true
