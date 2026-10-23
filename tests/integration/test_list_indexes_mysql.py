"""Index-only upgrades must preserve data, preflight all DDL and reject partial retries."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError

from wm_app import create_app
from wm_app.db import transaction
from wm_app.services import game_requests

pytestmark = pytest.mark.mysql
PREVIOUS = '0007_game_settlements'
HEAD = '0008_list_indexes'
NAMES = {'word': 'ix_word_dict_deleted_id', 'user': 'ix_user_deleted_rating_id'}


def migrate(database, *, downgrade=False, fail_on=None, lock_wait=None):
    engine = create_engine(database['url'])
    try:
        if fail_on:

            def fail(conn, cursor, statement, parameters, context, executemany):
                if fail_on in statement:
                    raise RuntimeError('injected DDL failure')

            event.listen(engine, 'before_cursor_execute', fail)
        with engine.begin() as connection:
            if lock_wait is not None:
                connection.execute(
                    text('SET SESSION lock_wait_timeout = :seconds'), {'seconds': lock_wait}
                )
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            config.attributes['connection'] = connection
            if downgrade:
                command.downgrade(config, PREVIOUS)
            else:
                command.upgrade(config, HEAD)
    finally:
        engine.dispose()


def snapshot(connection):
    inspector = inspect(connection)
    result = {}
    for table in inspector.get_table_names():
        if table == 'alembic_version':
            continue
        columns = inspector.get_pk_constraint(table)['constrained_columns'] or [
            column['name'] for column in inspector.get_columns(table)
        ]
        order = ', '.join(f'`{column}`' for column in columns)
        result[table] = [
            dict(row)
            for row in connection.execute(
                text(f'SELECT * FROM `{table}` ORDER BY {order}')
            ).mappings()
        ]
    return result


def index_names(connection, table):
    return {index['name'] for index in inspect(connection).get_indexes(table)}


def version(connection):
    return connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()


def test_index_upgrade_downgrade_and_reupgrade_preserve_all_data_and_receipts(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, PREVIOUS)
    app = create_app(legacy_database['config'])
    engine = create_engine(legacy_database['url'])
    with engine.begin() as conn:
        for statement in Path(__file__).with_name('index_data_0007.sql').read_text().split(';'):
            if statement.strip():
                conn.execute(text(statement))
    # Only the schema-frozen receipt protocol is exercised on 0007/0008, not
    # current auth/game business APIs. Their old-session/history coverage lives
    # in the current-head migration and game integration tests.
    request_id = str(uuid4())
    with app.app_context(), transaction() as cursor:
        assert game_requests.reserve(cursor, 1, request_id, 'end', 1, {}, 3) is None
        receipt = game_requests.complete(
            cursor,
            1,
            request_id,
            1,
            4,
            {
                'success': True,
                'game_id': 1,
                'status': 1,
                'already_finished': False,
            },
        )
    try:
        with engine.begin() as conn:
            conn.execute(
                text('UPDATE game SET perf = :value WHERE id = 1'), {'value': ' { "1" : 1500.0 } '}
            )
            conn.execute(
                text(
                    "INSERT INTO word (id,dictid,english,chinese,deleted) VALUES (-5,NULL,NULL,'',NULL), (44,999,'same','相同',1), (55,999,'same','相同',1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO user (id,username,rating,deleted) VALUES (4,'nullable',NULL,NULL), (5,'negative',-100,1)"
                )
            )
            before = snapshot(conn)
            assert before['auth_session'] and before['auth_rate_limit']
            assert before['game_answer'] and before['game_rating'] and before['game_request']
            old_indexes = {table: index_names(conn, table) for table in NAMES}
        assert app.test_client().get('/health/ready').status_code == 503
        for is_down in (False, True, False):
            migrate(legacy_database, downgrade=is_down)
            with engine.connect() as conn:
                assert snapshot(conn) == before
                assert version(conn) == (PREVIOUS if is_down else HEAD)
                for table, name in NAMES.items():
                    assert index_names(conn, table) == old_indexes[table] | (
                        set() if is_down else {name}
                    )
            assert app.test_client().get('/health/ready').status_code == 503
            with app.app_context(), transaction() as cursor:
                assert game_requests.reserve(cursor, 1, request_id, 'end', 1, {}, 3) == receipt
            with engine.connect() as conn:
                assert snapshot(conn) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'table,parts',
    [
        ('word', [('dictid', 'A'), ('deleted', 'A'), ('id', 'A')]),
        ('user', [('deleted', 'A'), ('rating', 'D'), ('id', 'A')]),
    ],
)
def test_index_shape_is_nonunique_visible_full_length_and_matches_metadata(
    mysql_app, legacy_database, table, parts
):
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateIndex

    from wm_app.models import Base

    engine = create_engine(legacy_database['url'])
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        'SELECT COLUMN_NAME, COLLATION, NON_UNIQUE, SUB_PART, IS_VISIBLE, INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :name ORDER BY SEQ_IN_INDEX'
                    ),
                    {'table': table, 'name': NAMES[table]},
                )
                .mappings()
                .all()
            )
            assert [(row['COLUMN_NAME'], row['COLLATION']) for row in rows] == parts
            assert all(
                row['NON_UNIQUE'] == 1
                and row['SUB_PART'] is None
                and row['IS_VISIBLE'] == 'YES'
                and row['INDEX_TYPE'] == 'BTREE'
                for row in rows
            )
        index = next(
            index for index in Base.metadata.tables[table].indexes if index.name == NAMES[table]
        )
        ddl = str(CreateIndex(index).compile(dialect=dialect()))
        assert (
            ', '.join(name + (' DESC' if direction == 'D' else '') for name, direction in parts)
            in ddl
        )
        assert not index.unique
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'ddl',
    [
        'CREATE INDEX IX_WORD_DICT_DELETED_ID ON word(english)',
        'CREATE INDEX IX_USER_DELETED_RATING_ID ON user(rating)',
        'CREATE INDEX ix_word_dict_deleted_id ON word(dictid, deleted, id)',
        'CREATE INDEX ix_user_deleted_rating_id ON user(deleted, rating DESC, id)',
        'ALTER TABLE word ENGINE=MyISAM',
        'ALTER TABLE word MODIFY dictid BIGINT',
        'ALTER TABLE word MODIFY deleted VARCHAR(10)',
        'ALTER TABLE word MODIFY id INT UNSIGNED NOT NULL AUTO_INCREMENT',
        'ALTER TABLE word MODIFY id INT NOT NULL, DROP PRIMARY KEY',
        'ALTER TABLE user MODIFY rating BIGINT',
        'ALTER TABLE user MODIFY deleted INT',
    ],
)
def test_upgrade_preflights_both_tables_before_any_ddl(legacy_database, migrate_database, ddl):
    migrate_database(legacy_database, PREVIOUS)
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
            before = snapshot(conn)
            indexes = {table: index_names(conn, table) for table in NAMES}
        with pytest.raises(RuntimeError):
            migrate_database(legacy_database)
        with engine.connect() as conn:
            assert snapshot(conn) == before and version(conn) == PREVIOUS
            assert {table: index_names(conn, table) for table in NAMES} == indexes
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'ddl',
    [
        'DROP INDEX ix_word_dict_deleted_id ON word',
        'ALTER TABLE word DROP INDEX ix_word_dict_deleted_id, ADD INDEX ix_word_dict_deleted_id (deleted,dictid,id)',
        'ALTER TABLE user DROP INDEX ix_user_deleted_rating_id, ADD INDEX ix_user_deleted_rating_id (deleted,rating,id)',
        'ALTER TABLE user ALTER INDEX ix_user_deleted_rating_id INVISIBLE',
        'ALTER TABLE word DROP INDEX ix_word_dict_deleted_id, ADD UNIQUE INDEX ix_word_dict_deleted_id (dictid,deleted,id)',
        'CREATE TABLE custom_child (dictid INT, deleted BOOLEAN, word_id INT, FOREIGN KEY (dictid,deleted,word_id) REFERENCES word(dictid,deleted,id)) ENGINE=InnoDB',
        'ALTER TABLE word DROP INDEX ix_word_dict_deleted_id, ADD INDEX ix_word_dict_deleted_id ((ABS(dictid)))',
        (
            'CREATE TABLE custom_parent (id INT PRIMARY KEY) ENGINE=InnoDB',
            'INSERT INTO custom_parent VALUES (1)',
            'ALTER TABLE word ADD CONSTRAINT custom_word_fk FOREIGN KEY (dictid) REFERENCES custom_parent(id)',
        ),
    ],
)
def test_downgrade_refuses_missing_custom_or_referenced_indexes_before_any_drop(
    legacy_database, migrate_database, ddl
):
    migrate_database(legacy_database, HEAD)
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            for statement in (ddl,) if isinstance(ddl, str) else ddl:
                conn.execute(text(statement))
            indexes = {table: index_names(conn, table) for table in NAMES}
        with pytest.raises(RuntimeError):
            migrate(legacy_database, downgrade=True)
        with engine.connect() as conn:
            assert version(conn) == HEAD
            assert {table: index_names(conn, table) for table in NAMES} == indexes
    finally:
        engine.dispose()


@pytest.mark.parametrize('downgrade', [False, True])
def test_second_ddl_failure_is_partial_and_retry_is_rejected_without_business_changes(
    legacy_database, migrate_database, downgrade
):
    migrate_database(legacy_database, HEAD if downgrade else PREVIOUS)
    engine = create_engine(legacy_database['url'])
    try:
        with engine.connect() as conn:
            before = snapshot(conn)
        statement = 'ALTER TABLE `word` DROP INDEX' if downgrade else 'ALTER TABLE `user` ADD INDEX'
        with pytest.raises(RuntimeError, match='injected DDL failure'):
            migrate(legacy_database, downgrade=downgrade, fail_on=statement)
        with engine.connect() as conn:
            assert snapshot(conn) == before
            assert version(conn) == (HEAD if downgrade else PREVIOUS)
            assert NAMES['word'] in index_names(conn, 'word')
            assert NAMES['user'] not in index_names(conn, 'user')
        with pytest.raises(RuntimeError):
            migrate(legacy_database, downgrade=downgrade)
        with engine.connect() as conn:
            assert snapshot(conn) == before
    finally:
        engine.dispose()


def test_metadata_lock_timeout_keeps_partial_ddl_visible_and_rejects_retry(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, PREVIOUS)
    engine = create_engine(legacy_database['url'])
    try:
        with engine.connect() as blocker:
            with blocker.begin():
                blocker.execute(text('SELECT id FROM user WHERE id = 1'))
                with pytest.raises(OperationalError) as error:
                    migrate(legacy_database, lock_wait=1)
                assert error.value.orig.args[0] == 1205
        with engine.connect() as conn:
            assert version(conn) == PREVIOUS
            assert NAMES['word'] in index_names(conn, 'word')
            assert NAMES['user'] not in index_names(conn, 'user')
        with pytest.raises(RuntimeError, match='Partial/custom'):
            migrate(legacy_database)
    finally:
        engine.dispose()


def test_empty_database_can_upgrade_to_new_head(legacy_database, migrate_database):
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            for table in ('game', 'word', 'dict', 'user'):
                conn.execute(text(f'DROP TABLE `{table}`'))
        migrate_database(legacy_database)
        with engine.connect() as conn:
            assert version(conn) == '0012_manual_rating'
            assert all(not rows for rows in snapshot(conn).values())
        assert (
            create_app(legacy_database['config']).test_client().get('/health/ready').status_code
            == 200
        )
    finally:
        engine.dispose()
