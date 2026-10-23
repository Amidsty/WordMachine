"""Shared real-browser harness: one migrated synthetic database per pytest test."""

import os
import signal
import subprocess
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from tests.integration.conftest import legacy_database, migrate_database, mysql_app
from tests.integration.test_game_mysql import execute

# Pytest discovers these imported fixtures by name; they are intentional re-exports.
__all__ = ['legacy_database', 'migrate_database', 'mysql_app']


@pytest.fixture
def run_browser(mysql_app):
    def run(spec):
        # Do not let the inherited active legacy game redirect unrelated UI flows.
        execute(mysql_app, 'UPDATE game SET status = 2 WHERE id = 1')
        server = make_server('127.0.0.1', 0, mysql_app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith('WM_DB_') and key != 'WM_TEST_MYSQL_URL'
        }
        env['WM_BROWSER_MYSQL_ORIGIN'] = f'http://127.0.0.1:{server.server_port}'
        process = None
        previous_term = signal.getsignal(signal.SIGTERM)

        def interrupted(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            raise KeyboardInterrupt('Browser test interrupted')

        signal.signal(signal.SIGTERM, interrupted)
        try:
            process = subprocess.Popen(
                [
                    'node_modules/.bin/playwright',
                    'test',
                    '--config',
                    'playwright.mysql.config.ts',
                    spec,
                    '--output',
                    f'test-results/mysql/{Path(spec).stem}',
                ],
                cwd=Path(__file__).resolve().parents[2] / 'frontend',
                env=env,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            print(f'Real browser harness started: {spec} on private loopback server', flush=True)
            output, _ = process.communicate(timeout=210)
            print(output)
            assert process.returncode == 0, output
        finally:
            # Reap our separate browser group even on failure, timeout or SIGTERM.
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            signal.signal(signal.SIGTERM, previous_term)

    return run
