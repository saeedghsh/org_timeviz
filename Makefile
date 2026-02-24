.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

########################################
########################################
########################################
ENV_FILE ?= environment.yaml
# Reads the first top-level `name:` from environment.yaml (e.g., `name: org_timeviz`)
ENV_NAME ?= $(shell awk -F: '/^name:/{gsub(/^[ \t]+/, "", $$2); print $$2; exit}' $(ENV_FILE))

CONDA ?= conda

.PHONY: ensure-env
ensure-env: ## Ensure the conda env exists (create it if missing).
	@$(CONDA) env list | awk '{print $$1}' | grep -Fxq "$(ENV_NAME)" \
		&& echo "conda env '$(ENV_NAME)' already exists." \
		|| (echo "conda env '$(ENV_NAME)' not found; creating..." && $(MAKE) create-env)

.PHONY: run
run: ensure-env ## Run `python -m main` inside the repo conda env.
	@$(CONDA) run -n $(ENV_NAME) --no-capture-output python -m main

########################################
###################### CONDA ENVIRONMENT
########################################
.PHONY: ensure-mamba
ensure-mamba: ## Ensure mamba is installed in the conda base environment.
	@conda list -n base mamba 1>/dev/null 2>&1 \
		&& echo "mamba already installed in conda base." \
		|| (echo "Installing mamba into conda base..." && conda install -n base -c conda-forge -y mamba)

.PHONY: create-env
create-env: ensure-mamba ## Create the conda environment for this repo.
	@echo "\n=== Creating conda virtual environment (using mamba) ==="
	ulimit -n 262144 && mamba env create -f environment.yaml

# syncs with environment.yaml
# does not update existing environment even if it is outdated and ignores lock file if it exists
.PHONY: update-env
update-env: ensure-mamba ## Update the conda environment to match the repo dependencies.
	@echo "\n=== Updating conda virtual environment (using mamba) ==="
	ulimit -n 262144 && mamba env update -f environment.yaml

########################################
################### CODE QUALITY TARGETS
########################################
.PHONY: test
test:
	@echo "\n=== Running tests ==="
	@pytest --cov=. --cov-report html:output/htmlcov

.PHONY: coverage
coverage:
	@echo "\n=== Generating coverage report ==="
	@coverage report -m

.PHONY: formatter
formatter: ## Check code formatting.
	@echo "\n=== Checking code formatting ==="
	@black --check .

.PHONY: linter
linter: ## Run the linter.
	@echo "\n=== Linting Python files (all) ==="
	@pylint $(shell git ls-files '*.py')

MYPY_OPTS = --install-types --non-interactive --explicit-package-bases --config-file=pyproject.toml --show-error-codes

.PHONY: type-check
type-check: ## Run static type checking.
	@echo "\n=== Running type checks (all) ==="
	@mypy $(MYPY_OPTS) .

.PHONY: code-quality
code-quality: ## Run the main code-quality checks (formatting, linting, typing).
	-@$(MAKE) formatter
	-@$(MAKE) type-check
	-@$(MAKE) linter
