# shelfr Makefile
# Common development tasks

.PHONY: help version bump-patch bump-minor bump-major release-patch release-minor release-major
.PHONY: test lint fmt check install dev clean

# Default target
help:
	@echo "shelfr development commands:"
	@echo ""
	@echo "  Version Management:"
	@echo "    make version       Show current version"
	@echo "    make bump-patch    Bump patch version (0.1.0 -> 0.1.1)"
	@echo "    make bump-minor    Bump minor version (0.1.0 -> 0.2.0)"
	@echo "    make bump-major    Bump major version (0.1.0 -> 1.0.0)"
	@echo "    make release-patch Full release: bump patch + commit + tag"
	@echo "    make release-minor Full release: bump minor + commit + tag"
	@echo "    make release-major Full release: bump major + commit + tag"
	@echo ""
	@echo "  Development:"
	@echo "    make test          Run tests with pytest"
	@echo "    make lint          Run pre-commit linters"
	@echo "    make fmt           Format code with ruff"
	@echo "    make check         Run pre-commit on all files"
	@echo ""
	@echo "  Installation:"
	@echo "    make install       Install package"
	@echo "    make dev           Install in editable mode with dev deps"
	@echo "    make clean         Remove build artifacts"

# -------------------------------------------------------------------
# Version Management
# -------------------------------------------------------------------

version:
	@python tools/version.py

bump-patch:
	@python tools/version.py patch

bump-minor:
	@python tools/version.py minor

bump-major:
	@python tools/version.py major

# Full release workflow: bump + commit + tag
release-patch:
	@python tools/version.py patch
	@git add src/shelfr/__init__.py pyproject.toml
	@VERSION=$$(python tools/version.py | grep -oP '\d+\.\d+\.\d+'); \
	git commit -m "chore: bump version to $$VERSION"; \
	git tag "v$$VERSION"
	@echo ""
	@echo "🚀 Release ready! Run: git push origin main --tags"

release-minor:
	@python tools/version.py minor
	@git add src/shelfr/__init__.py pyproject.toml
	@VERSION=$$(python tools/version.py | grep -oP '\d+\.\d+\.\d+'); \
	git commit -m "chore: bump version to $$VERSION"; \
	git tag "v$$VERSION"
	@echo ""
	@echo "🚀 Release ready! Run: git push origin main --tags"

release-major:
	@python tools/version.py major
	@git add src/shelfr/__init__.py pyproject.toml
	@VERSION=$$(python tools/version.py | grep -oP '\d+\.\d+\.\d+'); \
	git commit -m "chore: bump version to $$VERSION"; \
	git tag "v$$VERSION"
	@echo ""
	@echo "🚀 Release ready! Run: git push origin main --tags"

# -------------------------------------------------------------------
# Development
# -------------------------------------------------------------------

test:
	pytest tests/ -v

lint:
	pre-commit run --all-files

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

check: lint

# -------------------------------------------------------------------
# Installation
# -------------------------------------------------------------------

install:
	pip install .

dev:
	pip install -e ".[dev]"

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
