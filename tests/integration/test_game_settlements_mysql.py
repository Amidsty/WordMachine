import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text

from wm_app import create_app, socketio
from wm_app.db import transaction
from wm_app.services import game, game_requests, game_settlements
from wm_app.services.errors import GameError
from wm_app.services.rating import rating_delta

from .test_game_mysql import execute, parallel, query, rating_history

pytestmark = pytest.mark.mysql


def command(version=None):
    return {
        'request_id': str(uuid4()),
        **({'expected_version': version} if version is not None else {}),
    }


def ledger(app, gid):
    return query(app, 'SELECT * FROM game_rating WHERE game_id = %s ORDER BY user_id', (gid,))


def header(app, gid):
    return query(app, 'SELECT * FROM game_settlement WHERE game_id = %s', (gid,))


@pytest.fixture
def running(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
    return gid


def test_http_socket_settlement_ledger_and_original_receipts_survive_app_restart(
    mysql_app, mysql_login, running
):
    gid = running
    first, csrf = mysql_login(1)
    path = f'/api/game/{gid}'
    answer = first.post(path + '/answer', json={'word_id': 11, 'answer': 'apple', **command(2)})
    assert answer.status_code == 200
    finish = command(3)
    socket = socketio.test_client(mysql_app, flask_test_client=first, auth={'csrf_token': csrf})
    try:
        original = socket.emit(
            'game.end', {'game_id': gid, 'csrf_token': csrf, **finish}, callback=True
        )
        assert original['success'] and not original['already_finished'] and original['version'] == 4
        assert first.post(path + '/end', json=finish).json == original
    finally:
        socket.disconnect()
    rows, metadata = ledger(mysql_app, gid), header(mysql_app, gid)
    assert len(rows) == metadata[0]['rated_count'] == 1
    row = rows[0]
    assert row['user_id'] == 1 and row['rating_before'] == 1500
    assert row['perf'].hex() == answer.json['perf'].hex()
    assert row['delta'] == rating_delta(1500, row['perf'])
    assert row['rating_after'] == 1500 + row['delta']
    assert metadata[0]['rating_version'] == 'legacy-v1'
    assert metadata[0]['settled_at'] == metadata[0]['recorded_at']
    assert query(
        mysql_app, 'SELECT perf, ratingdelta, settlement_mode FROM game WHERE id = %s', (gid,)
    )[0] == {'perf': None, 'ratingdelta': None, 'settlement_mode': 1}
    assert (
        query(mysql_app, 'SELECT ratinghistory FROM user WHERE id = 1')[0]['ratinghistory'] is None
    )
    assert query(mysql_app, 'SELECT rating FROM user WHERE id = 2')[0]['rating'] == 1500
    state = first.get(path).json['game']
    assert state['userrating'] == [
        {
            'user_id': 1,
            'ratinghistory': [
                {'game_id': gid, 'delta': row['delta'], 'new_rating': row['rating_after']}
            ],
        },
        {'user_id': 2, 'ratinghistory': []},
    ]
    assert all('english' not in word for word in state['words'][1:])
    restarted = create_app(dict(mysql_app.config))
    with restarted.app_context():
        assert {'success': True, **game.end_game(gid, 1, **finish)} == original
        assert game.end_game(gid, 1, **command(4))['already_finished'] is True
    assert ledger(mysql_app, gid) == rows and header(mysql_app, gid) == metadata
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_zero_answers_has_one_empty_settlement_and_no_user_changes(mysql_app, running):
    before = query(mysql_app, 'SELECT * FROM user ORDER BY id')
    request = command(2)
    replies = parallel(mysql_app, *[lambda: game.end_game(running, 1, **request) for _ in range(4)])
    assert isinstance(replies[0], dict) and all(reply == replies[0] for reply in replies)
    assert replies[0]['perf'] == {} and not replies[0]['already_finished']
    assert (
        len(header(mysql_app, running)) == 1 and header(mysql_app, running)[0]['rated_count'] == 0
    )
    assert not ledger(mysql_app, running)
    assert query(mysql_app, 'SELECT * FROM user ORDER BY id') == before
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_old_finished_data_is_not_converted_but_future_old_and_new_games_share_ledger(
    mysql_app, running
):
    archive = '[ {"game_id":90,"delta":0,"new_rating":1500,"extra":"keep"} ]'
    execute(
        mysql_app,
        "INSERT INTO game (id,ownerid,dictid,users,wordlist,result,status,perf,ratingdelta) VALUES (90,1,1,'[1,2]','[11]','[]',1,'{}','{}')",
    )
    execute(mysql_app, 'UPDATE user SET ratinghistory = %s WHERE id = 1', (archive,))
    before = query(mysql_app, 'SELECT * FROM game WHERE id = 90')
    with mysql_app.app_context():
        assert game.end_game(90, 1)['already_finished']
        game.answer_game(running, 1, 11, 'apple')
        game.end_game(running, 1)
        game.answer_game(1, 1, 11, 'apple')  # Upgrade-era running game still uses JSON answers.
        game.end_game(1, 2)
        state = game.get_game_state(1)
    assert query(mysql_app, 'SELECT * FROM game WHERE id = 90') == before
    assert not header(mysql_app, 90)
    assert (
        query(mysql_app, 'SELECT ratinghistory FROM user WHERE id = 1')[0]['ratinghistory']
        == archive
    )
    assert [entry['game_id'] for entry in state['userrating'][0]['ratinghistory']] == [
        90,
        running,
        1,
    ]
    old = query(
        mysql_app,
        'SELECT settlement_mode, answer_mode, participant_mode, question_mode, perf, ratingdelta FROM game WHERE id = 1',
    )[0]
    assert old == {
        'settlement_mode': 1,
        'answer_mode': 0,
        'participant_mode': 0,
        'question_mode': 0,
        'perf': None,
        'ratingdelta': None,
    }
    first, second = ledger(mysql_app, running)[0], ledger(mysql_app, 1)[0]
    assert second['rating_before'] == first['rating_after'] and second['id'] > first['id']
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_zero_delta_still_records_answered_user_once(mysql_app):
    execute(
        mysql_app,
        'UPDATE game SET result = %s WHERE id = 1',
        (json.dumps([{'uid': 1, 'word_id': 11, 'perf': 1500}]),),
    )
    with mysql_app.app_context():
        game.end_game(1, 1)
    assert ledger(mysql_app, 1)[0]['delta'] == 0
    assert header(mysql_app, 1)[0]['rated_count'] == 1
    assert rating_history(mysql_app, 1) == [{'game_id': 1, 'delta': 0, 'new_rating': 1500}]
    assert not rating_history(mysql_app, 2)


@pytest.mark.parametrize(
    'point',
    [
        'INSERT INTO game_settlement',
        'INSERT INTO game_rating',
        'INSERT INTO rating_event',
        'UPDATE user SET rating =',
        'UPDATE game SET status = 1',
        'UPDATE game_request SET game_id',
    ],
)
def test_failure_at_each_settlement_write_rolls_back_final_answer_balances_and_receipt(
    mysql_app, running, monkeypatch, point
):
    gid = running
    with mysql_app.app_context():
        game.answer_game(gid, 1, 11, 'apple')
        game.answer_game(gid, 2, 22, 'banana')
    users = query(mysql_app, 'SELECT * FROM user ORDER BY id')
    answers = query(
        mysql_app, 'SELECT * FROM game_answer WHERE game_id = %s ORDER BY position', (gid,)
    )
    original = pymysql.cursors.Cursor.execute

    def fail(cursor, sql, args=None):
        result = original(cursor, sql, args)
        if sql.startswith(point):
            raise RuntimeError('injected settlement write failure')
        return result

    monkeypatch.setattr(pymysql.cursors.Cursor, 'execute', fail)
    request = command(4)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        game.answer_game(gid, 1, 33, 'cat', **request)
    assert query(mysql_app, 'SELECT * FROM user ORDER BY id') == users
    assert (
        query(mysql_app, 'SELECT * FROM game_answer WHERE game_id = %s ORDER BY position', (gid,))
        == answers
    )
    assert query(mysql_app, 'SELECT status, version, answer_count FROM game WHERE id = %s', (gid,))[
        0
    ] == {'status': 0, 'version': 4, 'answer_count': 2}
    assert (
        not header(mysql_app, gid)
        and not ledger(mysql_app, gid)
        and not query(mysql_app, 'SELECT * FROM rating_event')
        and not query(mysql_app, 'SELECT * FROM game_request')
    )
    monkeypatch.setattr(pymysql.cursors.Cursor, 'execute', original)
    with mysql_app.app_context():
        result = game.answer_game(gid, 1, 33, 'cat', **request)
        assert result['version'] == 5 and result['status'] == game.FINISHED
        assert game.answer_game(gid, 1, 33, 'cat', **request) == result
    assert len(ledger(mysql_app, gid)) == 2


def test_waiting_user_lock_uses_latest_committed_ledger_not_earlier_mvcc_view(
    mysql_app, running, monkeypatch
):
    gid = running
    with mysql_app.app_context():
        game.answer_game(gid, 1, 11, 'apple')
        game.answer_game(1, 1, 11, 'apple')
    holding, attempted = Event(), Event()
    original = game._lock_users

    def observed(cursor, ids):
        attempted.set()  # _decode_game has already established a repeatable-read view for gid.
        return original(cursor, ids)

    def first_settlement():
        with mysql_app.app_context(), transaction() as cursor:
            current = game._locked_game(cursor, 1)
            users = original(cursor, current['users'])
            holding.set()
            assert attempted.wait(10)
            game._settle(cursor, current, users)

    def second_settlement():
        assert holding.wait(10)
        with mysql_app.app_context():
            return game.end_game(gid, 2)

    monkeypatch.setattr(game, '_lock_users', observed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(first_settlement), pool.submit(second_settlement)
        one.result(20)
        assert not two.result(20)['already_finished']
    first, second = ledger(mysql_app, 1)[0], ledger(mysql_app, gid)[0]
    assert second['rating_before'] == first['rating_after']
    assert [entry['game_id'] for entry in rating_history(mysql_app, 1)] == [1, gid]


def test_state_history_and_balance_share_one_read_snapshot_during_other_game_settlement(
    mysql_app, running, monkeypatch
):
    with mysql_app.app_context():
        game.answer_game(1, 1, 11, 'apple')
    paused, committed = Event(), Event()
    original = game_settlements.histories

    def pause(cursor, users):
        paused.set()
        assert committed.wait(10)
        return original(cursor, users)

    monkeypatch.setattr(game_settlements, 'histories', pause)

    def read_state():
        with mysql_app.app_context():
            return game.get_game_state(running)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(read_state)
        assert paused.wait(10)
        try:
            with mysql_app.app_context():
                game.end_game(1, 1)
        finally:
            committed.set()
        state = pending.result(20)
    assert all(not entry['ratinghistory'] for entry in state['userrating'])
    monkeypatch.setattr(game_settlements, 'histories', original)
    with mysql_app.app_context():
        fresh = game.get_game_state(running)
    assert fresh['version'] == state['version']  # Other games do not advance this game's version.
    assert fresh['userrating'][0]['ratinghistory'][0]['game_id'] == 1


def test_disjoint_users_first_settlements_do_not_deadlock_on_empty_ledger_ranges(
    mysql_app, running, monkeypatch
):
    execute(
        mysql_app,
        "INSERT INTO user (id, username, rating, type, deleted) VALUES (4, 'four', 1500, 'normal', 0)",
    )
    with mysql_app.app_context():
        other = game.create_game(3, 1)['game_id']
        game.join_game(other, 4)
        game.start_game(other, 3)
        game.answer_game(running, 1, 11, 'apple')
        game.answer_game(other, 3, 11, 'apple')
    barrier = Barrier(2)
    original = pymysql.cursors.Cursor.execute

    def overlap(cursor, sql, args=None):
        if sql.startswith('INSERT INTO game_rating'):
            barrier.wait(10)
        return original(cursor, sql, args)

    monkeypatch.setattr(pymysql.cursors.Cursor, 'execute', overlap)
    replies = parallel(
        mysql_app, lambda: game.end_game(running, 1), lambda: game.end_game(other, 3)
    )
    assert all(isinstance(reply, dict) and not reply['already_finished'] for reply in replies)
    assert len(ledger(mysql_app, running)) == len(ledger(mysql_app, other)) == 1
    for uid in (1, 3):
        assert len(rating_history(mysql_app, uid)) == 1


def test_answer_end_competition_and_concurrent_end_never_duplicate_ledger(mysql_app, running):
    gid = running
    with mysql_app.app_context():
        game.answer_game(gid, 1, 11, 'apple')
        game.answer_game(gid, 2, 22, 'banana')
    results = parallel(
        mysql_app,
        lambda: game.answer_game(gid, 1, 33, 'cat', **command(4)),
        lambda: game.end_game(gid, 2, **command(4)),
    )
    assert (
        sum(isinstance(result, dict) for result in results) == 1 and 'stale_game_version' in results
    )
    before = ledger(mysql_app, gid)
    results = parallel(mysql_app, lambda: game.end_game(gid, 1), lambda: game.end_game(gid, 2))
    assert all(result['already_finished'] for result in results)
    assert ledger(mysql_app, gid) == before and len(before) == 2


@pytest.mark.parametrize(
    'sql',
    [
        'UPDATE game_settlement SET rated_count = 2 WHERE game_id = %s',
        'UPDATE game_rating SET user_id = 3 WHERE game_id = %s',
        'UPDATE game_rating SET perf = perf + 1 WHERE game_id = %s',
        'UPDATE game_settlement SET rated_count = 0 WHERE game_id = %s',
        "UPDATE game_settlement SET rating_version = 'unknown' WHERE game_id = %s",
        'UPDATE game SET status = 0 WHERE id = %s',
    ],
)
def test_corruption_is_rejected_not_repaired_or_reapplied(mysql_app, running, mysql_login, sql):
    with mysql_app.app_context():
        game.answer_game(running, 1, 11, 'private submission')
        request = command(3)
        receipt = game.end_game(running, 1, **request)
    execute(mysql_app, sql, (running,))
    users = query(mysql_app, 'SELECT * FROM user ORDER BY id')
    client, _ = mysql_login(1)
    for response in (
        client.get(f'/api/game/{running}'),
        client.post(f'/api/game/{running}/end', json=command(4)),
    ):
        assert response.status_code == 409 and response.json['code'] == 'invalid_game_settlement'
    assert query(mysql_app, 'SELECT rating FROM user ORDER BY id') == [
        {'rating': user['rating']} for user in users
    ]
    with mysql_app.app_context():
        assert game.end_game(running, 1, **request) == receipt
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1 and 'invalid_game_settlement' in {
        item['kind'] for item in json.loads(audit.output)['issues']
    }
    assert 'private submission' not in audit.output


def test_current_balance_tampering_blocks_new_settlement_without_overwriting_it(mysql_app, running):
    with mysql_app.app_context():
        game.answer_game(running, 1, 11, 'apple')
        game.end_game(running, 1)
        game.answer_game(1, 1, 11, 'apple')
    execute(mysql_app, 'UPDATE user SET rating = rating + 7 WHERE id = 1')
    before = query(mysql_app, 'SELECT rating FROM user ORDER BY id')
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        game.end_game(1, 1, **command(1))
    assert error.value.code == 'invalid_game_settlement'
    assert query(mysql_app, 'SELECT rating FROM user ORDER BY id') == before
    assert not header(mysql_app, 1) and not ledger(mysql_app, 1)
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1 and 'invalid_rating_history' in {
        item['kind'] for item in json.loads(audit.output)['issues']
    }


def test_already_settled_legacy_hint_is_not_automatically_recomputed(mysql_app):
    execute(mysql_app, 'UPDATE game SET result = %s WHERE id = 1', ('[{"uid":1,"perf":1600}]',))
    execute(
        mysql_app,
        'UPDATE user SET ratinghistory = %s WHERE id = 1',
        ('[{"game_id":1,"delta":77,"new_rating":1577}]',),
    )
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        game.end_game(1, 1)
    assert error.value.code == 'legacy_data_error'
    assert not header(mysql_app, 1) and not ledger(mysql_app, 1)


def test_rating_range_and_version_exhaustion_roll_back_settlement(mysql_app, running):
    execute(mysql_app, 'UPDATE game SET result = %s WHERE id = 1', ('[{"uid":1,"perf":1e100}]',))
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        game.end_game(1, 1, **command(0))
    assert error.value.code == 'rating_out_of_range'
    execute(
        mysql_app,
        'UPDATE game SET version = %s WHERE id = %s',
        (game_requests.MAX_VERSION, running),
    )
    with mysql_app.app_context(), pytest.raises(GameError, match='exhausted'):
        game.end_game(running, 1, **command(game_requests.MAX_VERSION))
    assert not query(mysql_app, 'SELECT * FROM game_settlement') and not query(
        mysql_app, 'SELECT * FROM game_rating'
    )
    assert not query(mysql_app, 'SELECT * FROM game_request')


def test_database_settlement_uniqueness_foreign_keys_and_arithmetic(mysql_app, running):
    with mysql_app.app_context():
        game.answer_game(running, 1, 11, 'apple')
        game.end_game(running, 1)
    for sql, code in [
        ('INSERT INTO game_settlement SELECT * FROM game_settlement WHERE game_id = %s', 1062),
        (
            'INSERT INTO game_rating (game_id,user_id,perf,rating_before,delta,rating_after) SELECT game_id,user_id,perf,rating_before,delta,rating_after FROM game_rating WHERE game_id = %s',
            1062,
        ),
        ('UPDATE game_rating SET user_id = 999 WHERE game_id = %s', 1452),
        ('UPDATE game_rating SET game_id = 999 WHERE game_id = %s', 1452),
        ('UPDATE game_rating SET delta = delta + 1 WHERE game_id = %s', 3819),
        ('UPDATE game_settlement SET rated_count = -1 WHERE game_id = %s', 3819),
        ('UPDATE game SET settlement_mode = 2 WHERE id = %s', 3819),
        ('DELETE FROM game_rating WHERE game_id = %s', 1451),
        ('DELETE FROM game_settlement WHERE game_id = %s', 1451),
        ('DELETE FROM game WHERE id = %s', 1451),
    ]:
        with pytest.raises(pymysql.MySQLError) as error:
            execute(mysql_app, sql, (running,))
        assert error.value.args[0] == code, (sql, error.value)
    assert {
        row['Column_name']
        for row in query(
            mysql_app, "SHOW INDEX FROM game_rating WHERE Key_name = 'ix_rating_user_id'"
        )
    } == {'user_id', 'id'}


def test_settlement_migration_preserves_all_existing_data_and_requires_new_readiness(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, '0006_game_answers')
    application = create_app(legacy_database['config'])
    assert application.test_client().get('/health/ready').status_code == 503
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    'UPDATE game SET status = 1, version = 17, perf = :perf, ratingdelta = :delta'
                ),
                {'perf': '{"1":1600.1234}', 'delta': '{"1":77}'},
            )
            conn.execute(
                text(
                    'UPDATE game SET question_mode = 1, participant_mode = 1, participant_count = 2, answer_mode = 1, answer_count = 1'
                )
            )
            conn.execute(
                text(
                    'INSERT INTO game_question SELECT 1, ROW_NUMBER() OVER (ORDER BY id) - 1, id, english, chinese FROM word'
                )
            )
            conn.execute(
                text(
                    'INSERT INTO game_participant VALUES (1,1,0,NULL,UTC_TIMESTAMP(6)), (1,2,1,NULL,UTC_TIMESTAMP(6))'
                )
            )
            conn.execute(
                text(
                    "INSERT INTO game_answer VALUES (1,0,1,'apple',1,1,1,100.1234,1600.1234,'legacy-v1',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
                )
            )
            conn.execute(
                text('UPDATE user SET rating = 1577, ratinghistory = :history WHERE id = 1'),
                {'history': '[ {"game_id":1,"delta":77,"new_rating":1577} ]'},
            )
            conn.execute(
                text(
                    "INSERT INTO game_request (actor_id,request_id,action,payload_hash,game_id,response,created_at) VALUES (1,:rid,'end',:hash,1,:reply,UTC_TIMESTAMP())"
                ),
                {
                    'rid': str(uuid4()),
                    'hash': 'a' * 64,
                    'reply': '{"version":17,"already_finished":false}',
                },
            )
            tables = [
                table for table in inspect(conn).get_table_names() if table != 'alembic_version'
            ]
            before = {
                table: [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                for table in tables
            }
        migrate_database(legacy_database, '0007_game_settlements')
        with engine.connect() as conn:
            for table, expected in before.items():
                actual = [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                if table == 'game':
                    assert all(row.pop('settlement_mode') == 0 for row in actual)
                if table == 'user':
                    assert all(row.pop('rating_ledger_id') is None for row in actual)
                assert actual == expected
            assert conn.execute(text('SELECT COUNT(*) FROM game_settlement')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM game_rating')).scalar_one() == 0
        # This historical revision is no longer sufficient for the current release.
        assert application.test_client().get('/health/ready').status_code == 503
        migrate_database(legacy_database)
        assert application.test_client().get('/health/ready').json == {'status': 'ok'}
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'ddl',
    [
        'CREATE TABLE game_rating (id INT PRIMARY KEY) ENGINE=InnoDB',
        'CREATE TABLE game_settlement (id INT PRIMARY KEY) ENGINE=InnoDB',
        'ALTER TABLE game ADD COLUMN Settlement_Mode INT NOT NULL DEFAULT 0',
        'CREATE TABLE custom (id INT, CONSTRAINT CK_RATING_ARITHMETIC CHECK (id >= 0)) ENGINE=InnoDB',
        'CREATE TABLE custom (uid INT, CONSTRAINT fk_rating_user FOREIGN KEY (uid) REFERENCES user(id)) ENGINE=InnoDB',
        'ALTER TABLE user MODIFY rating BIGINT',
        'ALTER TABLE user ADD COLUMN Rating_Ledger_Id BIGINT',
        'CREATE INDEX IX_USER_RATING_LEDGER ON user(rating)',
    ],
)
def test_settlement_migration_preflights_before_any_ddl(legacy_database, migrate_database, ddl):
    migrate_database(legacy_database, '0006_game_answers')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
        tables = set(inspect(engine).get_table_names())
        columns = {column['name'] for column in inspect(engine).get_columns('game')}
        with pytest.raises(RuntimeError):
            migrate_database(legacy_database)
        assert set(inspect(engine).get_table_names()) == tables
        assert {column['name'] for column in inspect(engine).get_columns('game')} == columns
        with engine.connect() as conn:
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0006_game_answers'
            )
    finally:
        engine.dispose()
