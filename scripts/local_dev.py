"""Explicit initialization and simple startup of a private, persistent LOCAL development DB.

No .env loading, existing database attachment, automatic migration, reset or production serving.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine
from werkzeug.serving import WSGIRequestHandler, make_server

from scripts.with_test_mysql import child, connect_when_ready, server_options
from wm_app import create_app
from wm_app.services.admin_policy import MASTER_NAME, generate_master_password
from wm_app.services.auth import create_user

ROOT = Path(__file__).resolve().parents[1]
DATABASE = 'wordmachine_local'
DB_USER = 'wm_local'
ADMIN = MASTER_NAME


class LocalError(Exception):
    """An actionable message that does not contain credentials."""


class LocalRequestHandler(WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        # The application already logs method/path/status without queries or cookies.
        # Do not add Werkzeug's raw request target (including Engine.IO session IDs).
        return None


def state_directory():
    home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    if not home.is_absolute():
        raise LocalError('XDG_DATA_HOME 必须是绝对路径。')
    project = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    directory = home / 'wordmachine-local' / project
    if len(os.fsencode(directory / 'mysql.sock')) >= 108:
        raise LocalError('本地数据路径超出 Unix socket 限制，请设置较短的 XDG_DATA_HOME。')
    return directory


def check_private(path, *, directory=False):
    info = path.lstat()
    expected = 0o700 if directory else 0o600
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not kind(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != expected
    ):
        raise LocalError(f'拒绝使用非本人所有、链接或权限不符的路径：{path}（应为 {expected:o}）')


@contextmanager
def locked(directory, *, initialize=False):
    if initialize:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not directory.exists():
        raise LocalError('尚未初始化本地开发库，请先运行 ./setup.sh --init-local')
    check_private(directory, directory=True)
    descriptor = os.open(directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as lock:
        check_private(directory / 'lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LocalError('本地实例正在运行或初始化；请先在原终端 Ctrl+C 停止。') from error
        yield


def write_private(path, text):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())


def save_settings(directory, settings):
    temporary = directory / 'settings.new'
    write_private(temporary, json.dumps(settings, indent=2) + '\n')
    os.replace(temporary, directory / 'settings.json')


def load_settings(directory):
    path = directory / 'settings.json'
    if not path.is_file():
        raise LocalError('本地配置缺失；不自动接管或修复已有目录，请先核对数据和日志。')
    check_private(path)
    settings = json.loads(path.read_text())
    if (
        not isinstance(settings, dict)
        or type(settings.get('format')) is not int
        or settings.get('format') != 1
        or settings.get('project') != str(ROOT)
        or settings.get('ready') is not True
        or not isinstance(settings.get('mysql_base'), str)
        or not Path(settings['mysql_base']).is_absolute()
        or any(
            not isinstance(settings.get(key), str)
            or not re.fullmatch('[0-9a-f]{64}', settings[key])
            for key in ('root_password', 'db_password', 'secret_key')
        )
    ):
        raise LocalError('本地配置未完成或不匹配；数据保留，不自动初始化、迁移或修复。')
    if not (directory / 'data').is_dir() or (directory / 'data').is_symlink():
        raise LocalError('本地 MySQL 数据目录缺失或是链接；拒绝重新生成。')
    return settings


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


@contextmanager
def mysql_server(directory, settings, *, bootstrap=False):
    args, environment = server_options(Path(settings['mysql_base']), directory)
    port = None if bootstrap else free_port()
    network = ['--skip-networking'] if bootstrap else ['--bind-address=127.0.0.1', f'--port={port}']
    # Logs and sockets are within the checked private directory; no password in argv.
    log_path = directory / 'mysql.log'
    if log_path.exists():
        check_private(log_path)
    descriptor = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as log:
        with child([*args, '--upgrade=NONE', *network], env=environment, output=log) as process:
            password = '' if bootstrap else settings['root_password']
            with connect_when_ready(process, directory / 'mysql.sock', password):
                pass
            yield port, process


def application(settings, port):
    # Cookie scope ignores ports. Separate this private profile from other localhost apps.
    cookie_id = hashlib.sha256(settings['secret_key'].encode()).hexdigest()[:16]
    return create_app(
        {
            'ENVIRONMENT': 'development',
            'DEBUG': False,
            'SECRET_KEY': settings['secret_key'],
            'DB_HOST': '127.0.0.1',
            'DB_PORT': port,
            'DB_NAME': DATABASE,
            'DB_USER': DB_USER,
            'DB_PASSWORD': settings['db_password'],
            'AUTH_COOKIE_NAME': f'wm_local_{cookie_id}_session',
            'CSRF_COOKIE_NAME': f'wm_local_{cookie_id}_csrf',
        }
    )


def ready(app):
    # Read only. The application's own readiness requirement is the single authority.
    if app.test_client().get('/health/ready').status_code != 200:
        raise LocalError('数据库未就绪或迁移版本不匹配；未自动执行迁移，请先备份并审查。')


def initialize(directory, base):
    if any(
        (directory / name).exists() or (directory / name).is_symlink()
        for name in ('data', 'settings.json', 'settings.new', 'initial-login.txt')
    ):
        raise LocalError(
            '已有本地数据或初始化痕迹，拒绝覆盖/重跑；请使用 ./start.sh 或先人工核对。'
        )
    args, environment = server_options(base, directory)
    settings = {
        'format': 1,
        'project': str(ROOT),
        'ready': False,
        'mysql_base': str(base),
        'root_password': secrets.token_hex(32),
        'db_password': secrets.token_hex(32),
        'secret_key': secrets.token_hex(32),
    }
    save_settings(directory, settings)
    (directory / 'data').mkdir(mode=0o700)
    (directory / 'files').mkdir(mode=0o700)
    write_private(directory / 'mysql.log', '')
    with (directory / 'mysql.log').open('a') as log:
        with child([*args, '--initialize-insecure'], env=environment, output=log) as process:
            if process.wait(timeout=90) != 0:
                raise LocalError(
                    '本地 MySQL 初始化失败；目录已保留，请检查 mysql.log，不要盲目重跑。'
                )
    # Initial empty root password is never exposed over TCP.
    with mysql_server(directory, settings, bootstrap=True) as (_, process):
        with connect_when_ready(process, directory / 'mysql.sock', '') as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (settings['root_password'],)
                )
                cursor.execute(f'CREATE DATABASE `{DATABASE}` CHARACTER SET utf8mb4')
                cursor.execute(
                    "CREATE USER 'wm_local'@'127.0.0.1' IDENTIFIED BY %s",
                    (settings['db_password'],),
                )
                cursor.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{DATABASE}`.* TO 'wm_local'@'127.0.0.1'"
                )
    with mysql_server(directory, settings) as (port, _):
        url = URL.create(
            'mysql+pymysql',
            username='root',
            password=settings['root_password'],
            database=DATABASE,
            query={'unix_socket': str(directory / 'mysql.sock'), 'charset': 'utf8mb4'},
        )
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                config = Config(str(ROOT / 'alembic.ini'))
                config.set_main_option('script_location', str(ROOT / 'migrations'))
                config.attributes['connection'] = connection
                command.upgrade(config, 'head')
        finally:
            engine.dispose()
        app = application(settings, port)
        ready(app)
        password = generate_master_password()
        write_private(
            directory / 'initial-login.txt',
            f'用户名：{ADMIN}\n初始密码：{password}\n仅用于这个本地开发实例；改密后以新密码为准。\n',
        )
        with app.app_context():
            create_user(ADMIN, password, role='root', level=5)
    settings['ready'] = True
    save_settings(directory, settings)
    print(f'独立本地开发库已初始化，数据保存在：{directory}', flush=True)
    print('以后运行 ./start.sh；查看初始账号运行 ./start.sh --show-login。', flush=True)


def build_frontend():
    try:
        output = subprocess.check_output(['node', '--version'], text=True, timeout=10).strip()
        version = tuple(map(int, output.removeprefix('v').split('.')))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise LocalError('Node 不可用，请先运行 ./setup.sh 并检查 Node 安装。') from error
    if len(version) != 3 or not ((22, 18, 0) <= version < (23, 0, 0) or version >= (24, 12, 0)):
        raise LocalError('需要 Node ^22.18.0 或 >=24.12.0，请先配置支持的版本。')
    print('正在重新构建前端（包括 CSS），失败时不会启动旧页面…', flush=True)
    with child(
        ['npm', '--prefix', str(ROOT / 'frontend'), 'run', 'build'], env=os.environ.copy()
    ) as process:
        if process.wait() != 0:
            raise LocalError('前端构建失败。请运行 ./setup.sh 修复锁定依赖；未启动应用。')


def start(directory, settings, port):
    build_frontend()
    with mysql_server(directory, settings) as (db_port, _):
        app = application(settings, db_port)
        ready(app)
        server = make_server(
            '127.0.0.1', port, app, threaded=True, request_handler=LocalRequestHandler
        )
        try:
            print(f'\n本地开发服务：http://127.0.0.1:{server.server_port}/', flush=True)
            print('仅监听本机，不是生产部署；Ctrl+C 停止，已提交数据会保留。', flush=True)
            print(
                f'数据目录：{directory}\n初始账号：./start.sh --show-login（改密后旧密码不再有效）',
                flush=True,
            )
            server.serve_forever()
        finally:
            server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        '--init', action='store_true', help='仅初始化全新的独立本地数据库；拒绝已有数据'
    )
    action.add_argument(
        '--show-login', action='store_true', help='显示私有文件中的初始账号；不会重置密码'
    )
    parser.add_argument('--port', type=int, default=5000, help='本机 HTTP 端口，默认 5000')
    parser.add_argument(
        '--mysql-basedir', type=Path, help='仅初始化时指定 MySQL 二进制/资源目录，不接受旧 datadir'
    )
    options = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error('请使用普通用户运行，不要 sudo')
    if not 1 <= options.port <= 65535:
        parser.error('端口必须在 1–65535 之间')
    if options.mysql_basedir is not None and not options.init:
        parser.error('--mysql-basedir 只能与 --init 一同使用')
    os.chdir(ROOT)
    # Private mode is intentionally separate from .env and any inherited business configuration.
    for key in list(os.environ):
        if key.startswith('WM_'):
            del os.environ[key]
    try:
        directory = state_directory()
    except LocalError as error:
        parser.error(str(error))

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    # A background/nohup parent may have ignored SIGINT before exec. Explicitly
    # restore our own cleanup path rather than inheriting an uninterruptible launch.
    signal.signal(signal.SIGINT, terminate)
    try:
        if options.show_login:
            # Read-only, also available while the running server holds the lifecycle lock.
            if not directory.exists():
                raise LocalError('尚未初始化本地开发库，请先运行 ./setup.sh --init-local')
            check_private(directory, directory=True)
            load_settings(directory)
            check_private(directory / 'initial-login.txt')
            print((directory / 'initial-login.txt').read_text(), end='')
        else:
            with locked(directory, initialize=options.init):
                if options.init:
                    base = (
                        (
                            options.mysql_basedir
                            or Path.home() / '.local/share/wordmachine-test/mysql/usr'
                        )
                        .expanduser()
                        .resolve()
                    )
                    initialize(directory, base)
                else:
                    start(directory, load_settings(directory), options.port)
        return 0
    except KeyboardInterrupt:
        return 130
    except LocalError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        # Diagnostic SQL exceptions can contain parameters. Keep them private, never echo secrets.
        path = directory / f'launcher-error-{secrets.token_hex(4)}.log'
        diagnostic = traceback.format_exc()
        try:
            check_private(directory, directory=True)
            write_private(path, diagnostic)
            detail = f'请核对私有日志：{path}'
        except (OSError, LocalError):
            detail = '无法写入私有日志；未向终端输出可能含凭据的异常。'
        print(f'本地启动/初始化失败，数据未删除。{detail}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
