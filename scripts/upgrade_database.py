"""Explicit 0011..0018 upgrade; default is a read-only version/plan check.

Uses explicit WM_DB_HOST/PORT/NAME/USER/PASSWORD, never local-launcher settings.
Backups, restoring a copy and stopping ALL writers are operator prerequisites.
No initialization, account reset, retry, stamp, downgrade or service management.
"""

import argparse
import hashlib
import json
import os
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymysql
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = (
    '0011_dictionary_multipliers',
    '0012_manual_rating',
    '0013_game_rated',
    '0014_rated_bounds',
    '0015_dictionary_promotions',
    '0016_game_names',
    '0017_weighted_rating',
    '0018_bounded_rating',
)
TARGET = REVISIONS[-1]
ADDITIONS = {
    '0018_bounded_rating': {
        'tables': (),
        'columns': {'game_rating_snapshot': {'rule_version': 'weighted-rating-v1'}},
    },
    '0012_manual_rating': {
        'tables': ('rating_adjustment_request', 'manual_rating'),
        'columns': {'rating_event': {'manual_rating_id': None}},
    },
    '0013_game_rated': {'tables': (), 'columns': {'game': {'rated': 1}}},
    '0014_rated_bounds': {
        'tables': ('dictionary_rated_audit',),
        'columns': {'dict': {'rated_min': -2147483648, 'rated_max': 2147483647}},
    },
    '0015_dictionary_promotions': {'tables': ('dictionary_promotion',), 'columns': {}},
    '0016_game_names': {'tables': (), 'columns': {'game': {'name': None}}},
    '0017_weighted_rating': {
        'tables': (
            'user_rating_state',
            'rated_occupancy',
            'game_rating_snapshot',
            'weighted_answer',
            'weighted_result',
            'newcomer_award',
            'dictionary_difficulty_audit',
        ),
        'columns': {
            'dict': {'difficulty': 1500},
            'game': {'rating_model': 0, 'difficulty_snapshot': None, 'rating_parameters': None},
            'game_rating': {'rule_version': 'legacy-v1'},
        },
    },
}


class UpgradeError(Exception):
    """Only explicitly safe, credential-free messages are displayed."""


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Read-only version/plan check (default)')
    mode.add_argument('--apply', action='store_true', help='Explicitly execute reviewed migrations')
    result.add_argument('--target', default=TARGET, choices=REVISIONS)
    result.add_argument('--expected-current', choices=REVISIONS)
    result.add_argument('--confirm-database', help='Must exactly match WM_DB_NAME')
    result.add_argument(
        '--report', type=Path, help='NEW private JSON file, outside the source tree'
    )
    result.add_argument('--writers-stopped', action='store_true')
    result.add_argument('--backup-verified', action='store_true')
    result.add_argument('--restore-tested', action='store_true')
    result.add_argument('--rehearsal-verified', action='store_true')
    return result


def connection_url(environment):
    keys = ('WM_DB_HOST', 'WM_DB_PORT', 'WM_DB_NAME', 'WM_DB_USER', 'WM_DB_PASSWORD')
    if any(key not in environment for key in keys):
        raise UpgradeError(
            'Explicit WM_DB_HOST/PORT/NAME/USER/PASSWORD are required; .env is not loaded'
        )
    if any(not environment[key] for key in keys):
        raise UpgradeError('Connection settings must be nonempty; use a password-protected account')
    try:
        port = int(environment['WM_DB_PORT'])
    except ValueError:
        raise UpgradeError('WM_DB_PORT must be an integer in 1..65535') from None
    if not 1 <= port <= 65535:
        raise UpgradeError('WM_DB_PORT must be an integer in 1..65535')
    return URL.create(
        'mysql+pymysql',
        username=environment['WM_DB_USER'],
        password=environment['WM_DB_PASSWORD'],
        host=environment['WM_DB_HOST'],
        port=port,
        database=environment['WM_DB_NAME'],
        query={'charset': 'utf8mb4'},
    )


def alembic_config():
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    return config


