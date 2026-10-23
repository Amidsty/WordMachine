import json
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text

from wm_app import create_app, socketio
from wm_app.services import game, game_requests

from .test_game_mysql import execute, parallel, query, rating_history

pytestmark = pytest.mark.mysql


def metadata(version=0):
    return {'request_id': str(uuid4()), 'expected_version': version}


def test_http_socket_replay_returns_original_receipt_after_later_turn(mysql_app, mysql_login):
    client, csrf = mysql_login(1)
    command = {'word_id': 11, 'answer': 'APPLE', **metadata()}
    first = client.post('/api/game/1/answer', json=command)
    assert first.status_code == 200 and first.json['version'] == 1
    second, _ = mysql_login(2)
    assert (
        second.post(
            '/api/game/1/answer', json={'word_id': 22, 'answer': 'banana', **metadata(1)}
        ).json['version']
        == 2
    )
    socket = socketio.test_client(mysql_app, flask_test_client=client, auth={'csrf_token': csrf})
    try:
        socket.emit('game.subscribe', {'game_id': 1, 'csrf_token': csrf})
        socket.get_received()
        socket.emit('game.answer', {**command, 'game_id': 1, 'csrf_token': csrf})
        events = socket.get_received()
        assert (
            next(event['args'][0] for event in events if event['name'] == 'game.answer_result')
            == first.json
        )
        assert (
            next(event['args'][0] for event in events if event['name'] == 'game.update')['version']
            == 2
        )
    finally:
        socket.disconnect()
    assert (
        len(json.loads(query(mysql_app, 'SELECT result FROM game WHERE id = 1')[0]['result'])) == 2
    )
    # The receipt survives a newly constructed app/connection, not an in-memory cache.
    restarted = create_app(dict(mysql_app.config))
    with restarted.app_context():
        replay = game.answer_game(
            1, 1, 11, ' apple ', **{key: command[key] for key in ('request_id', 'expected_version')}
        )
    assert {'success': True, **replay} == first.json


@pytest.mark.parametrize(
    'change',
    [
        {'answer': 'wrong'},
        {'word_id': 22},
        {'expected_version': 1},
    ],
)
def test_same_key_with_changed_effective_payload_is_a_conflict(mysql_app, mysql_login, change):
    client, _ = mysql_login()
    command = {'word_id': 11, 'answer': 'apple', **metadata()}
    assert client.post('/api/game/1/answer', json=command).status_code == 200
    conflict = client.post('/api/game/1/answer', json={**command, **change})
    assert conflict.status_code == 409 and conflict.json['code'] == 'request_id_conflict'
    for path in ('/api/game/999/answer', '/api/game/1/end'):
        assert client.post(path, json=command).json['code'] == 'request_id_conflict'
    assert query(mysql_app, 'SELECT version FROM game WHERE id = 1')[0]['version'] == 1
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 1


def test_request_scope_is_actor_not_session_and_revocation_still_applies(mysql_app, mysql_login):
    first, _ = mysql_login(1)
    command = {'word_id': 11, 'answer': 'apple', **metadata()}
    result = first.post('/api/game/1/answer', json=command)
    fresh, _ = mysql_login(1)
    assert fresh.post('/api/game/1/answer', json=command).json == result.json
    other, _ = mysql_login(2)
    assert (
        other.post(
            '/api/game/1/answer',
            json={**command, 'word_id': 22, 'answer': 'banana', 'expected_version': 1},
        ).status_code
        == 200
    )
    admin, _ = mysql_login(3)
    assert admin.post('/api/admin/user/1/delete', json={}).status_code == 200
    assert fresh.post('/api/game/1/answer', json=command).status_code == 401
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 2


def test_concurrent_create_duplicates_only_create_one_game(mysql_app):
    rid = str(uuid4())
    replies = parallel(
        mysql_app, *[lambda: game.create_game(1, 1, request_id=rid) for _ in range(4)]
    )
    assert all(reply == replies[0] for reply in replies)
    assert isinstance(replies[0], dict) and replies[0]['version'] == 0
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game')[0]['n'] == 2  # Plus the seeded game.
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 1


