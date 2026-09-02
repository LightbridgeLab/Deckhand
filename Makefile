.PHONY: help install config \
	dev start stop restart status logs \
	menubar install-menubar \
	catalog-sync cli \
	test lint format check clean \
	opendeck-plugin-install \
	abandon merge deploy-preview deploy-prod \
	version bump-patch bump-minor bump-major set-version \
	_deckhand-dir
.DEFAULT_GOAL := help

BRANCH_PROD := main
SRC_DIRS    := src/ tests/ opendeck-plugin/
OPENDECK_PLUGIN_SRC := opendeck-plugin/com.deckhand.plugin.sdPlugin

HOST ?= 127.0.0.1
PORT ?= 18765
BASE_URL := http://$(HOST):$(PORT)
PID_FILE := .deckhand/server.pid
LOG_FILE := .deckhand/server.log
UVICORN  := uv run python -m uvicorn deckhand.main:app --app-dir src --host $(HOST) --port $(PORT)

ifeq ($(shell uname -s),Darwin)
OPENDECK_PLUGINS := $(HOME)/Library/Application Support/OpenDeck/Plugins
else
OPENDECK_PLUGINS := $(HOME)/.config/OpenDeck/Plugins
endif

# ── Colors ────────────────────────────────────────────────────────────────────

