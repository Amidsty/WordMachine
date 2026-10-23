import json
import os
from pathlib import Path

import pytest

from scripts import local_dev as local
from scripts.with_test_mysql import server_options


@pytest.fixture
def profile(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / 'data').mkdir(mode=0o700)
    settings = {
        'format': 1,
        'project': str(local.ROOT),
        'ready': True,
        'mysql_base': '/unused/mysql/usr',
        'root_password': 'a' * 64,
        'db_password': 'b' * 64,
        'secret_key': 'c' * 64,
    }
    local.save_settings(tmp_path, settings)
    return tmp_path, settings


def test_profile_is_private_and_settings_are_not_overwritten_on_read(profile):
    directory, settings = profile
    original = (directory / 'settings.json').read_bytes()
    assert local.load_settings(directory) == settings
    assert (directory / 'settings.json').read_bytes() == original
    assert (directory / 'settings.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ('key', 'value'),
    [
        ('ready', False),
        ('format', 2),
        ('format', True),
        ('project', '/another/project'),
        ('root_password', 'short'),
        ('mysql_base', 'relative'),
    ],
)
def test_partial_or_mismatched_profile_is_not_adopted(profile, key, value):
    directory, settings = profile
    settings[key] = value
    local.save_settings(directory, settings)
    with pytest.raises(local.LocalError, match='不自动初始化'):
        local.load_settings(directory)
    assert json.loads((directory / 'settings.json').read_text())[key] == value


def test_lifecycle_lock_rejects_second_instance_and_releases_after_failure(profile):
    directory, _ = profile
    with pytest.raises(RuntimeError, match='injected'):
        with local.locked(directory):
            with pytest.raises(local.LocalError, match='正在运行'):
                with local.locked(directory):
                    pytest.fail('second process must not enter')
            raise RuntimeError('injected')
    with local.locked(directory):
        pass


def test_init_refuses_existing_data_before_any_mysql_or_migration_work(profile, monkeypatch):
    directory, _ = profile
    before = (directory / 'settings.json').read_bytes()
    monkeypatch.setattr(local, 'server_options', lambda *args: pytest.fail('must not start MySQL'))
    with pytest.raises(local.LocalError, match='拒绝覆盖'):
        local.initialize(directory, Path('/unused'))
    assert (directory / 'settings.json').read_bytes() == before


def test_profile_symlink_and_public_permissions_are_rejected(profile):
    directory, _ = profile
    path = directory / 'settings.json'
    path.chmod(0o644)
    with pytest.raises(local.LocalError, match='权限不符'):
        local.load_settings(directory)
    path.chmod(0o600)
    path.rename(directory / 'original.json')
    path.symlink_to(directory / 'original.json')
    with pytest.raises(local.LocalError, match='权限不符'):
        local.load_settings(directory)


def test_main_ignores_business_environment_and_never_initializes_on_start(profile, monkeypatch):
    directory, settings = profile
    inherited = dict(
        os.environ, WM_ENV='production', WM_DB_HOST='business.invalid', WM_PORT='invalid'
    )
    monkeypatch.setattr(os, 'environ', inherited)
    monkeypatch.setattr(local, 'state_directory', lambda: directory)
    monkeypatch.setattr(local.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(
        local, 'initialize', lambda *args: pytest.fail('ordinary start is not init')
    )
    calls = []

    def start(path, config, port):
        assert not any(key.startswith('WM_') for key in os.environ)
        calls.append((path, config, port))

    monkeypatch.setattr(local, 'start', start)
    assert local.main(['--port', '5001']) == 0
    assert calls == [(directory, settings, 5001)]


def test_credentials_can_be_read_while_running_without_unlocking_or_resetting(
    profile, monkeypatch, capsys
):
    directory, _ = profile
    local.write_private(directory / 'initial-login.txt', 'initial synthetic credentials\n')
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    monkeypatch.setattr(local, 'state_directory', lambda: directory)
    monkeypatch.setattr(local.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(local, 'start', lambda *args: pytest.fail('read only'))
    with local.locked(directory):
        assert local.main(['--show-login']) == 0
        with pytest.raises(local.LocalError, match='正在运行'):
            with local.locked(directory):
                pytest.fail('existing lock must remain')
    assert capsys.readouterr().out == 'initial synthetic credentials\n'


def test_missing_profile_does_not_initialize_or_create_data(tmp_path):
    directory = tmp_path / 'missing'
    with pytest.raises(local.LocalError, match='尚未初始化'):
        with local.locked(directory):
            pytest.fail('must not enter')
    assert not directory.exists()


def test_frontend_failure_stops_before_mysql_start(profile, monkeypatch):
    directory, settings = profile

    def fail():
        raise local.LocalError('build failed')

    monkeypatch.setattr(local, 'build_frontend', fail)
    monkeypatch.setattr(local, 'mysql_server', lambda *args: pytest.fail('must not start MySQL'))
    with pytest.raises(local.LocalError, match='build failed'):
        local.start(directory, settings, 5000)


def test_profile_cookie_names_are_stable_and_separate_from_default_and_other_profiles(profile):
    _, settings = profile
    first = local.application(settings, 12345)
    restarted = local.application(settings, 12346)
    another = local.application({**settings, 'secret_key': 'd' * 64}, 12347)
    for key, legacy in [('AUTH_COOKIE_NAME', 'wm_session'), ('CSRF_COOKIE_NAME', 'wm_csrf')]:
        assert first.config[key] == restarted.config[key]
        assert first.config[key] != another.config[key]
        assert first.config[key] != legacy
    assert first.config['ENVIRONMENT'] == 'development' and not first.config['DEBUG']


def test_shared_server_options_do_not_create_or_start_a_database(tmp_path):
    base = tmp_path / 'binary'
    (base / 'bin').mkdir(parents=True)
    (base / 'bin/mysqld').touch()
    (base / 'share/english').mkdir(parents=True)
    (base / 'share/english/errmsg.sys').touch()
    directory = tmp_path / 'nonexistent'
    args, _ = server_options(base, directory)
    assert args[:2] == [str(base / 'bin/mysqld'), '--no-defaults']
    assert f'--datadir={directory / "data"}' in args
    assert '--mysqlx=0' in args and '--local-infile=0' in args
    assert not directory.exists()


@pytest.mark.parametrize('data_home', ['relative', '/' + 'a' * 120])
def test_unsafe_or_overlong_data_paths_fail_before_creation(monkeypatch, data_home):
    monkeypatch.setenv('XDG_DATA_HOME', data_home)
    with pytest.raises(local.LocalError):
        local.state_directory()
