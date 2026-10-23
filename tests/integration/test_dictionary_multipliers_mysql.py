from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, text

from wm_app import create_app, socketio
from wm_app.db import transaction
from wm_app.services import dictionary, game, rating
from wm_app.services.errors import ApiError, GameError

from .test_auth_dict_mysql import execute, query

pytestmark = pytest.mark.mysql


def body(value='2.00', version=0):
    return {'multiplier': value, 'expected_version': version, 'reason': 'reviewed difficulty'}


@pytest.mark.parametrize('level', range(6))
def test_system_dictionary_all_mutations_require_level_three(mysql_app, mysql_login, level):
    execute(
        mysql_app,
        'UPDATE user SET admin_level=%s, type=%s WHERE id=3',
        (level, 'root' if level else 'normal'),
    )
    client, _ = mysql_login(3)
    assert client.get('/api/dict/1').json['dict']['can_manage'] == (level >= 3)
    before = {
        table: query(mysql_app, f'SELECT * FROM {table}')
        for table in ('dict', 'word', 'dictionary_audit')
    }
    calls = [
        ('put', '/api/dict/1/multiplier', body()),
        ('put', '/api/dict/1', {'dictname': 'renamed'}),
        ('put', '/api/word/11', {'english': 'pear', 'chinese': '梨'}),
        ('post', '/api/dict/1/word', {'english': 'dog', 'chinese': '狗'}),
        ('post', '/api/dict/1/import-csv', {'csv': 'a,甲\nb,乙'}),
        ('delete', '/api/word/11', {}),
        ('delete', '/api/dict/1', {}),
    ]
    for method, path, data in calls:
        response = getattr(client, method)(path, json=data)
        assert response.status_code == (
            403 if level < 3 else 201 if path.endswith('/word') else 200
        ), response.json
    if level < 3:
        assert {table: query(mysql_app, f'SELECT * FROM {table}') for table in before} == before


def test_personal_owner_or_level_five_and_decimal_audit(mysql_app, mysql_login):
    owner, _ = mysql_login(1)
    created = owner.post('/api/dict', json={'dictname': 'Personal', 'multiplier': '1.25'})
    assert created.status_code == 201
    did = created.json['dict_id']
    assert owner.put(f'/api/dict/{did}/multiplier', json=body('2.50')).status_code == 200
    execute(mysql_app, "UPDATE user SET admin_level=4, type='root' WHERE id=3")
    admin, _ = mysql_login(3)
    assert admin.put(f'/api/dict/{did}/multiplier', json=body('3.00', 1)).status_code == 403
    execute(mysql_app, 'UPDATE user SET admin_level=5 WHERE id=3')
    assert admin.put(f'/api/dict/{did}/multiplier', json=body('3.00', 1)).status_code == 200
    result = owner.get(f'/api/dict/{did}').json['dict']
    assert result['multiplier'] == '3.00' and result['config_version'] == 2
    records = query(
        mysql_app, 'SELECT * FROM dictionary_audit WHERE dict_id=%s ORDER BY id', (did,)
    )
    assert len(records) == 3 and records[0]['multiplier_before'] is None
    assert records[-1]['actor_level'] == 5 and records[-1]['multiplier_before'] == Decimal('2.50')
    assert owner.post('/api/dict', json={'dictname': 'forged', 'ownerid': None}).status_code == 400
    assert (
        owner.put(f'/api/dict/{did}', json={'dictname': 'x', 'multiplier': '5.00'}).status_code
        == 400
    )


def test_validation_reason_csrf_and_rename_stale_version(mysql_app, mysql_login):
    admin, _ = mysql_login(3)
    before = query(mysql_app, 'SELECT * FROM dict')
    for value in [True, None, 2, 'NaN', '1e0', '0.09', '5.01', '1.001']:
        assert admin.put('/api/dict/1/multiplier', json=body(value)).status_code == 400
    assert admin.put('/api/dict/1/multiplier', json={**body(), 'reason': ''}).status_code == 400
    assert (
        admin.put(
            '/api/dict/1/multiplier', json=body(), headers={'X-CSRF-Token': 'wrong'}
        ).status_code
        == 403
    )
    assert query(mysql_app, 'SELECT * FROM dict') == before
    assert admin.put('/api/dict/1', json={'dictname': 'renamed'}).status_code == 200
    response = admin.put('/api/dict/1/multiplier', json=body())
    assert response.status_code == 409 and response.json['code'] == 'stale_dictionary_version'
    assert not query(mysql_app, 'SELECT * FROM dictionary_audit')