BOLD   := \033[1m
DIM    := \033[2m
RED    := \033[31m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m
RESET  := \033[0m

# ── Helpers ───────────────────────────────────────────────────────────────────

##@ Help

help: ## Show available targets
	@printf "$(BOLD)Deckhand$(RESET) $(DIM)— local Stream Deck / OpenDeck control$(RESET)\n\n"
	@awk 'BEGIN {FS = ":.*##"; printf ""} \
		/^##@/ {printf "\n$(GREEN)%s$(RESET)\n", substr($$0, 5); next} \
		/^[a-zA-Z0-9_-]+:.*?##/ {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n"

_deckhand-dir:
	@mkdir -p .deckhand

# ── Setup ─────────────────────────────────────────────────────────────────────

##@ Setup

install: ## Install all dependencies via uv
	uv sync --all-extras

config: ## Copy config.example.toml → config.toml if missing
	@if [ -f config.toml ]; then \
		printf "$(YELLOW)config.toml already exists — leaving it alone$(RESET)\n"; \
	else \
		cp config.example.toml config.toml; \
		printf "$(GREEN)Created config.toml from config.example.toml$(RESET)\n"; \
	fi

# ── Server ────────────────────────────────────────────────────────────────────

##@ Server

dev: ## Start dev server with hot reload (foreground)
	$(UVICORN) --reload

start: _deckhand-dir ## Start server in background (no reload)
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		printf "$(YELLOW)Already running$(RESET) (pid $$(cat "$(PID_FILE)")) — $(BASE_URL)\n"; \
		exit 0; \
	fi
	@if curl -sf "$(BASE_URL)/health" >/dev/null 2>&1; then \
		printf "$(YELLOW)Already running$(RESET) at $(BASE_URL) (no PID file)\n"; \
		exit 0; \
	fi
	@rm -f "$(PID_FILE)"
	@nohup $(UVICORN) >"$(LOG_FILE)" 2>&1 & echo $$! >"$(PID_FILE)"
	@printf "$(DIM)Waiting for $(BASE_URL)/health …$(RESET)\n"
	@i=0; \
	while [ $$i -lt 30 ]; do \
		if curl -sf "$(BASE_URL)/health" >/dev/null 2>&1; then \
			printf "$(GREEN)Started$(RESET) $(BASE_URL)  pid $$(cat "$(PID_FILE)")  log $(LOG_FILE)\n"; \
			exit 0; \
		fi; \
		if ! kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
			printf "$(RED)Failed to start$(RESET) — see $(LOG_FILE)\n"; \
			rm -f "$(PID_FILE)"; \
			exit 1; \
		fi; \
		sleep 0.2; \
		i=$$((i + 1)); \
	done; \
	printf "$(RED)Timed out waiting for health$(RESET) — see $(LOG_FILE)\n"; \
	exit 1

stop: ## Stop background server (via PID file)
	@if [ -f "$(PID_FILE)" ]; then \
		PID=$$(cat "$(PID_FILE)"); \
		if kill -0 "$$PID" 2>/dev/null; then \
			kill "$$PID" 2>/dev/null || true; \
			i=0; \
			while [ $$i -lt 25 ] && kill -0 "$$PID" 2>/dev/null; do \
				sleep 0.2; \
				i=$$((i + 1)); \
			done; \
			if kill -0 "$$PID" 2>/dev/null; then \
				kill -9 "$$PID" 2>/dev/null || true; \
			fi; \
			printf "$(GREEN)Stopped$(RESET) pid $$PID\n"; \
		else \
			printf "$(DIM)Stale PID file (process $$PID gone)$(RESET)\n"; \
		fi; \
		rm -f "$(PID_FILE)"; \
	elif curl -sf "$(BASE_URL)/health" >/dev/null 2>&1; then \
		printf "$(YELLOW)Something is serving $(BASE_URL) but no PID file$(RESET)\n"; \
		printf "$(DIM)Stop it manually (e.g. the terminal running make dev)$(RESET)\n"; \
		exit 1; \
	else \
		printf "$(DIM)Not running$(RESET)\n"; \
	fi

restart: ## Restart background server
	@$(MAKE) --no-print-directory stop
	@$(MAKE) --no-print-directory start

status: ## Show whether Core is up (GET /health)
	@if curl -sf "$(BASE_URL)/health" >/dev/null 2>&1; then \
		printf "$(GREEN)Running$(RESET) $(BASE_URL)\n"; \
		curl -s "$(BASE_URL)/health" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  status=%s  version=%s  uptime=%.0fs' % (d.get('status'), d.get('version'), d.get('uptime_seconds') or 0))"; \
		if [ -f "$(PID_FILE)" ]; then printf "  pid %s\n" "$$(cat "$(PID_FILE)")"; fi; \
	else \
		printf "$(RED)Not running$(RESET) ($(BASE_URL))\n"; \
		exit 1; \
	fi

logs: ## Tail background server log
	@if [ ! -f "$(LOG_FILE)" ]; then \
		printf "$(RED)No log file$(RESET) at $(LOG_FILE) — start with make start first\n"; \
		exit 1; \
	fi
	tail -f "$(LOG_FILE)"

# ── Menu Bar (macOS) ──────────────────────────────────────────────────────────

##@ Menu Bar (macOS)

menubar: _deckhand-dir ## Build, start background service, and launch macOS Menu Bar app
	@if [ ! -f .deckhand/DeckhandMenu ] || [ src/mac/DeckhandMenu.swift -nt .deckhand/DeckhandMenu ]; then \
		printf "$(DIM)Compiling DeckhandMenu.swift …$(RESET)\n"; \
		/usr/bin/swiftc -O src/mac/DeckhandMenu.swift -o .deckhand/DeckhandMenu; \
	fi
	@$(MAKE) --no-print-directory start
	@if pgrep -f ".deckhand/DeckhandMenu" >/dev/null 2>&1; then \
		printf "$(YELLOW)DeckhandMenu is already running$(RESET)\n"; \
	else \
		nohup .deckhand/DeckhandMenu >/dev/null 2>&1 & \
		printf "$(GREEN)Deckhand Menu Bar app started$(RESET) (icon in top right next to clock)\n"; \
	fi

install-menubar: _deckhand-dir ## Install Deckhand.app into ~/Applications for Login Items
	@printf "$(DIM)Compiling DeckhandMenu.swift …$(RESET)\n"
	@/usr/bin/swiftc -O src/mac/DeckhandMenu.swift -o .deckhand/DeckhandMenu
	@mkdir -p "$(HOME)/Applications/Deckhand.app/Contents/MacOS"
	@cp .deckhand/DeckhandMenu "$(HOME)/Applications/Deckhand.app/Contents/MacOS/DeckhandMenu"
	@printf '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n\t<key>CFBundleExecutable</key>\n\t<string>DeckhandMenu</string>\n\t<key>CFBundleIdentifier</key>\n\t<string>com.deckhand.menubar</string>\n\t<key>CFBundleName</key>\n\t<string>Deckhand</string>\n\t<key>CFBundlePackageType</key>\n\t<string>APPL</string>\n\t<key>CFBundleShortVersionString</key>\n\t<string>0.4.1</string>\n\t<key>LSUIElement</key>\n\t<true/>\n</dict>\n</plist>\n' > "$(HOME)/Applications/Deckhand.app/Contents/Info.plist"
	@printf "$(GREEN)Installed$(RESET) to $(HOME)/Applications/Deckhand.app\n"
	@printf "$(DIM)You can add it to System Settings → General → Login Items to start on login.$(RESET)\n"

# ── Catalog / CLI ─────────────────────────────────────────────────────────────

##@ Catalog / CLI

catalog-sync: ## Sync [catalog.state_keys] (live if Core is up)
	@if curl -sf "$(BASE_URL)/health" >/dev/null 2>&1; then \
		uv run deckhand catalog sync; \
	else \
		printf "$(YELLOW)Core not running — syncing curated seeds only (--no-live)$(RESET)\n"; \
		uv run deckhand catalog sync --no-live; \
	fi

cli: ## Run the deckhand CLI (pass ARGS="..." for arguments)
	uv run --extra test python -m deckhand $(ARGS)

# ── Quality ───────────────────────────────────────────────────────────────────

##@ Quality

test: ## Run test suite
	uv run --extra test pytest tests/ -v --asyncio-mode=auto
	uv run --extra test pytest opendeck-plugin/tests/ -v --asyncio-mode=auto --rootdir=opendeck-plugin

lint: ## Run ruff linter
	uvx ruff check $(SRC_DIRS)
	uvx ruff format --check $(SRC_DIRS)

format: ## Auto-format code with ruff
	uvx ruff format $(SRC_DIRS)
	uvx ruff check --fix $(SRC_DIRS)

check: ## Full quality gate: lint + tests
	@$(MAKE) --no-print-directory lint
	@$(MAKE) --no-print-directory test

# ── OpenDeck ──────────────────────────────────────────────────────────────────

##@ OpenDeck

opendeck-plugin-install: ## Copy OpenDeck plugin into OpenDeck's Plugins folder
	@mkdir -p "$(OPENDECK_PLUGINS)"
	cp -R "$(OPENDECK_PLUGIN_SRC)" "$(OPENDECK_PLUGINS)/"
	@printf "$(GREEN)Installed$(RESET) to $(OPENDECK_PLUGINS)/com.deckhand.plugin.sdPlugin\n"
	@if [ -f "$(OPENDECK_PLUGINS)/com.deckhand.plugin.sdPlugin/deckhand.env" ]; then \
		printf "$(YELLOW)Note:$(RESET) leftover deckhand.env overrides DECKHAND_URL (reinstall does not replace it).\n"; \
		printf "$(DIM)Prefer [client] in ~/.config/deckhand/config.toml, or update the URL in deckhand.env.$(RESET)\n"; \
	fi
	@printf "$(DIM)Restart OpenDeck (fully quit + reopen) so Property Inspectors reload.$(RESET)\n"

# ── Workflow (CodeCannon) ─────────────────────────────────────────────────────

##@ Workflow

abandon: ## Discard changes, delete feature branch, return to main
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$BRANCH" = "$(BRANCH_PROD)" ]; then \
		printf "$(RED)error:$(RESET) already on $(BRANCH_PROD), nothing to abandon\n" >&2; exit 1; \
	fi; \
	git checkout $(BRANCH_PROD) && \
	git pull --ff-only && \
	git branch -D "$$BRANCH" && \
	printf "$(GREEN)Deleted branch$(RESET) $$BRANCH, now on $(BRANCH_PROD)\n"

merge: ## Merge current branch's PR into main
	gh pr merge --merge --delete-branch

deploy-preview: ## Deploy to preview (not configured)
	@printf "$(DIM)No preview deployment configured — Deckhand is a local-first service.$(RESET)\n"

deploy-prod: ## Build release artifacts
	@$(MAKE) --no-print-directory check
	uv build
	@printf "\n$(GREEN)Built artifacts in dist/:$(RESET)\n"
	@ls dist/
	@printf "\n$(DIM)Publish with: uv publish$(RESET)\n"

# ── Versioning ────────────────────────────────────────────────────────────────

##@ Versioning

version: ## Print current version
	@python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

bump-patch: ## Bump patch version (0.1.0 → 0.1.1)
	@V=$$(python3 -c "\
		import tomllib; \
		v = tomllib.load(open('pyproject.toml','rb'))['project']['version'].split('.'); \
		v[2] = str(int(v[2])+1); \
		print('.'.join(v))"); \
	$(MAKE) --no-print-directory set-version V=$$V

bump-minor: ## Bump minor version (0.1.0 → 0.2.0)
	@V=$$(python3 -c "\
		import tomllib; \
		v = tomllib.load(open('pyproject.toml','rb'))['project']['version'].split('.'); \
		v[1] = str(int(v[1])+1); v[2] = '0'; \
		print('.'.join(v))"); \
	$(MAKE) --no-print-directory set-version V=$$V

bump-major: ## Bump major version (0.1.0 → 1.0.0)
	@V=$$(python3 -c "\
		import tomllib; \
		v = tomllib.load(open('pyproject.toml','rb'))['project']['version'].split('.'); \
		v[0] = str(int(v[0])+1); v[1] = '0'; v[2] = '0'; \
		print('.'.join(v))"); \
	$(MAKE) --no-print-directory set-version V=$$V

set-version: ## Set version to V=x.y.z
	@if [ -z "$(V)" ]; then printf "$(RED)error:$(RESET) usage: make set-version V=x.y.z\n" >&2; exit 1; fi
	@echo "$(V)" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$$' || { printf "$(RED)error:$(RESET) invalid version '$(V)'\n" >&2; exit 1; }
	@python3 -c "\
		import re, pathlib; \
		p = pathlib.Path('pyproject.toml'); \
		p.write_text(re.sub(r'version = \".*?\"', 'version = \"$(V)\"', p.read_text(), count=1))"
	@printf "$(GREEN)Version set to$(RESET) $(V)\n"

# ── Cleanup ───────────────────────────────────────────────────────────────────

##@ Cleanup

clean: ## Remove build artifacts, caches, and server PID
	rm -rf dist/ build/ *.egg-info
	rm -f $(PID_FILE)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
