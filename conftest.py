"""
Root-level pytest configuration.
"""

__license__ = "GNU GPLv3"

from src import logger_adapter

# Every tests/test_*.py sets this at import time so LoggerAdapter.alert()
# doesn't write real ERROR-level entries to the production log file while
# unit tests deliberately trigger it. `python -m pytest . --doctest-modules`
# (see .github/workflows/ci_pipeline.yml) never imports any of those files -
# it only imports src/ modules directly for their embedded doctests - so
# without this, doctests like logger_adapter.get_logger()'s own
# `>>> raise logger.alert(TypeError, "Test")` write real "[TypeError] Test"
# entries to whichever log file TOPOLOGYBUILDER_LOG_FILE (or the default
# logs/log.txt) points at. Harmless in CI's ephemeral runner, but pollutes a
# real, persistent log file on a local checkout - confirmed live 2026-08-10
# via the `logs` CLI command surfacing stale entries from an earlier local
# doctest run.
logger_adapter.LoggerAdapter.is_test_run = True