def migration_plan(current, target):
    scripts = ScriptDirectory.from_config(alembic_config())
    if scripts.get_heads() != [TARGET]:
        raise UpgradeError('Source head changed; this upgrade procedure needs review')
    for previous, revision in zip(REVISIONS, REVISIONS[1:], strict=False):
        if scripts.get_revision(revision).down_revision != previous:
            raise UpgradeError('Unexpected migration chain; review source before upgrading')
    if current not in REVISIONS:
        raise UpgradeError(
            'Only intact 0011..0018 databases are supported; no initialization or adoption'
        )
    if target not in REVISIONS or REVISIONS.index(target) < REVISIONS.index(current):
        raise UpgradeError('Downgrade is not supported')
    return list(REVISIONS[REVISIONS.index(current) + 1 : REVISIONS.index(target) + 1])


def current_revision(connection):
    exists = connection.exec_driver_sql(
        'SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() '
        "AND TABLE_NAME='alembic_version' AND TABLE_TYPE='BASE TABLE'"
    ).scalar_one()
    if exists != 1:
        raise UpgradeError('Missing version table; do not initialize or stamp an existing database')
    rows = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalars().all()
    if len(rows) != 1:
        raise UpgradeError('Exactly one database revision is required')
    return rows[0]


def identifier(value):
    return '`' + value.replace('`', '``') + '`'


def snapshot(connection, projection=None):
    """Stream ALL original values in PK order; digests are NOT a backup."""
    connection.rollback()
    connection.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
    result = {}
    try:
        objects = connection.exec_driver_sql(
            'SELECT TABLE_NAME, TABLE_TYPE, ENGINE FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME'
        ).all()
        for name, kind, engine in objects:
            if kind != 'BASE TABLE' or engine != 'InnoDB':
                raise UpgradeError('Views/non-InnoDB tables require separate review')
            columns = [
                row[0]
                for row in connection.exec_driver_sql('SHOW COLUMNS FROM ' + identifier(name))
            ]
            keys = connection.exec_driver_sql(
                'SHOW KEYS FROM ' + identifier(name) + " WHERE Key_name='PRIMARY'"
            ).all()
            primary = [row[4] for row in sorted(keys, key=lambda row: row[3])]
            if not primary:
                raise UpgradeError(
                    'Every table must have a stable primary key for full-row verification'
                )
            selected = projection[name]['columns'] if projection and name in projection else columns
            if not set(selected) <= set(columns):
                raise UpgradeError('An original column is missing; keep writers stopped')
            digest, count = hashlib.sha256(), 0
            query = (
                'SELECT '
                + ','.join(map(identifier, selected))
                + ' FROM '
                + identifier(name)
                + ' ORDER BY '
                + ','.join(map(identifier, primary))
            )
            with connection.connection.dbapi_connection.cursor(pymysql.cursors.SSCursor) as cursor:
                cursor.execute(query)
                for row in cursor:
                    # Same Python/driver/session for both passes; no JSON/float rounding.
                    encoded = repr(row).encode('utf-8')
                    digest.update(len(encoded).to_bytes(8, 'big'))
                    digest.update(encoded)
                    count += 1
            result[name] = {
                'columns': columns,
                'primary': primary,
                'rows': count,
                'sha256': digest.hexdigest(),
            }
        return result
    finally:
        connection.rollback()


def verify_preserved(connection, original, applied):
    after = snapshot(connection, original)
    added_tables, added_columns = set(), {}
    for revision in applied:
        change = ADDITIONS[revision]
        added_tables.update(change['tables'])
        for table, columns in change['columns'].items():
            added_columns.setdefault(table, {}).update(columns)
    if set(after) != set(original) | added_tables:
        raise UpgradeError('Unexpected table set after migration; keep writers stopped')
    for name, before in original.items():
        expected_columns = before['columns'] + list(added_columns.get(name, {}))
        if (
            after[name]['columns'] != expected_columns
            or after[name]['primary'] != before['primary']
        ):
            raise UpgradeError('Unexpected column/primary-key change; keep writers stopped')
        if name != 'alembic_version' and any(
            after[name][key] != before[key] for key in ('rows', 'sha256')
        ):
            raise UpgradeError(
                'Original row values changed; keep writers stopped and review the report'
            )
    initialized = (
        {'user_rating_state', 'rated_occupancy'} if '0017_weighted_rating' in applied else set()
    )
    if initialized:
        verify_weighted_initialization(connection, original, after)
    if any(after[name]['rows'] != 0 for name in added_tables - initialized):
        raise UpgradeError('New migration tables must remain empty until service resumes')
    for table, columns in added_columns.items():
        for column, default in columns.items():
            invalid = connection.exec_driver_sql(
                'SELECT COUNT(*) FROM '
                + identifier(table)
                + ' WHERE NOT ('
                + identifier(column)
                + ' <=> %s)',
                (default,),
            ).scalar_one()
            if invalid:
                raise UpgradeError(
                    'Unexpected values in a newly added column; keep writers stopped'
                )
    if '0018_bounded_rating' in applied:
        from wm_app.models import weighted_v2

        expected = {(table, new) for table, _, new, _ in weighted_v2.REPLACEMENTS}
        expected.add(('game_rating_snapshot', 'ck_weighted_snapshot_rule_v2'))
        actual = {
            (row[0], row[1])
            for row in connection.exec_driver_sql(
                "SELECT TABLE_NAME,CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='CHECK' AND ENFORCED='YES'"
            )
        }
        if not expected <= actual or any(
            (table, old) in actual for table, old, _, _ in weighted_v2.REPLACEMENTS
        ):
            raise UpgradeError('Bounded scoring CHECKs require review; keep writers stopped')
    connection.rollback()
    return after