def test_config_competition_and_audit_failure_are_atomic(mysql_app, monkeypatch):
    barrier = Barrier(2)

    def change(value):
        with mysql_app.app_context():
            barrier.wait(timeout=5)
            try:
                dictionary.set_multiplier(3, 1, body(value))
                return 200
            except ApiError as error:
                return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, ['2.00', '3.00'])) == [200, 409]
    before = query(mysql_app, 'SELECT * FROM dict')

    def fail(*args):
        raise RuntimeError('injected audit failure')

    monkeypatch.setattr(dictionary, '_audit_multiplier', fail)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        dictionary.set_multiplier(3, 1, body('4.00', 1))
    assert query(mysql_app, 'SELECT * FROM dict') == before
    assert len(query(mysql_app, 'SELECT * FROM dictionary_audit')) == 1


def test_actor_demotion_between_http_and_write_is_rechecked(mysql_app, mysql_login, monkeypatch):
    actor, _ = mysql_login(3)
    original = dictionary.set_multiplier

    def demote(*args):
        execute(mysql_app, 'UPDATE user SET admin_level=2 WHERE id=3')
        return original(*args)

    monkeypatch.setattr(dictionary, 'set_multiplier', demote)
    assert actor.put('/api/dict/1/multiplier', json=body()).status_code == 403
    assert not query(mysql_app, 'SELECT * FROM dictionary_audit')


def test_snapshot_http_socket_scoring_and_receipt_keep_original_multiplier(
    mysql_app, mysql_login, monkeypatch
):
    monkeypatch.setattr(game.random, 'shuffle', lambda items: None)
    monkeypatch.setattr(rating.random, 'randint', lambda low, high: low)
    admin, _ = mysql_login(3)
    first, _ = mysql_login(1)
    second, csrf = mysql_login(2)
    assert admin.put('/api/dict/1/multiplier', json=body()).status_code == 200
    request = {'dict_id': 1, 'request_id': str(uuid4())}
    created = first.post('/api/game/create', json=request).json
    gid = created['game_id']
    assert admin.put('/api/dict/1/multiplier', json=body('0.50', 1)).status_code == 200
    assert first.post('/api/game/create', json=request).json == created
    with mysql_app.app_context():
        game.join_game(gid, 2)
        game.start_game(gid, 1)
    answer_id = str(uuid4())
    payload = {'word_id': 11, 'answer': 'apple', 'request_id': answer_id, 'expected_version': 2}
    answer = first.post(f'/api/game/{gid}/answer', json=payload).json
    assert answer['success'] and answer['perf_delta'] == answer['raw_perf_delta'] * 2
    assert answer['perf'] == 1500 + answer['perf_delta']
    assert first.post(f'/api/game/{gid}/answer', json=payload).json == answer
    connection = socketio.test_client(
        mysql_app, flask_test_client=second, auth={'csrf_token': csrf}
    )
    try:
        wrong = connection.emit(
            'game.answer',
            {
                'game_id': gid,
                'word_id': 22,
                'answer': 'wrong',
                'csrf_token': csrf,
                'request_id': str(uuid4()),
                'expected_version': 3,
            },
            callback=True,
        )
        assert wrong['success'] and wrong['perf_delta'] == wrong['raw_perf_delta'] * 2 < 0
        assert wrong['perf'] == 1500 + wrong['perf_delta']
    finally:
        connection.disconnect()
    finish = {'request_id': str(uuid4()), 'expected_version': 4}
    ended = first.post(f'/api/game/{gid}/end', json=finish)
    assert ended.status_code == 200
    assert first.post(f'/api/game/{gid}/end', json=finish).json == ended.json
    state = first.get(f'/api/game/{gid}').json['game']
    assert state['multiplier_snapshot'] == '2.00' and state['perf_rule_version'] == 'dict-perf-v1'
    sources = query(
        mysql_app, 'SELECT * FROM game_rating WHERE game_id=%s ORDER BY user_id', (gid,)
    )
    assert [row['delta'] for row in sources] == [
        rating.rating_delta(1500, answer['perf']),
        rating.rating_delta(1500, wrong['perf']),
    ]
    assert len(query(mysql_app, 'SELECT * FROM rating_event')) == 2
    assert all(
        row['rating_version'] == 'dict-perf-v1'
        for row in query(mysql_app, 'SELECT * FROM game_answer WHERE game_id=%s', (gid,))
    )
    assert (
        query(mysql_app, 'SELECT rating_version FROM game_settlement WHERE game_id=%s', (gid,))[0][
            'rating_version'
        ]
        == 'legacy-v1'
    )
    with mysql_app.app_context():
        newer = game.create_game(1, 1)['game_id']
        assert game.get_game_state(newer)['multiplier_snapshot'] == '0.50'
        assert game.get_game_state(1)['multiplier_snapshot'] is None
        legacy = game.answer_game(1, 1, 11, 'apple')
        assert legacy['rating_version'] == 'legacy-v1' and 'raw_perf_delta' not in legacy
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_capture_uses_one_mvcc_view_and_never_locks_dictionary_before_users(mysql_app, monkeypatch):
    original = pymysql.cursors.Cursor.execute
    captured = []

    def concurrent(cursor, sql, args=None):
        result = original(cursor, sql, args)
        if isinstance(sql, str) and sql.startswith('SELECT d.dictname, d.multiplier'):
            captured.append(sql)
            with transaction() as writer:
                writer.execute("UPDATE dict SET dictname='new name', multiplier=3.00 WHERE id=1")
                writer.execute("UPDATE word SET chinese='changed' WHERE id=11")
        return result

    monkeypatch.setattr(pymysql.cursors.Cursor, 'execute', concurrent)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        state = game.get_game_state(gid)
    assert len(captured) == 1 and 'FOR ' not in captured[0]
    assert state['dictname'] == 'test dictionary' and state['multiplier_snapshot'] == '1.00'
    assert next(row for row in state['words'] if row['id'] == 11)['chinese'] == '苹果'


