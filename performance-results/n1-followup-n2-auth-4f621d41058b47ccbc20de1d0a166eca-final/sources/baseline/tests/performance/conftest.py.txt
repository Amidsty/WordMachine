"""Opt-in synthetic list benchmark. Never select an existing application database."""

import pytest

from tests.integration.conftest import legacy_database, migrate_database
from wm_app import create_app

from .dataset import DISTRIBUTIONS

__all__ = ['legacy_database', 'migrate_database']


def pytest_addoption(parser):
    group = parser.getgroup('list-performance')
    group.addoption('--list-perf-size', choices=('smoke', 'medium', 'large'), default='smoke')
    group.addoption('--list-perf-runs', type=int, choices=(1, 3, 5, 9), default=3)
    group.addoption('--list-perf-distribution', choices=tuple(DISTRIBUTIONS), default='standard')
    group.addoption(
        '--list-perf-revision', choices=('head', '0007_game_settlements'), default='head'
    )
    group.addoption(
        '--list-perf-write-costs',
        action='store_true',
        help='Optional committed synthetic write probes; never a live-data profiler',
    )
    group.addoption(
        '--list-perf-report', default=None, help='New JSON path; never overwrite a file'
    )


@pytest.fixture
def perf_app(legacy_database, migrate_database, request):
    migrate_database(legacy_database, request.config.getoption('--list-perf-revision'))
    return create_app(legacy_database['config'])


@pytest.fixture
def perf_options(request):
    return {
        'size': request.config.getoption('--list-perf-size'),
        'distribution': request.config.getoption('--list-perf-distribution'),
        'runs': request.config.getoption('--list-perf-runs'),
        'report': request.config.getoption('--list-perf-report'),
        'writes': request.config.getoption('--list-perf-write-costs'),
    }
