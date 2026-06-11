.PHONY: help install dev cli test lint format check clean abandon merge deploy-preview deploy-prod version bump-patch bump-minor bump-major set-version
.DEFAULT_GOAL := help

BRANCH_PROD := main
SRC_DIRS    := src/ tests/ opendeck-plugin/

# ── Helpers ───────────────────────────────────────────────────────────────────

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Development ───────────────────────────────────────────────────────────────

install: ## Install all dependencies via uv
	uv sync --all-extras

dev: ## Start dev server with hot reload
	uv run python -m uvicorn deckhand.main:app --app-dir src --reload --host 127.0.0.1 --port 8000

cli: ## Run the deckhand CLI (pass ARGS="..." for arguments)
	uv run --extra test python -m deckhand $(ARGS)

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
	@$(MAKE) lint
	@$(MAKE) test

clean: ## Remove build artifacts and caches
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

# ── Workflow (CodeCannon) ─────────────────────────────────────────────────────

abandon: ## Discard changes, delete feature branch, return to main
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$BRANCH" = "$(BRANCH_PROD)" ]; then \
		echo "error: already on $(BRANCH_PROD), nothing to abandon" >&2; exit 1; \
	fi; \
	git checkout $(BRANCH_PROD) && \
	git pull --ff-only && \
	git branch -D "$$BRANCH" && \
	echo "Deleted branch $$BRANCH, now on $(BRANCH_PROD)"

merge: ## Merge current branch's PR into main
	gh pr merge --merge --delete-branch

deploy-preview: ## Deploy to preview (not configured)
	@echo "No preview deployment configured — Deckhand is a local-first service."

deploy-prod: ## Build release artifacts
	@$(MAKE) check
	uv build
	@echo ""
	@echo "Built artifacts in dist/:"
	@ls dist/
	@echo ""
	@echo "Publish with: uv publish"

# ── Versioning ────────────────────────────────────────────────────────────────

version: ## Print current version
	@python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

bump-patch: ## Bump patch version (0.1.0 → 0.1.1)
	@V=$$(python3 -c "\
		import tomllib; \
		v = tomllib.load(open('pyproject.toml','rb'))['project']['version'].split('.'); \
		v[2] = str(int(v[2])+1); \
		print('.'.join(v))"); \
	$(MAKE) set-version V=$$V

bump-minor: ## Bump minor version (0.1.0 → 0.2.0)
	@V=$$(python3 -c "\
		import tomllib; \
		v = tomllib.load(open('pyproject.toml','rb'))['project']['version'].split('.'); \
		v[1] = str(int(v[1])+1); v[2] = '0'; \
		print('.'.join(v))"); \
	$(MAKE) set-version V=$$V

bump-major: ## Bump major version (0.1.0 → 1.0.0)
	@V=$$(python3 -c "\
		import tomllib; \
		v = tomllib.load(open('pyproject.toml','rb'))['project']['version'].split('.'); \
		v[0] = str(int(v[0])+1); v[1] = '0'; v[2] = '0'; \
		print('.'.join(v))"); \
	$(MAKE) set-version V=$$V

set-version: ## Set version to V=x.y.z
	@if [ -z "$(V)" ]; then echo "error: usage: make set-version V=x.y.z" >&2; exit 1; fi
	@echo "$(V)" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$$' || { echo "error: invalid version '$(V)'" >&2; exit 1; }
	@python3 -c "\
		import re, pathlib; \
		p = pathlib.Path('pyproject.toml'); \
		p.write_text(re.sub(r'version = \".*?\"', 'version = \"$(V)\"', p.read_text(), count=1))"
	@echo "Version set to $(V)"