def verify_weighted_initialization(connection, original, after):
    if after['user_rating_state']['rows'] != original['user']['rows']:
        raise UpgradeError('Weighted account initialization count differs; keep writers stopped')
    invalid = connection.exec_driver_sql(
        'SELECT COUNT(*) FROM user u LEFT JOIN user_rating_state s ON s.user_id=u.id WHERE s.user_id IS NULL OR s.newcomer_enabled<>0 OR s.completed_games<>0 OR s.remaining_bonus<>0'
    ).scalar_one()
    if invalid:
        raise UpgradeError('Old account policy changed; keep writers stopped')
    expected = "(SELECT p.user_id, g.id AS game_id FROM game g JOIN game_participant p ON p.game_id=g.id WHERE g.status=0 AND g.rated=1 AND g.participant_mode=1 UNION ALL SELECT u.id AS user_id,g.id AS game_id FROM game g JOIN user u ON JSON_CONTAINS(CASE WHEN JSON_VALID(g.users) THEN g.users ELSE '[]' END, CAST(u.id AS JSON))=1 WHERE g.status=0 AND g.rated=1 AND g.participant_mode=0)"
    count = connection.exec_driver_sql('SELECT COUNT(*) FROM ' + expected + ' e').scalar_one()
    invalid = connection.exec_driver_sql(
        'SELECT COUNT(*) FROM rated_occupancy o LEFT JOIN '
        + expected
        + ' e ON e.user_id=o.user_id AND e.game_id=o.game_id WHERE e.user_id IS NULL'
    ).scalar_one()
    if count != after['rated_occupancy']['rows'] or invalid:
        raise UpgradeError('Running Rated occupancy differs; keep writers stopped')


