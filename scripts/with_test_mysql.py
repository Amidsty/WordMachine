"""Run a command against a disposable, user-owned MySQL instance (never a business DB).

Usage: .venv/bin/python scripts/with_test_mysql.py -- <command> [arguments...]
Requires separately installed MySQL binaries/resources. No sudo or system service.
The process helpers are also used by the persistent local-development launcher.
"""

import argparse
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import pymysql


def stop(process):
    """Only signal the process group created by this runner, never a PID from a file."""
    if process.poll() is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


@contextmanager
def child(command, *, env, output=None):
    process = subprocess.Popen(
        command,
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT if output else None,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        stop(process)


def connect_when_ready(process, socket_path, password):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Temporary MySQL exited before becoming ready')
        try:
            return pymysql.connect(
                unix_socket=str(socket_path),
                user='root',
                password=password,
                autocommit=True,
                connect_timeout=2,
                read_timeout=5,
                write_timeout=5,
            )
        except pymysql.OperationalError:
            time.sleep(0.1)
    raise RuntimeError('Temporary MySQL startup timed out')


def test_environment(port, password):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('WM_DB_')}
    environment.update(
        WM_TEST_MYSQL_URL=f'mysql+pymysql://wm_test:{password}@127.0.0.1:{port}',
        PYTHONDONTWRITEBYTECODE='1',
        WM_ENV='testing',
        WM_DEBUG='false',
        # Unconfigured application code must fail, never inherit a business database.
        # Only the pytest fixtures consume WM_TEST_MYSQL_URL and choose fresh databases.
        WM_DB_HOST='127.0.0.1',
        WM_DB_PORT='1',
        WM_DB_NAME='wm_test_unconfigured',
        WM_DB_USER='wm_test',
        WM_DB_PASSWORD='',
    )
    return environment


def server_options(base, directory):
    """Shared private-server options; does not create, start or migrate a database."""
    binary = next(
        (base / name for name in ('sbin/mysqld', 'bin/mysqld') if (base / name).is_file()), None
    )
    if binary is None:
        raise RuntimeError(
            f'mysqld not found under {base}; provide an installed MySQL 8.0.16+ binary/resource directory'
        )
    messages = next(
        (
            base / name
            for name in ('share/mysql', 'share/mysql-8.0', 'share')
            if (base / name / 'english/errmsg.sys').is_file()
        ),
        None,
    )
    if messages is None:
        raise RuntimeError(f'MySQL message files not found under {base}')
    server_env = os.environ.copy()
    library_paths = [
        str(path) for path in (base / 'lib/x86_64-linux-gnu', base / 'lib') if path.is_dir()
    ]
    if server_env.get('LD_LIBRARY_PATH'):
        library_paths.append(server_env['LD_LIBRARY_PATH'])
    server_env['LD_LIBRARY_PATH'] = os.pathsep.join(library_paths)
    args = [
        str(binary),
        '--no-defaults',
        f'--basedir={base}',
        f'--datadir={directory / "data"}',
        f'--lc-messages-dir={messages}',
        f'--socket={directory / "mysql.sock"}',
        f'--pid-file={directory / "mysql.pid"}',
        f'--secure-file-priv={directory / "files"}',
        '--mysqlx=0',
        '--skip-log-bin',
        '--skip-name-resolve',
        '--local-infile=0',
        '--innodb-buffer-pool-size=64M',
        '--performance-schema=OFF',
        '--default-time-zone=+00:00',
    ]
    return args, server_env


def run(command, base, directory):
    args, server_env = server_options(base, directory)
    (directory / 'data').mkdir()
    (directory / 'files').mkdir()
    socket_path = directory / 'mysql.sock'
    root_password, test_password = secrets.token_hex(32), secrets.token_hex(32)
    with (directory / 'mysql.log').open('a') as log:
        with child([*args, '--initialize-insecure'], env=server_env, output=log) as process:
            if process.wait(timeout=90) != 0:
                raise RuntimeError('Temporary MySQL initialization failed')
        # Empty root password is confined to a private Unix socket; TCP is disabled.
        with child([*args, '--skip-networking'], env=server_env, output=log) as process:
            with connect_when_ready(process, socket_path, '') as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (root_password,)
                    )
                    cursor.execute(
                        "CREATE USER 'wm_test'@'127.0.0.1' IDENTIFIED BY %s", (test_password,)
                    )
                    cursor.execute(
                        r"GRANT ALL PRIVILEGES ON `wm\_test\_%`.* TO 'wm_test'@'127.0.0.1'"
                    )
        # A bind race causes startup failure, not attachment to another server.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        with child(
            [*args, '--bind-address=127.0.0.1', f'--port={port}'], env=server_env, output=log
        ) as process:
            with connect_when_ready(process, socket_path, root_password) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT VERSION()')
                    version = cursor.fetchone()[0]
            environment = test_environment(port, test_password)
            print(
                f'Temporary MySQL {version} on 127.0.0.1:{port}; grants restricted to wm_test_*',
                flush=True,
            )
            with child(command, env=environment) as test:
                return test.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    command = options.command
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        parser.error('provide a command after --')
    if os.geteuid() == 0:
        parser.error('run as an ordinary user, not root')
    base = (
        Path(
            os.environ.get(
                'WM_TEST_MYSQL_BASEDIR',
                str(Path.home() / '.local/share/wordmachine-test/mysql/usr'),
            )
        )
        .expanduser()
        .resolve()
    )

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    # A fresh 0700 directory owns all data, logs and socket paths. Never reuse a datadir.
    with tempfile.TemporaryDirectory(prefix='wm-mysql-', dir='/tmp') as temporary:
        directory = Path(temporary)
        try:
            return run(command, base, directory)
        except KeyboardInterrupt:
            return 130
        except Exception as error:
            print(f'Test MySQL failed: {error}', file=sys.stderr)
            log = directory / 'mysql.log'
            if log.exists():
                print(
                    '\n'.join(log.read_text(errors='replace').splitlines()[-40:]), file=sys.stderr
                )
            return 1


if __name__ == '__main__':
    sys.exit(main())