def test_concurrent_answer_duplicates_score_and_advance_only_once(mysql_app):
    command = metadata()
    replies = parallel(
        mysql_app, *[lambda: game.answer_game(1, 1, 11, 'apple', **command) for _ in range(4)]
    )
    assert isinstance(replies[0], dict) and all(reply == replies[0] for reply in replies)
    row = query(mysql_app, 'SELECT version, result FROM game WHERE id = 1')[0]
    assert row['version'] == 1 and len(json.loads(row['result'])) == 1
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 1


def test_distinct_commands_with_same_expected_version_do_not_overwrite(mysql_app):
    execute(mysql_app, "UPDATE game SET status = -1, users = '[1]' WHERE id = 1")
    replies = parallel(
        mysql_app,
        lambda: game.join_game(1, 2, **metadata()),
        lambda: game.join_game(1, 3, **metadata()),
    )
    assert sum(isinstance(reply, dict) for reply in replies) == 1
    assert 'stale_game_version' in replies
    row = query(mysql_app, 'SELECT version, users FROM game WHERE id = 1')[0]
    assert row['version'] == 1 and len(json.loads(row['users'])) == 2
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 1


def test_receipts_do_not_invert_cross_game_user_locks(mysql_app):
    answers = json.dumps([{'uid': 1, 'word_id': 11, 'result': True, 'perf': 1600}])
    execute(mysql_app, 'UPDATE game SET result = %s WHERE id = 1', (answers,))
    execute(
        mysql_app,
        "INSERT INTO game (id, ownerid, dictid, users, wordlist, result, status) VALUES (2, 1, 1, '[1, 2]', '[11, 22, 33]', %s, 0)",
        (answers,),
    )
    replies = parallel(
        mysql_app,
        lambda: game.end_game(1, 1, **metadata()),
        lambda: game.end_game(2, 1, **metadata()),
    )
    assert all(isinstance(reply, dict) and reply['version'] == 1 for reply in replies)
    assert len(rating_history(mysql_app, 1)) == 2
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 2


def test_receipt_failure_rolls_back_answer_rating_and_version_then_same_key_can_retry(
    mysql_app, monkeypatch
):
    execute(mysql_app, "UPDATE game SET wordlist = '[11]' WHERE id = 1")
    complete = game_requests.complete

    def fail(*args):
        complete(*args)
        raise RuntimeError('failure after receipt write')

    command = metadata()
    monkeypatch.setattr(game_requests, 'complete', fail)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        game.answer_game(1, 1, 11, 'apple', **command)
    assert query(mysql_app, 'SELECT status, version, result FROM game WHERE id = 1')[0] == {
        'status': 0,
        'version': 0,
        'result': '[]',
    }
    assert query(mysql_app, 'SELECT rating, ratinghistory, gamehistory FROM user WHERE id = 1')[
        0
    ] == {'rating': 1500, 'ratinghistory': None, 'gamehistory': None}
    assert not query(mysql_app, 'SELECT * FROM game_request')
    monkeypatch.setattr(game_requests, 'complete', complete)
    with mysql_app.app_context():
        first = game.answer_game(1, 1, 11, 'apple', **command)
        assert first['status'] == game.FINISHED and first['version'] == 1
        assert game.answer_game(1, 1, 11, 'apple', **command) == first
    assert len(rating_history(mysql_app, 1)) == 1


def test_lobby_command_receipts_replay_without_reapplying_old_membership(mysql_app):
    with mysql_app.app_context():
        created = game.create_game(1, 1, request_id=str(uuid4()))
        gid = created['game_id']
        join = metadata()
        original = game.join_game(gid, 2, **join)
        assert original['version'] == 1
        assert game.leave_game(gid, 2, **metadata(1))['version'] == 2
        assert game.join_game(gid, 2, **join) == original
        state = game.get_game_state(gid)
        assert [user['id'] for user in state['users']] == [1] and state['version'] == 2
        cancel = metadata(2)
        cancelled = game.cancel_game(gid, 1, **cancel)
        assert cancelled['version'] == 3 and game.cancel_game(gid, 1, **cancel) == cancelled


