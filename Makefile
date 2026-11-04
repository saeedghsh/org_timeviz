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
EMACS ?= emacs
ELISP_FILES = $(wildcard org_timeviz/org_source/elisp/*.el)

.PHONY: test
test: ## Run the tests, failing below the configured coverage threshold.
	@echo "\n=== Running tests ==="
	@$(UV_RUN) pytest

.PHONY: coverage
coverage: ## Report coverage of the last test run, also as HTML in output/htmlcov.
	@echo "\n=== Generating coverage report ==="
	@$(UV_RUN) coverage report
	@$(UV_RUN) coverage html

.PHONY: format
format: ## Format Python code with Ruff.
	@echo "\n=== Formatting Python files ==="
	@$(UV_RUN) ruff format .

.PHONY: format-check
format-check: ## Check Python formatting with Ruff without changing files.
	@echo "\n=== Checking code formatting ==="
	@$(UV_RUN) ruff format --check .

.PHONY: lint
lint: ## Run Ruff lint checks.
	@echo "\n=== Linting Python files ==="
	@$(UV_RUN) ruff check .

.PHONY: lint-fix
lint-fix: ## Apply Ruff's safe automatic lint fixes.
	@echo "\n=== Applying Ruff lint fixes ==="
	@$(UV_RUN) ruff check --fix .

# Earlier names, kept for compatibility.
.PHONY: formatter linter
formatter: format-check
linter: lint

# ty is fast but does not yet enforce annotations or match all of mypy's
# strict checks, so mypy keeps running in strict mode alongside it.
.PHONY: type-check
type-check: ## Type-check with ty and with mypy in strict mode.
	@echo "\n=== Running type checks ==="
	@$(UV_RUN) ty check
	@$(UV_RUN) mypy .

.PHONY: elisp-check
elisp-check: ## Byte-compile the Emacs Lisp exporters, treating warnings as errors.
	@echo "\n=== Checking Emacs Lisp ==="
	@$(EMACS) --batch -Q --load scripts/check-elisp.el $(ELISP_FILES)

.PHONY: code-quality
code-quality: ## Run every non-mutating check: format, lint, types, Emacs Lisp, tests.
	@$(MAKE) format-check
	@$(MAKE) lint
	@$(MAKE) type-check
	@$(MAKE) elisp-check
	@$(MAKE) test
