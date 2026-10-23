import os
import signal
import sys
from pathlib import Path

import pytest

from scripts import with_test_mysql as runner


def test_runner_does_not_inherit_business_database_configuration(monkeypatch):
    monkeypatch.setenv('WM_DB_HOST', 'business.invalid')
    monkeypatch.setenv('WM_DB_PASSWORD', 'must-not-be-used')
    monkeypatch.setenv('WM_DB_EXTRA', 'future-option')
    monkeypatch.setenv('WM_TEST_MYSQL_URL', 'mysql://business.invalid')
    monkeypatch.setenv('WM_ENV', 'production')
    environment = runner.test_environment(12345, 'temporary-test-password')
    assert (
        environment['WM_TEST_MYSQL_URL']
        == 'mysql+pymysql://wm_test:temporary-test-password@127.0.0.1:12345'
    )
    assert environment['WM_DB_HOST'] == '127.0.0.1' and environment['WM_DB_PORT'] == '1'
    assert environment['WM_DB_PASSWORD'] == '' and 'WM_DB_EXTRA' not in environment
    assert environment['WM_ENV'] == 'testing' and environment['WM_DEBUG'] == 'false'
    assert os.environ['WM_DB_HOST'] == 'business.invalid'


def test_owned_child_is_stopped_and_reaped_even_after_an_error():
    with pytest.raises(RuntimeError, match='test failure'):
        with runner.child(
            [sys.executable, '-c', 'import time; time.sleep(60)'], env=os.environ.copy()
        ) as process:
            assert process.poll() is None
            raise RuntimeError('test failure')
    assert process.returncode == -signal.SIGTERM


def test_runner_refuses_root_before_starting_a_server(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['with_test_mysql.py', '--', 'unused-command'])
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(runner, 'run', lambda *args: pytest.fail('server must not start'))
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


def test_startup_failure_removes_only_its_temporary_directory(monkeypatch):
    directories = []

    def fail(_command, _base, directory):
        directories.append(directory)
        assert directory.stat().st_mode & 0o777 == 0o700
        (directory / 'mysql.log').write_text('startup failed')
        raise RuntimeError('injected startup failure')

    monkeypatch.setattr(sys, 'argv', ['with_test_mysql.py', '--', 'unused-command'])
    monkeypatch.setattr(os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(signal, 'signal', lambda *args: None)
    monkeypatch.setattr(runner, 'run', fail)
    assert runner.main() == 1
    assert len(directories) == 1 and not Path(directories[0]).exists()
