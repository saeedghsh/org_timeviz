.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

########################################
########################################
########################################
UV ?= uv
SERVE_PORT ?= 8000

# `uv run` creates or updates .venv from uv.lock before running a command.
# --locked fails instead of rewriting uv.lock when it is out of date.
UV_RUN = $(UV) run --locked

.PHONY: sync
sync: ## Create or update .venv from uv.lock, including development tools.
	@$(UV) sync --locked

.PHONY: run
run: ## Generate reports.
	@$(UV_RUN) python -m org_timeviz

.PHONY: serve
serve: ## Generate and serve reports with browser refresh support.
	@$(UV_RUN) python -m org_timeviz.server --port $(SERVE_PORT)

.PHONY: other_catalogue
other_catalogue: ## Write CSV of unmapped tags contributing to the other time bucket.
	@$(UV_RUN) python -m org_timeviz.other_catalogue

########################################
################### CODE QUALITY TARGETS
########################################
.PHONY: test
test:
	@echo "\n=== Running tests ==="
	@$(UV_RUN) pytest --cov=. --cov-report html:output/htmlcov

.PHONY: coverage
coverage:
	@echo "\n=== Generating coverage report ==="
	@$(UV_RUN) coverage report -m

.PHONY: formatter
formatter: ## Check code formatting with Ruff.
	@echo "\n=== Checking code formatting ==="
	@$(UV_RUN) ruff format --check .

.PHONY: format
format: ## Format Python code with Ruff.
	@echo "\n=== Formatting Python files ==="
	@$(UV_RUN) ruff format .

.PHONY: linter
linter: ## Run Ruff lint checks.
	@echo "\n=== Linting Python files ==="
	@$(UV_RUN) ruff check .

.PHONY: lint-fix
lint-fix: ## Apply Ruff's safe automatic lint fixes.
	@echo "\n=== Applying Ruff lint fixes ==="
	@$(UV_RUN) ruff check --fix .

.PHONY: type-check
type-check: ## Run static type checking.
	@echo "\n=== Running type checks (all) ==="
	@$(UV_RUN) mypy .

.PHONY: code-quality
code-quality: ## Run formatting, linting, typing, and unit tests.
	@$(MAKE) formatter
	@$(MAKE) linter
	@$(MAKE) type-check
	@$(MAKE) test