class Report:
    def __init__(self, path, data):
        self.path = path.expanduser().absolute()
        if self.path.resolve().is_relative_to(ROOT):
            raise UpgradeError('The private report must be outside the source tree')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = self.path.parent
        if parent.is_symlink() or parent.stat().st_mode & 0o077:
            raise UpgradeError('Use a private report directory (0700 on POSIX)')
        if hasattr(os, 'getuid') and parent.stat().st_uid != os.getuid():
            raise UpgradeError('Report directory must be owned by the current user')
        self.data = data
        # Exclusive creation: never overwrite a previous attempt, including a failed one.
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())

    def save(self, **changes):
        self.data.update(changes, updated_at=datetime.now(timezone.utc).isoformat())
        temporary = self.path.with_name('.upgrade-' + uuid4().hex)
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump(self.data, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            if os.name == 'posix':
                descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def validate_apply(options, database):
    if (
        not options.expected_current
        or options.confirm_database != database
        or not options.report
        or not options.writers_stopped
        or not options.backup_verified
        or not options.restore_tested
        or not options.rehearsal_verified
    ):
        raise UpgradeError(
            'Apply requires expected revision, exact database confirmation, a NEW private report, '
            'and explicit stopped-writer/backup/restore/rehearsal confirmations'
        )


def execute(connection, options, database):
    if connection.dialect.is_mariadb or connection.dialect.server_version_info < (8, 0, 16):
        raise UpgradeError('MySQL 8.0.16+ is required; MariaDB is not supported')
    actual_database, server_uuid = connection.exec_driver_sql(
        'SELECT DATABASE(), @@server_uuid'
    ).one()
    if actual_database != database:
        raise UpgradeError('Connected database does not match the explicit configuration')
    current = current_revision(connection)
    steps = migration_plan(current, options.target)
    print(f'Current revision: {current}; target: {options.target}')
    print('Plan: ' + (' -> '.join(steps) if steps else 'no migration needed'))
    connection.rollback()
    if not options.apply:
        print('Read-only version check only; NOT a schema audit, backup or migration rehearsal.')
        return
    validate_apply(options, database)
    lock_name = (
        'wm-upgrade:' + hashlib.sha256((server_uuid + ':' + database).encode()).hexdigest()[:48]
    )
    acquired = connection.exec_driver_sql('SELECT GET_LOCK(%s, 0)', (lock_name,)).scalar_one()
    connection.commit()
    if acquired != 1:
        raise UpgradeError('Another upgrade session holds the database advisory lock')
    report = None
    try:
        # Recheck AFTER obtaining the lock. It coordinates this script, not arbitrary writers.
        if (
            current_revision(connection) != options.expected_current
            or options.expected_current != current
        ):
            raise UpgradeError(
                'Actual revision differs from expected-current; review, do not retry blindly'
            )
        if not steps:
            print(
                'Already at target; no DDL executed. Version alone does not prove schema integrity.'
            )
            return
        if connection.exec_driver_sql(
            'SELECT @@global.read_only OR @@global.super_read_only'
        ).scalar_one():
            raise UpgradeError('Server is read-only; this script will not change server settings')
        for table, field in (
            ('TRIGGERS', 'TRIGGER_SCHEMA'),
            ('ROUTINES', 'ROUTINE_SCHEMA'),
            ('EVENTS', 'EVENT_SCHEMA'),
        ):
            if connection.exec_driver_sql(
                f'SELECT COUNT(*) FROM information_schema.{table} WHERE {field}=DATABASE()'
            ).scalar_one():
                raise UpgradeError(
                    'Stored triggers/routines/events require a separately reviewed procedure'
                )
        connection.rollback()
        connection.exec_driver_sql("SET SESSION time_zone = '+00:00'")
        connection.commit()
        original = snapshot(connection)
        report = Report(
            options.report,
            {
                'status': 'prepared',
                'database': database,
                'server_uuid': server_uuid,
                'from_revision': current,
                'target': options.target,
                'plan': steps,
                'original': original,
                'completed_steps': [],
                'operator_confirmations_only': True,
            },
        )
        applied = []
        for step in steps:
            report.save(status='applying', active_step=step)
            config = alembic_config()
            config.attributes['connection'] = connection
            with connection.begin():
                command.upgrade(config, step)
            if current_revision(connection) != step:
                raise UpgradeError(
                    'Migration returned an unexpected revision; keep writers stopped'
                )
            applied.append(step)
            after = verify_preserved(connection, original, applied)
            report.save(status='verified_step', completed_steps=list(applied), last_verified=after)
            print(f'Verified {step}: all original business column values preserved')
        report.save(status='complete', active_step=None)
        print(
            'Migration/data checks complete. Keep maintenance mode until schema/audit/health checks pass.'
        )
    except BaseException as error:
        if report is not None:
            with suppress(Exception):
                report.save(status='needs_review', error_type=type(error).__name__)
        raise
    finally:
        # A lost connection must NOT reconnect and try the migration again.
        with suppress(Exception):
            if not connection.invalidated:
                connection.rollback()
                connection.exec_driver_sql('SELECT RELEASE_LOCK(%s)', (lock_name,))
                connection.commit()


def main(argv=None):
    options = parser().parse_args(argv)
    engine = None
    try:
        url = connection_url(os.environ)
        if options.apply:
            validate_apply(options, url.database)
        engine = create_engine(
            url,
            poolclass=NullPool,
            hide_parameters=True,
            isolation_level='REPEATABLE READ',
            connect_args={'connect_timeout': 5, 'read_timeout': 600, 'write_timeout': 30},
        )
        with engine.connect() as connection:
            execute(connection, options, url.database)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        message = str(error) if isinstance(error, UpgradeError) else type(error).__name__
        print(
            f'STOP: {message}. Keep writers stopped; MySQL DDL may already be committed. '
            'Do not blindly rerun, change the report path to bypass review, stamp or downgrade.',
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    # migrations/env.py imports wm_app; make invocation independent of the working directory.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
