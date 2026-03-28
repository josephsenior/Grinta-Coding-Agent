PYTHON ?= uv run python

.PHONY: pretest
pretest:
	@bash ./backend/scripts/dev/clean_pycache.sh

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
	@uv run python backend/scripts/verify/reliability_gate.py --phase full --include-integration

.PHONY: docker-up
docker-up:
	@FORGE_KB_STORAGE_TYPE=database docker compose up --build

.PHONY: docker-up-detached
docker-up-detached:
	@FORGE_KB_STORAGE_TYPE=database docker compose up --build -d

.PHONY: docker-up-no-db
docker-up-no-db:
	@FORGE_KB_STORAGE_TYPE=file docker compose up --build

# Makefile for Forge project
SHELL=/usr/bin/env bash

# Variables
BACKEND_HOST ?= "127.0.0.1"
BACKEND_PORT ?= 3000
BACKEND_HOST_PORT = "$(BACKEND_HOST):$(BACKEND_PORT)"
DEFAULT_LOCAL_DATA_DIR = "./workspace"
DEFAULT_MODEL = "gpt-4o"
CONFIG_FILE = settings.json
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
	@echo "$(YELLOW)Checking tmux installation...$(RESET)"
	@if command -v tmux > /dev/null; then \
		echo "$(BLUE)$(shell tmux -V) is already installed.$(RESET)"; \
	else \
		echo "$(YELLOW)╔════════════════════════════════════════════════════════════════════════════╗$(RESET)"; \
		echo "$(YELLOW)║ OPTIONAL: tmux is not installed.                                          ║$(RESET)"; \
		echo "$(YELLOW)║ Some advanced terminal features may not work without tmux.                ║$(RESET)"; \
		echo "$(YELLOW)║ You can install it if needed, but it's not required for development.      ║$(RESET)"; \
		echo "$(YELLOW)╚════════════════════════════════════════════════════════════════════════════╝$(RESET)"; \
	fi

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
	uv sync
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
	@uv run uvicorn backend.gateway.socketio_asgi_app:app --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload --reload-exclude "./workspace"

# Run the app
run:
	@echo "$(YELLOW)Running the app...$(RESET)"
	@mkdir -p logs
	@echo "$(YELLOW)Starting backend server...$(RESET)"
	@uv run uvicorn backend.gateway.socketio_asgi_app:app --host $(BACKEND_HOST) --port $(BACKEND_PORT) &
	@echo "$(YELLOW)Waiting for the backend to start...$(RESET)"
	@until nc -z localhost $(BACKEND_PORT); do sleep 0.1; done
	@echo "$(GREEN)Backend started successfully on $(BACKEND_HOST_PORT).$(RESET)"
	@echo "$(GREEN)Launch TUI with: uv run forge-tui$(RESET)"

# Setup settings.json
setup-config:
	@echo "$(YELLOW)Setting up Forge configuration...$(RESET)"
	@$(MAKE) setup-config-prompts
	@mv $(CONFIG_FILE).tmp $(CONFIG_FILE)
	@echo "$(GREEN)settings.json setup completed.$(RESET)"

setup-config-prompts:
	@echo '{"local_data_root":"$(DEFAULT_LOCAL_DATA_DIR)","llm_model":"$(DEFAULT_MODEL)","llm_api_key":"","llm_base_url":""}' > $(CONFIG_FILE).tmp
	@read -p "Enter local data root (LocalFileStore directory, absolute path) [default: $(DEFAULT_LOCAL_DATA_DIR)]: " data_root_dir; \
	 data_root_dir=$${data_root_dir:-$(DEFAULT_LOCAL_DATA_DIR)}; \
	 $(PYTHON) -c "import json; f='$(CONFIG_FILE).tmp'; d=json.load(open(f)); d['local_data_root']='$$data_root_dir'; json.dump(d, open(f,'w'), indent=2)"
	@read -p "Enter your LLM model name [default: $(DEFAULT_MODEL)]: " llm_model; \
	 llm_model=$${llm_model:-$(DEFAULT_MODEL)}; \
	 $(PYTHON) -c "import json; f='$(CONFIG_FILE).tmp'; d=json.load(open(f)); d['llm_model']='$$llm_model'; json.dump(d, open(f,'w'), indent=2)"
	@read -p "Enter your LLM API key: " llm_api_key; \
	 $(PYTHON) -c "import json; f='$(CONFIG_FILE).tmp'; d=json.load(open(f)); d['llm_api_key']='$$llm_api_key'; json.dump(d, open(f,'w'), indent=2)"
	@read -p "Enter your LLM base URL [mostly used for local LLMs, leave blank if not needed]: " llm_base_url; \
	 $(PYTHON) -c "import json; f='$(CONFIG_FILE).tmp'; d=json.load(open(f)); d['llm_base_url']='$$llm_base_url'; json.dump(d, open(f,'w'), indent=2)"

setup-config-basic:
	@cp settings.template.json settings.json 2>/dev/null || (echo '{"local_data_root":"./workspace","max_budget_per_task":5.0,"llm_model":"$(DEFAULT_MODEL)","llm_api_key":"","llm_base_url":""}' > settings.json)
	@echo "$(GREEN)settings.json created.$(RESET)"

# Clean up all caches
clean:
	@echo "$(YELLOW)Cleaning up caches...$(RESET)"
	@rm -rf backend/.cache
	@echo "$(GREEN)Caches cleaned up successfully.$(RESET)"

# Help
help:
	@echo "$(BLUE)Usage: make [target]$(RESET)"
	@echo "Targets:"
	@echo "  $(GREEN)build$(RESET)               - Build project, including environment setup and dependencies."
	@echo "  $(GREEN)lint$(RESET)                - Run linters on the project."
	@echo "  $(GREEN)setup-config$(RESET)        - Setup the configuration for Forge by providing LLM API key,"
	@echo "                        LLM Model name, and local data root directory."
	@echo "  $(GREEN)start-backend$(RESET)       - Start the backend server for the Forge project."
	@echo "  $(GREEN)run$(RESET)                 - Start the backend, then launch the TUI with: uv run forge-tui"
	@echo "  $(GREEN)help$(RESET)                - Display this help message, providing information on available targets."

# Phony targets
.PHONY: build check-dependencies check-system check-python check-uv install-python-dependencies install-pre-commit-hooks lint start-backend run setup-config setup-config-prompts setup-config-basic clean help

