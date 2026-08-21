.PHONY: bootstrap format format-check lint typecheck unit integration contract bdd test smoke build

UV ?= uv
export UV_LINK_MODE := copy

bootstrap:
	./scripts/ensure-venv.sh

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

format-check:
	$(UV) run ruff format --check .

lint:
	$(UV) run ruff check .

typecheck:
	$(UV) run mypy src

unit:
	$(UV) run pytest -q tests/unit

integration:
	@echo "not applicable: scaffold has no external integration yet"

contract:
	$(UV) run pytest -q tests/contract

bdd:
	$(UV) run pytest -q tests/bdd

test: format-check lint typecheck unit contract bdd

smoke:
	$(UV) run job-search-hh capabilities
	$(UV) run job-search-hh vacancies sync --help >/dev/null
	$(UV) run job-search-hh applications sync --help >/dev/null
	$(UV) run job-search-hh metrics sync --help >/dev/null
	$(UV) run job-search-hh apply dry-run --help >/dev/null
	$(UV) run job-search-hh apply limited --help >/dev/null

build:
	docker build -t job-search-hh:dev .

