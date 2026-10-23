"""Opt-in lifecycle smoke: python -m pytest tests/startup -q -s.

Uses its own disposable persistent profile, not WM_TEST_MYSQL_URL or the user's local data.
"""

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pymysql
import pytest

from scripts.local_dev import ROOT, free_port
from scripts.with_test_mysql import child


def wait_http(process, origin):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        assert process.poll() is None, 'launcher exited; inspect private smoke log'
        try:
            with urlopen(origin + '/health/ready', timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(0.1)
    pytest.fail('local server did not become ready within 60 seconds')


def snapshot(directory, settings):
    with pymysql.connect(
        unix_socket=str(directory / 'mysql.sock'),
        user='root',
        password=settings['root_password'],
        database='wordmachine_local',
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT @@port, @@bind_address')
            port, address = cursor.fetchone()
            assert address == '127.0.0.1'
            cursor.execute('SHOW TABLES')
            tables = [row[0] for row in cursor.fetchall()]
            result = {}
            for table in tables:
                assert re.fullmatch('[a-z_]+', table)
                cursor.execute(f'SHOW CREATE TABLE `{table}`')
                structure = cursor.fetchone()[1]
                cursor.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name = 'PRIMARY'")
                columns = [row[4] for row in cursor.fetchall()]
                assert columns and all(re.fullmatch('[a-z_]+', column) for column in columns)
                order = ', '.join(f'`{column}`' for column in columns)
                cursor.execute(f'SELECT * FROM `{table}` ORDER BY {order}')
                result[table] = (structure, cursor.fetchall())
            assert result['alembic_version'][1] == (('0011_dictionary_multipliers',),)
            assert len(result['user'][1]) == 1
    # Verify the actual runtime identity cannot execute DDL.
    with pymysql.connect(
        host='127.0.0.1',
        port=port,
        user='wm_local',
        password=settings['db_password'],
        database='wordmachine_local',
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(pymysql.OperationalError) as denied:
                cursor.execute('CREATE TABLE forbidden_probe (id INT)')
            assert denied.value.args[0] in (1044, 1142)
    return result


def test_real_local_launcher_preserves_data_sessions_receipts_and_stops_owned_servers(tmp_path):
    base = Path(
        os.environ.get(
            'WM_TEST_MYSQL_BASEDIR', str(Path.home() / '.local/share/wordmachine-test/mysql/usr')
        )
    ).resolve()
    assert (base / 'sbin/mysqld').is_file() or (base / 'bin/mysqld').is_file(), (
        'Install the private MySQL binaries first; see docs/TEST_ENVIRONMENT.md'
    )
    environment = {key: value for key, value in os.environ.items() if not key.startswith('WM_')}
    # Prove the shell launcher does not depend on the coding harness's PATH or DB variables.
    environment.update(
        PATH='/usr/bin:/bin', WM_DB_HOST='business.invalid', WM_ENV='production', WM_PORT='invalid'
    )
    with tempfile.TemporaryDirectory(prefix='wm-local-', dir='/tmp') as temporary:
        home = Path(temporary)
        environment['XDG_DATA_HOME'] = temporary
        with (tmp_path / 'smoke.log').open('w') as log:
            command = [str(ROOT / 'start.sh')]
            with child(
                [*command, '--init', '--mysql-basedir', str(base)], env=environment, output=log
            ) as process:
                result = process.wait(timeout=150)
                if result:
                    for error in home.rglob('launcher-error-*.log'):
                        (tmp_path / error.name).write_bytes(error.read_bytes())
                assert result == 0, f'initialization failed; inspect {tmp_path}'
            directories = list((home / 'wordmachine-local').iterdir())
            assert len(directories) == 1
            directory = directories[0]
            settings_bytes = (directory / 'settings.json').read_bytes()
            settings = json.loads(settings_bytes)
            login = (directory / 'initial-login.txt').read_bytes()
            assert not (directory / 'mysql.sock').exists()
            # Explicit initialization also refuses to overwrite an already initialized instance.
            refused = subprocess.run(
                [*command, '--init'],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            assert refused.returncode == 1 and '拒绝覆盖' in refused.stderr.decode()
            assert (directory / 'settings.json').read_bytes() == settings_bytes
            origin = f'http://127.0.0.1:{free_port()}'
            before = None
            node = str(Path.home() / '.local/share/wordmachine-tools/node/bin/node')
            if not Path(node).is_file():
                node = 'node'
                environment['PATH'] = os.environ['PATH']
            for phase, signum in [('first', signal.SIGTERM), ('second', signal.SIGINT)]:
                with child(
                    [*command, '--port', origin.rsplit(':', 1)[1]], env=environment, output=log
                ) as process:
                    wait_http(process, origin)
                    shown = subprocess.run(
                        [*command, '--show-login'], env=environment, capture_output=True, timeout=10
                    )
                    assert shown.returncode == 0 and shown.stdout == login
                    duplicate = subprocess.run(
                        command, env=environment, capture_output=True, timeout=10
                    )
                    assert duplicate.returncode == 1 and '正在运行' in duplicate.stderr.decode()
                    with child(
                        [
                            node,
                            str(ROOT / 'tests/startup/browser.mjs'),
                            origin,
                            temporary,
                            str(directory / 'initial-login.txt'),
                            phase,
                        ],
                        env=environment,
                        output=log,
                    ) as browser:
                        assert browser.wait(timeout=75) == 0, (
                            f'browser smoke failed; inspect {tmp_path / "smoke.log"}'
                        )
                    current = snapshot(directory, settings)
                    if before is None:
                        before = current
                        assert (
                            len(current['dict'][1])
                            == len(current['word'][1])
                            == len(current['game'][1])
                            == len(current['game_request'][1])
                            == 1
                        )
                    else:
                        assert current == before, (
                            'restart/read/replay changed stored facts or schema'
                        )
                    process.send_signal(signum)
                    assert process.wait(timeout=45) in (0, 130, 143)
                assert not (directory / 'mysql.sock').exists()
                assert not (directory / 'mysql.pid').exists()
                assert (directory / 'settings.json').read_bytes() == settings_bytes
                assert (directory / 'initial-login.txt').read_bytes() == login
            print(
                'Local startup smoke passed: fresh migration, CSS, HTTP/WS, least privilege, two starts / one restart, persistent facts, original Cookie/receipt, SIGTERM and Ctrl+C cleanup.'
            )
