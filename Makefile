PYTHON ?= uv run python

BOOTSTRAP := python scripts/bootstrap_env.py

.DEFAULT_GOAL := help

.PHONY: pretest
pretest:
	@$(PYTHON) scripts/dev/clean_pycache.py

.PHONY: test-unit
test-unit: pretest
	@uv run pytest -q backend/tests/unit

# Integration/e2e/stress are excluded by default in pytest.ini (-m "not integration").
# Run them explicitly with -m integration or by path with marker override.
.PHONY: test-integration
test-integration: pretest
	@uv run pytest backend/tests/integration -m integration -v

.PHONY: test-e2e
test-e2e: pretest
	@uv run pytest backend/tests/e2e -m integration -v

.PHONY: test-stress
test-stress: pretest
	@uv run pytest backend/tests/stress -v

.PHONY: reliability-gate
reliability-gate: pretest
	@uv run python backend/scripts/verify/reliability_gate.py --phase full

.PHONY: reliability-gate-integration
reliability-gate-integration: pretest
	@uv run python backend/scripts/verify/reliability_gate.py --phase full --include-integration --include-stress

.PHONY: docker-up
docker-up:
	@if [ -f "docker-compose.yml" ] || [ -f "compose.yml" ]; then \
		docker compose up --build; \
	else \
		echo "No docker-compose file found. Docker path is community/experimental in this repo."; \
		echo 'Use: docker run -it --rm -v "$$PWD:/work" -w /work -e LLM_API_KEY=$${LLM_API_KEY} ghcr.io/josephsenior/grinta:latest'; \
		exit 1; \
	fi

.PHONY: docker-up-detached
docker-up-detached:
	@if [ -f "docker-compose.yml" ] || [ -f "compose.yml" ]; then \
		docker compose up --build -d; \
	else \
		echo "No docker-compose file found. Docker path is community/experimental in this repo."; \
		exit 1; \
	fi

.PHONY: docker-up-no-db
docker-up-no-db:
	@if [ -f "docker-compose.yml" ] || [ -f "compose.yml" ]; then \
		docker compose up --build; \
	else \
		echo "No docker-compose file found. Docker path is community/experimental in this repo."; \
		exit 1; \
	fi

# Makefile for the current Grinta CLI/TUI contributor workflow
SHELL=/usr/bin/env bash

# Variables
BACKEND_HOST ?= "127.0.0.1"
BACKEND_PORT ?= 3000
PRE_COMMIT_CONFIG_PATH = "./.pre-commit-config.yaml"
PYTHON_VERSION = 3.12

# ANSI color codes
GREEN=$(shell tput -Txterm setaf 2)
YELLOW=$(shell tput -Txterm setaf 3)
RED=$(shell tput -Txterm setaf 1)
BLUE=$(shell tput -Txterm setaf 6)
RESET=$(shell tput -Txterm sgr0)

# Build
build:
	@echo "$(GREEN)Building project...$(RESET)"
	@$(MAKE) -s check-dependencies
	@$(MAKE) -s install-python-dependencies
	@$(MAKE) -s install-pre-commit-hooks
	@echo "$(GREEN)Build completed successfully.$(RESET)"

check-dependencies:
	@echo "$(YELLOW)Checking dependencies...$(RESET)"
	@$(MAKE) -s check-system
	@$(MAKE) -s check-python
	@$(MAKE) -s check-uv
	@$(MAKE) -s check-tmux
	@echo "$(GREEN)Dependencies checked successfully.$(RESET)"

check-system:
	@echo "$(YELLOW)Checking system...$(RESET)"
	@if [ "$(shell uname)" = "Darwin" ]; then \
		echo "$(BLUE)macOS detected.$(RESET)"; \
	elif [ "$(shell uname)" = "Linux" ]; then \
		if [ -f "/etc/manjaro-release" ]; then \
			echo "$(BLUE)Manjaro Linux detected.$(RESET)"; \
		else \
			echo "$(BLUE)Linux detected.$(RESET)"; \
		fi; \
	elif [ "$$(uname -r | grep -i microsoft)" ]; then \
		echo "$(BLUE)Windows Subsystem for Linux detected.$(RESET)"; \
	else \
		echo "$(RED)Unsupported system detected. Please use macOS, Linux, or Windows Subsystem for Linux (WSL).$(RESET)"; \
		exit 1; \
	fi

check-python:
	@echo "$(YELLOW)Checking Python installation...$(RESET)"
	@if command -v python$(PYTHON_VERSION) > /dev/null; then \
		echo "$(BLUE)$(shell python$(PYTHON_VERSION) --version) is already installed.$(RESET)"; \
	elif command -v uv > /dev/null; then \
		echo "$(BLUE)uv will manage the python version.$(RESET)"; \
	else \
		echo "$(RED)Python $(PYTHON_VERSION) is not installed. Please install Python $(PYTHON_VERSION) or uv to continue.$(RESET)"; \
		exit 1; \
	fi

check-uv:
	@echo "$(YELLOW)Checking uv installation...$(RESET)"
	@if command -v uv > /dev/null; then \
		echo "$(BLUE)$(shell uv --version) is already installed.$(RESET)"; \
	else \
		echo "$(RED)uv is not installed. You can install it by running:$(RESET)"; \
		echo "$(RED)curl -LsSf https://astral.sh/uv/install.sh | sh$(RESET)"; \
		exit 1; \
	fi

check-tmux:
	@echo "$(YELLOW)Ensuring tmux is installed (Linux/WSL)...$(RESET)"
	@uv run python -c "from backend.utils.linux_host_tools import ensure_linux_host_tools; ensure_linux_host_tools()" 2>/dev/null || true
	@if command -v tmux > /dev/null; then \
		echo "$(BLUE)$(shell tmux -V) is ready.$(RESET)"; \
	else \
		echo "$(YELLOW)tmux is not available yet; Grinta will retry on launch.$(RESET)"; \
	fi