def test_start_and_end_receipts_and_noop_end_versions(mysql_app):
    execute(mysql_app, 'UPDATE game SET status = -1 WHERE id = 1')
    with mysql_app.app_context():
        start = metadata()
        started = game.start_game(1, 1, **start)
        end = metadata(1)
        finished = game.end_game(1, 1, **end)
        assert finished['version'] == 2 and not finished['already_finished']
        assert game.start_game(1, 1, **start) == started
        assert game.end_game(1, 1, **end) == finished
        noop = game.end_game(1, 1, **metadata(2))
        assert noop['version'] == 2 and noop['already_finished']
    with pytest.raises(pymysql.OperationalError) as error:
        execute(mysql_app, 'UPDATE game SET version = -1 WHERE id = 1')
    assert (
        error.value.args[0] == 3819
    )  # MySQL CHECK violation; PyMySQL classifies it as OperationalError.


def test_metadata_migration_preserves_all_legacy_business_values(legacy_database, migrate_database):
    migrate_database(legacy_database, '0002_sessions_dict')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            # Even malformed legacy JSON is not repaired by this metadata-only revision.
            conn.execute(
                text("UPDATE game SET result = 'broken-json', perf = :perf, ratingdelta = :delta"),
                {'perf': '{"1": 1600}', 'delta': '{"1": 37}'},
            )
            conn.execute(
                text('UPDATE user SET rating = 1537, ratinghistory = :history WHERE id = 1'),
                {'history': '[{"game_id":1,"delta":37,"new_rating":1537}]'},
            )
            before = {
                table: [
                    dict(row)
                    for row in conn.execute(text(f'SELECT * FROM `{table}` ORDER BY id')).mappings()
                ]
                for table in ('user', 'dict', 'word', 'game')
            }
        migrate_database(legacy_database, '0003_game_requests')
        with engine.connect() as conn:
            for table, expected in before.items():
                actual = [
                    dict(row)
                    for row in conn.execute(text(f'SELECT * FROM `{table}` ORDER BY id')).mappings()
                ]
                if table == 'game':
                    assert all(row.pop('version') == 0 for row in actual)
                assert actual == expected
            assert conn.execute(text('SELECT COUNT(*) FROM game_request')).scalar_one() == 0
    finally:
        engine.dispose()


def test_version_exhaustion_never_commits_partial_answers_or_receipts(mysql_app):
    execute(mysql_app, 'UPDATE game SET version = %s WHERE id = 1', (game_requests.MAX_VERSION,))
    from wm_app.services.errors import GameError

    with mysql_app.app_context(), pytest.raises(GameError, match='exhausted'):
        game.answer_game(1, 1, 11, 'apple', **metadata(game_requests.MAX_VERSION))
    assert query(mysql_app, 'SELECT result, version FROM game WHERE id = 1')[0] == {
        'result': '[]',
        'version': game_requests.MAX_VERSION,
    }
    assert query(mysql_app, 'SELECT gamehistory FROM user WHERE id = 1')[0]['gamehistory'] is None
    assert not query(mysql_app, 'SELECT * FROM game_request')


@pytest.mark.parametrize(
    'custom_ddl',
    [
        'ALTER TABLE game ADD COLUMN version INT NOT NULL DEFAULT 0',
        'CREATE TABLE game_request (id INT PRIMARY KEY) ENGINE=InnoDB',
        'ALTER TABLE game MODIFY id BIGINT NOT NULL AUTO_INCREMENT',
        'ALTER TABLE game ENGINE=MyISAM',
    ],
)
def test_request_migration_preflight_stops_before_new_ddl(
    legacy_database, migrate_database, custom_ddl
):
    migrate_database(legacy_database, '0002_sessions_dict')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(text(custom_ddl))
        tables = set(inspect(engine).get_table_names())
        columns = {column['name'] for column in inspect(engine).get_columns('game')}
        with pytest.raises(RuntimeError):
            migrate_database(legacy_database)
        assert set(inspect(engine).get_table_names()) == tables
        assert {column['name'] for column in inspect(engine).get_columns('game')} == columns
        with engine.connect() as conn:
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0002_sessions_dict'
            )
    finally:
        engine.dispose()
