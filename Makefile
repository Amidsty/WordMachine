PYTHON ?= .venv/bin/python
PYTHON_SOURCES := app.py wm_app migrations scripts tests
PERF_ARGS ?= --list-perf-size=medium --list-perf-runs=3

.PHONY: check check-python check-python-static format-python check-frontend build-frontend test-browser test-browser-mysql test-browser-live test-mysql check-with-mysql benchmark-mysql benchmark-live test-startup

check: check-python check-frontend

# These targets always use a new local instance, never an inherited database URL.
check-with-mysql:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/with_test_mysql.py -- $(MAKE) check

test-mysql:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/with_test_mysql.py -- $(PYTHON) -m pytest -m mysql -q -p no:cacheprovider

# Opt-in synthetic service benchmark, not a latency gate or a live data profiler.
benchmark-mysql:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/with_test_mysql.py -- $(PYTHON) -m pytest tests/performance -q -s -p no:cacheprovider $(PERF_ARGS)

benchmark-live:
	@test -n "$$WM_TEST_MYSQL_URL" || { echo 'WM_TEST_MYSQL_URL is required; use make benchmark-mysql' >&2; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/performance -q -s -p no:cacheprovider $(PERF_ARGS)

# Check-only by default: neither local checks nor CI rewrite source files.
check-python-static:
	$(PYTHON) -m ruff check --config ruff.toml --no-fix $(PYTHON_SOURCES)
	$(PYTHON) -m ruff format --config ruff.toml --check $(PYTHON_SOURCES)

# Formatting is explicit; lint autofixes require separate, reviewed commands.
format-python:
	$(PYTHON) -m ruff format --config ruff.toml $(PYTHON_SOURCES)

check-python: check-python-static
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider

check-frontend:
	npm --prefix frontend run check

build-frontend:
	npm --prefix frontend run build

test-browser:
	npm --prefix frontend run test:browser

# Real Chromium/Socket.IO tests; by default create a fresh private MySQL instance.
test-browser-mysql: build-frontend
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/with_test_mysql.py -- $(PYTHON) -m pytest tests/browser -q -s -p no:cacheprovider

# Opt-in real local-launcher lifecycle: creates and removes its OWN synthetic profile.
test-startup:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/startup -q -s -p no:cacheprovider

# CI may use its dedicated MySQL service. This target requires WM_TEST_MYSQL_URL.
test-browser-live:
	@test -n "$$WM_TEST_MYSQL_URL" || { echo 'WM_TEST_MYSQL_URL is required; use make test-browser-mysql' >&2; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/browser -q -s -p no:cacheprovider
