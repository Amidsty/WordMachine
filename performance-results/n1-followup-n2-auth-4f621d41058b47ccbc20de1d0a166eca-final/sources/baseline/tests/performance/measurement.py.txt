"""Measure real service SELECTs, including connections and DTO work, without copying SQL."""

import hashlib
import json
import os
import platform
import time
from contextlib import contextmanager
from pathlib import Path
from statistics import median
from unittest.mock import patch

from wm_app import db
from wm_app.services import auth, dictionary, leaderboard, lobby


def signature(result):
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def distribution(values):
    return {'min': min(values), 'median': median(values), 'max': max(values), 'samples': values}


def handlers(connection):
    with connection.cursor() as cursor:
        cursor.execute("SHOW SESSION STATUS LIKE 'Handler_read_%'")
        return {row['Variable_name']: int(row['Value']) for row in cursor.fetchall()}


class ReadCursor:
    def __init__(self, cursor, statements):
        self.cursor = cursor
        self.statements = statements

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def executemany(self, sql, params):
        raise ValueError('List benchmark does not accept bulk writes')

    def execute(self, sql, params=None):
        if not sql.lstrip().upper().startswith('SELECT '):
            raise ValueError('List benchmark accepts SELECT statements only')
        started = time.perf_counter()
        result = self.cursor.execute(sql, params)
        self.statements.append(
            {
                'sql': sql,
                'params': list(params or ()),
                'returned_rows': self.cursor.rowcount,
                'execute_ms': (time.perf_counter() - started) * 1000,
            }
        )
        return result


class ReadConnection:
    def __init__(self, connection, statements, counters):
        self.connection = connection
        self.statements = statements
        self.counters = counters
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
        self.before = handlers(connection)

    def cursor(self):
        return ReadCursor(self.connection.cursor(), self.statements)

    def close(self):
        try:
            after = handlers(self.connection)
            for key, value in after.items():
                self.counters[key] = self.counters.get(key, 0) + value - self.before[key]
        finally:
            self.connection.close()


@contextmanager
def trace_reads():
    original = db.get_db_connection
    statements, counters = [], {}

    def connect():
        connection = original()
        try:
            return ReadConnection(connection, statements, counters)
        except BaseException:
            connection.close()
            raise

    with patch.object(db, 'get_db_connection', connect):
        yield statements, counters


def plans(app, statements):
    with app.app_context(), db.reading() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        result = []
        for statement in statements:
            cursor.execute('EXPLAIN FORMAT=JSON ' + statement['sql'], statement['params'])
            result.append(json.loads(next(iter(cursor.fetchone().values()))))
        return result


def measure(app, operation, runs):
    # Explicitly one unreported warm-up. This is NOT a cold-cache or concurrent load test.
    with app.app_context(), trace_reads():
        reference = signature(operation())
    elapsed, samples, reads = [], [], []
    for _ in range(runs):
        with app.app_context(), trace_reads() as (statements, counters):
            started = time.perf_counter()
            data = operation()
            elapsed.append((time.perf_counter() - started) * 1000)
        assert signature(data) == reference, 'Read-only workload changed results between samples'
        assert statements
        samples.append(statements)
        reads.append(counters)

    def fingerprint(sample):
        return [(item['sql'], item['params'], item['returned_rows']) for item in sample]

    assert all(fingerprint(sample) == fingerprint(samples[0]) for sample in samples)
    items = next(data[key] for key in ('dicts', 'words', 'users', 'games') if key in data)
    assert len(items) <= data['pagination']['per_page']
    assert len({item['id'] for item in items}) == len(items)
    return {
        'result_sha256': reference,
        'pagination': data['pagination'],
        'item_ids': [item['id'] for item in items],
        'active_game_id': data.get('active_game_id'),
        'service_ms': distribution(elapsed),
        'handler_reads': {key: distribution([sample[key] for sample in reads]) for key in reads[0]},
        'statements': [
            {
                **statement,
                'execute_ms': distribution([sample[index]['execute_ms'] for sample in samples]),
                'plan': plan,
            }
            for index, (statement, plan) in enumerate(
                zip(samples[0], plans(app, samples[0]), strict=True)
            )
        ],
    }


def environment(app):
    with app.app_context(), db.reading() as cursor:
        cursor.execute(
            'SELECT VERSION() AS mysql_version, @@innodb_buffer_pool_size AS buffer_pool_bytes, '
            '@@collation_database AS collation, @@transaction_isolation AS isolation, '
            '@@optimizer_switch AS optimizer_switch, @@performance_schema AS performance_schema'
        )
        result = cursor.fetchone()
        cursor.execute('SELECT version_num FROM alembic_version')
        result['schema_revision'] = [row['version_num'] for row in cursor.fetchall()]
        result['row_counts'] = {}
        for table in ('user', 'dict', 'word', 'game', 'game_participant', 'game_question'):
            cursor.execute(f'SELECT COUNT(*) AS n FROM {table}')
            result['row_counts'][table] = cursor.fetchone()['n']
        result['python_version'] = platform.python_version()
        result['platform'] = platform.system() + ' ' + platform.machine()
        result['logical_cpus'] = os.cpu_count()
        result['source_sha256'] = {
            module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (db, auth, dictionary, leaderboard, lobby)
        }
        return result


def save_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Do not follow an existing symlink or replace a user's previous report.
    with path.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
