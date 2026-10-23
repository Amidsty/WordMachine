"""The opt-in benchmark must not silently change data or replace earlier reports."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.performance import measurement
from tests.performance.compare import compare
from tests.performance.dataset import SIZES, chunks
from tests.performance.index_costs import require_fixture


def test_synthetic_profiles_and_insert_batches_are_bounded():
    assert list(SIZES) == ['smoke', 'medium', 'large']
    assert all(
        0 < sizes['words'] <= 500000 and 0 < sizes['games'] <= 50000 for sizes in SIZES.values()
    )
    rows = list(chunks(iter(range(2005))))
    assert list(map(len, rows)) == [1000, 1000, 5]
    assert [item for batch in rows for item in batch] == list(range(2005))
    assert list(chunks([])) == []


def test_summary_retains_samples_and_digest_does_not_mask_null_or_zero():
    assert measurement.distribution([3, 1, 2]) == {
        'min': 1,
        'median': 2,
        'max': 3,
        'samples': [3, 1, 2],
    }
    assert measurement.signature({'a': 1, 'b': 2}) == measurement.signature({'b': 2, 'a': 1})
    assert measurement.signature({'rating': None}) != measurement.signature({'rating': 0})
    with pytest.raises(ValueError):
        measurement.signature({'rating': float('nan')})


@pytest.mark.parametrize('symlink', [False, True])
def test_report_creation_never_replaces_files_or_follows_existing_symlinks(tmp_path, symlink):
    target = tmp_path / 'existing.json'
    target.write_text('keep me')
    report = tmp_path / 'report.json' if symlink else target
    if symlink:
        report.symlink_to(target)
    with pytest.raises(FileExistsError):
        measurement.save_report(report, {'changed': True})
    assert target.read_text() == 'keep me'
    fresh = tmp_path / 'new' / 'report.json'
    measurement.save_report(fresh, {'scope': 'synthetic', 'value': '词'})
    assert json.loads(fresh.read_text()) == {'scope': 'synthetic', 'value': '词'}


@pytest.mark.parametrize(
    'sql',
    [
        'INSERT INTO t VALUES (1)',
        'UPDATE t SET x=1',
        'DELETE FROM t',
        'ALTER TABLE t ADD x INT',
        'SET autocommit=1',
        '',
    ],
)
def test_statement_recorder_rejects_non_select_before_execution(sql):
    cursor = MagicMock()
    recorder = measurement.ReadCursor(cursor, [])
    with pytest.raises(ValueError):
        recorder.execute(sql)
    cursor.execute.assert_not_called()
    with pytest.raises(ValueError):
        recorder.executemany('INSERT INTO t VALUES (%s)', [(1,)])
    cursor.executemany.assert_not_called()


def test_statement_recorder_preserves_binding_context_and_buffered_row_count():
    cursor, statements = MagicMock(), []
    cursor.rowcount = 2
    cursor.execute.return_value = 2
    with measurement.ReadCursor(cursor, statements) as recorder:
        assert recorder.execute('SELECT id FROM example WHERE id IN (%s, %s)', (7, 8)) == 2
        assert recorder.fetchall() is cursor.fetchall.return_value
    cursor.execute.assert_called_once_with('SELECT id FROM example WHERE id IN (%s, %s)', (7, 8))
    cursor.__exit__.assert_called_once()
    assert statements[0]['params'] == [7, 8] and statements[0]['returned_rows'] == 2
    assert statements[0]['execute_ms'] >= 0


def test_handler_counters_are_session_deltas_and_connection_closes(monkeypatch):
    connection, counters = MagicMock(), {}
    snapshots = iter([{'Handler_read_next': 10}, {'Handler_read_next': 25}])
    monkeypatch.setattr(measurement, 'handlers', lambda _: next(snapshots))
    wrapped = measurement.ReadConnection(connection, [], counters)
    connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
        'SET TRANSACTION READ ONLY'
    )
    wrapped.close()
    assert counters == {'Handler_read_next': 15}
    connection.close.assert_called_once()


def test_counter_failure_still_closes_connection(monkeypatch):
    connection = MagicMock()
    reader = MagicMock(side_effect=[{'Handler_read_next': 10}, RuntimeError('counter failure')])
    monkeypatch.setattr(measurement, 'handlers', reader)
    wrapped = measurement.ReadConnection(connection, [], {})
    with pytest.raises(RuntimeError, match='counter failure'):
        wrapped.close()
    connection.close.assert_called_once()


def test_trace_setup_failure_closes_real_connection_and_restores_factory(monkeypatch):
    connection = MagicMock()
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(measurement.db, 'get_db_connection', factory)
    monkeypatch.setattr(
        measurement, 'handlers', MagicMock(side_effect=RuntimeError('setup failure'))
    )
    with pytest.raises(RuntimeError, match='setup failure'), measurement.trace_reads():
        measurement.db.get_db_connection()
    connection.close.assert_called_once()
    assert measurement.db.get_db_connection is factory


def example_report():
    return {
        'format_version': 1,
        'scope': 'synthetic',
        'profile': 'smoke',
        'generated_rows': {'words': 1000},
        'warmups_per_case': 1,
        'measured_runs_per_case': 3,
        'environment': {'row_counts': {'word': 1003}, 'source_sha256': {'service': 'old'}},
        'cases': {
            'example': {
                'result_sha256': 'same',
                'pagination': {'total': 1},
                'item_ids': [1],
                'active_game_id': None,
                'service_ms': {'median': 5},
                'statements': [{}, {}],
            }
        },
    }


def test_comparison_allows_source_and_plan_changes_not_result_changes():
    before = example_report()
    after = deepcopy(before)
    after['environment']['source_sha256']['service'] = 'new'
    after['cases']['example'].update(service_ms={'median': 2}, statements=[{}])
    assert compare(before, after) == [('example', 5, 2, 2, 1)]


@pytest.mark.parametrize(
    'field,value',
    [
        ('result_sha256', 'changed'),
        ('pagination', {'total': 0}),
        ('item_ids', []),
        ('active_game_id', 123),
    ],
)
def test_comparison_refuses_changed_results(field, value):
    before = example_report()
    after = deepcopy(before)
    after['cases']['example'][field] = value
    with pytest.raises(ValueError, match='Result changed'):
        compare(before, after)


@pytest.mark.parametrize(
    'field,value',
    [
        ('format_version', 2),
        ('scope', 'other'),
        ('profile', 'large'),
        ('generated_rows', {'words': 0}),
        ('warmups_per_case', 2),
        ('measured_runs_per_case', 5),
        ('cases', {}),
        ('environment', {'row_counts': {'word': 999}}),
    ],
)
def test_comparison_refuses_incompatible_method_environment_and_cases(field, value):
    before = example_report()
    after = deepcopy(before)
    after[field] = value
    with pytest.raises(ValueError):
        compare(before, after)


def test_comparison_cli_exits_nonzero_on_mismatch_without_rewriting_reports(tmp_path):
    before, after = tmp_path / 'before.json', tmp_path / 'after.json'
    original = json.dumps(example_report())
    before.write_text(original)
    after.write_text(original)
    command = [sys.executable, '-m', 'tests.performance.compare', str(before), str(after)]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0 and 'not a production SLA' in result.stdout
    modified = example_report()
    modified['cases']['example']['result_sha256'] = 'changed'
    after.write_text(json.dumps(modified))
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode != 0 and 'Result changed' in result.stderr
    assert before.read_text() == original
    assert json.loads(after.read_text()) == modified


def test_make_benchmark_defaults_to_private_mysql_and_live_requires_url():
    env = dict(os.environ)
    env.pop('WM_TEST_MYSQL_URL', None)
    result = subprocess.run(
        ['make', 'benchmark-live', f'PYTHON={sys.executable}'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert 'WM_TEST_MYSQL_URL is required; use make benchmark-mysql' in result.stderr
    dry_run = subprocess.run(
        ['make', '-n', 'benchmark-mysql', f'PYTHON={sys.executable}'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert dry_run.returncode == 0
    assert 'scripts/with_test_mysql.py --' in dry_run.stdout
    assert 'tests/performance' in dry_run.stdout
    assert '--list-perf-size=medium --list-perf-runs=3' in dry_run.stdout


@pytest.mark.parametrize(
    'testing,name',
    [(False, 'wm_test_' + 'a' * 32), (True, 'wordmachine'), (True, 'wm_test_'), (True, None)],
)
def test_write_probes_reject_non_fixture_configuration_before_connecting(testing, name):
    with pytest.raises(ValueError, match='disposable synthetic'):
        require_fixture(SimpleNamespace(testing=testing, config={'DB_NAME': name}))
    require_fixture(SimpleNamespace(testing=True, config={'DB_NAME': 'wm_test_' + 'a' * 32}))


def test_report_comparison_only_allows_the_explicit_revision_pair():
    before, after = example_report(), example_report()
    before['environment']['schema_revision'] = ['0007_game_settlements']
    after['environment']['schema_revision'] = ['0008_list_indexes']
    with pytest.raises(ValueError, match='environment'):
        compare(before, after)
    pair = ('0007_game_settlements', '0008_list_indexes')
    assert compare(before, after, expected_revisions=pair)
    assert before['environment']['schema_revision'] == [pair[0]]
    assert after['environment']['schema_revision'] == [pair[1]]
    after['environment']['row_counts']['word'] += 1
    with pytest.raises(ValueError, match='environment'):
        compare(before, after, expected_revisions=pair)


@pytest.mark.parametrize(
    'pair', [(), ('old',), ('wrong', 'new'), ('old', 'wrong'), ('old', 'new', 'extra')]
)
def test_report_comparison_does_not_ignore_unknown_or_unreviewed_schema_changes(pair):
    before, after = example_report(), example_report()
    before['environment']['schema_revision'] = ['old']
    after['environment']['schema_revision'] = ['new']
    with pytest.raises(ValueError, match='revision'):
        compare(before, after, expected_revisions=pair)