def test_snapshot_and_raw_delta_corruption_fail_closed(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda items: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
        game.answer_game(gid, 1, 11, 'apple')
    execute(mysql_app, 'UPDATE game_answer SET raw_perf_delta=NULL WHERE game_id=%s', (gid,))
    with mysql_app.app_context(), pytest.raises(GameError):
        game.get_game_state(gid)
    with pytest.raises(pymysql.MySQLError) as error:
        execute(mysql_app, 'UPDATE game SET multiplier_snapshot=NULL WHERE id=%s', (gid,))
    assert error.value.args[0] == 3819


def test_migration_preserves_old_rows_without_fabricating_snapshots(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, '0010_rating_events')
    app = create_app(legacy_database['config'])
    before = {
        table: query(app, f'SELECT * FROM {table} ORDER BY 1')
        for table in ('dict', 'game', 'user', 'game_answer', 'rating_event')
    }
    migrate_database(legacy_database)
    for table, rows in before.items():
        after = query(app, f'SELECT * FROM {table} ORDER BY 1')
        for row in after:
            if table == 'dict':
                assert row.pop('multiplier') == Decimal('1.00') and row.pop('config_version') == 0
            if table == 'game':
                assert row.pop('perf_mode') == 0 and row.pop('multiplier_snapshot') is None
            if table == 'game_answer':
                assert row.pop('raw_perf_delta') is None
        assert after == rows
    assert not query(app, 'SELECT * FROM dictionary_audit')


@pytest.mark.parametrize('partial', ['column', 'unsigned_parent', 'constraint'])
def test_partial_multiplier_schema_is_not_adopted(legacy_database, migrate_database, partial):
    migrate_database(legacy_database, '0010_rating_events')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    {
                        'column': 'ALTER TABLE dict ADD COLUMN multiplier DECIMAL(5,2)',
                        'unsigned_parent': 'ALTER TABLE dict MODIFY id INT UNSIGNED NOT NULL AUTO_INCREMENT',
                        'constraint': 'ALTER TABLE dict ADD CONSTRAINT ck_dict_multiplier CHECK (deleted IS NULL OR deleted IN (0,1))',
                    }[partial]
                )
            )
        with pytest.raises(RuntimeError, match='Partial/custom|signed INT'):
            migrate_database(legacy_database)
        with engine.connect() as conn:
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0010_rating_events'
            )
    finally:
        engine.dispose()