.PHONY: bootstrap-base
bootstrap-base:
	@$(BOOTSTRAP) base

.PHONY: bootstrap-browser
bootstrap-browser:
	@$(BOOTSTRAP) browser

.PHONY: bootstrap-dev
bootstrap-dev:
	@$(BOOTSTRAP) dev

.PHONY: bootstrap-dev-test
bootstrap-dev-test:
	@$(BOOTSTRAP) dev-test

.PHONY: bootstrap-dev-test-browser
bootstrap-dev-test-browser:
	@$(BOOTSTRAP) dev-test-browser

install-python-dependencies:
	@echo "$(GREEN)Syncing Python dependencies...$(RESET)"
	@if [ -z "${TZ}" ]; then \
		echo "Defaulting TZ (timezone) to UTC"; \
		export TZ="UTC"; \
	fi
	@if [ "$(shell uname)" = "Darwin" ]; then \
		echo "$(BLUE)Installing chroma-hnswlib for macOS...$(RESET)"; \
		export HNSWLIB_NO_NATIVE=1; \
		uv pip install chroma-hnswlib; \
	fi
	@$(MAKE) -s bootstrap-base
	@echo "$(GREEN)Python dependencies synced successfully.$(RESET)"

install-pre-commit-hooks: check-python check-uv install-python-dependencies
	@echo "$(YELLOW)Installing pre-commit hooks...$(RESET)"
	@git config --unset-all core.hooksPath || true
	@uv run pre-commit install --config $(PRE_COMMIT_CONFIG_PATH)
	@echo "$(GREEN)Pre-commit hooks installed successfully.$(RESET)"

lint: install-pre-commit-hooks
	@echo "$(YELLOW)Running linters...$(RESET)"
	@uv run pre-commit run --all-files --show-diff-on-failure --config $(PRE_COMMIT_CONFIG_PATH)

# Proto compilation
.PHONY: compile-protos
compile-protos:
	@echo "$(GREEN)Compiling Protocol Buffer definitions...$(RESET)"
	@uv run python backend/scripts/build/compile_protos.py
	@echo "$(GREEN)Proto compilation completed.$(RESET)"

.PHONY: update-openapi
update-openapi:
	@echo "$(GREEN)Regenerating OpenAPI schema...$(RESET)"
	@uv run python backend/scripts/build/update_openapi.py
	@echo "$(GREEN)OpenAPI schema updated at openapi.json.$(RESET)"

# Start backend
start-backend:
	@echo "$(YELLOW)Starting backend...$(RESET)"
	@uv run uvicorn backend.execution.action_execution_server:app --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload --reload-exclude "./workspace"

.PHONY: init-cli
init-cli:
	@echo "$(YELLOW)Launching interactive CLI setup...$(RESET)"
	@uv run python -m backend.cli.entry init

.PHONY: run-cli
run-cli:
	@echo "$(YELLOW)Launching Grinta from the source checkout...$(RESET)"
	@uv run python -m backend.cli.entry

.PHONY: smoke-onboarding
smoke-onboarding:
	@echo "$(YELLOW)Running onboarding smoke checks (wheel + source)...$(RESET)"
	@uv build --wheel
	@WHEEL_DIR=./dist ./scripts/smoke_install.sh
	@./scripts/smoke_source_onboarding.sh
	@echo "$(GREEN)Onboarding smoke checks completed.$(RESET)"

.PHONY: run
run: run-cli

.PHONY: setup-config
setup-config: init-cli

# Clean up all caches
clean:
	@echo "$(YELLOW)Cleaning up caches...$(RESET)"
	@rm -rf backend/.cache
	@echo "$(GREEN)Caches cleaned up successfully.$(RESET)"

# Help
help:
	@echo "$(BLUE)Usage: make [target]$(RESET)"
	@echo "Targets:"
	@echo "  $(GREEN)bootstrap-dev-test$(RESET)  - Sync the source-checkout dev + test dependency profile."
	@echo "  $(GREEN)init-cli$(RESET)            - Run the interactive 'grinta init' flow from source."
	@echo "  $(GREEN)run-cli$(RESET)             - Launch the Grinta CLI/TUI from source."
	@echo "  $(GREEN)test-unit$(RESET)           - Run the unit test suite."
	@echo "  $(GREEN)reliability-gate$(RESET)    - Run the full local reliability verification gate."
	@echo "  $(GREEN)smoke-onboarding$(RESET)    - Build a wheel and run wheel + source onboarding smokes."
	@echo "  $(GREEN)lint$(RESET)                - Run pre-commit across the repository."
	@echo "  $(GREEN)build$(RESET)               - Bootstrap dependencies and install pre-commit hooks."
	@echo "  $(GREEN)run$(RESET)                 - Compatibility alias for run-cli."
	@echo "  $(GREEN)setup-config$(RESET)        - Compatibility alias for init-cli."
	@echo "  $(GREEN)start-backend$(RESET)       - Legacy maintenance target for the action execution server."
	@echo "  $(GREEN)compile-protos$(RESET)      - Rebuild protobuf-generated files."
	@echo "  $(GREEN)update-openapi$(RESET)      - Refresh the generated OpenAPI schema."
	@echo "  $(GREEN)help$(RESET)                - Show this target summary."

# Phony targets
.PHONY: build check-dependencies check-system check-python check-uv install-python-dependencies install-pre-commit-hooks lint start-backend init-cli run-cli smoke-onboarding run setup-config clean help
