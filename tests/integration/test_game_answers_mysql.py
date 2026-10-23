import json
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text

from wm_app import create_app, socketio
from wm_app.services import game, game_answers, game_requests
from wm_app.services.errors import GameError
from wm_app.services.rating import rating_delta

from .test_game_mysql import execute, parallel, query, rating_history

pytestmark = pytest.mark.mysql


def command(version=None):
    return {
        'request_id': str(uuid4()),
        **({'expected_version': version} if version is not None else {}),
    }


def recorded(app, gid):
    return query(app, 'SELECT * FROM game_answer WHERE game_id = %s ORDER BY position', (gid,))


@pytest.fixture
def started_game(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
    return gid


def test_http_socket_answers_keep_binary64_scores_protocol_and_original_receipt(
    mysql_app, mysql_login, started_game, monkeypatch
):
    gid = started_game
    monkeypatch.setattr('wm_app.services.rating.random.randint', lambda low, high: low)
    execute(mysql_app, 'UPDATE user SET rating = 1433 WHERE id = 1')
    owner, csrf = mysql_login(1)
    other, _ = mysql_login(2)
    path = f'/api/game/{gid}'
    first_command = {'word_id': 11, 'answer': ' APPLE ', **command(2)}
    first = owner.post(path + '/answer', json=first_command)
    assert first.status_code == 200 and first.json['version'] == 3
    first_row = recorded(mysql_app, gid)[0]
    assert (
        first_row['perf_delta'].hex() == (1500 / 1433 * 11).hex() == first.json['perf_delta'].hex()
    )
    assert first_row['perf'].hex() == first.json['perf'].hex()
    assert first_row['answered_at'] == first_row['recorded_at']
    assert first_row['answer'] == 'apple' and first_row['rating_version'] == 'dict-perf-v1'
    assert (
        other.post(
            path + '/answer', json={'word_id': 22, 'answer': 'banana', **command(3)}
        ).status_code
        == 200
    )
    socket = socketio.test_client(mysql_app, flask_test_client=owner, auth={'csrf_token': csrf})
    try:
        socket.emit('game.subscribe', {'game_id': gid, 'csrf_token': csrf})
        socket.get_received()
        socket.emit('game.answer', {**first_command, 'game_id': gid, 'csrf_token': csrf})
        events = socket.get_received()
        assert (
            next(event['args'][0] for event in events if event['name'] == 'game.answer_result')
            == first.json
        )
        assert (
            next(event['args'][0] for event in events if event['name'] == 'game.update')['version']
            == 4
        )
        socket.emit(
            'game.answer',
            {'word_id': 33, 'answer': 'wrong', 'game_id': gid, 'csrf_token': csrf, **command(4)},
        )
        last = next(
            event['args'][0]
            for event in socket.get_received()
            if event['name'] == 'game.answer_result'
        )
        assert last['status'] == game.FINISHED and last['version'] == 5
        # Wrong answers reset to the rating baseline, not the previous Perf.
        assert last['perf'] == 1500 - 1 / (1500 / 1433)
        assert last['globalcombo'] == last['usercombo'] == 0
    finally:
        socket.disconnect()
    assert recorded(mysql_app, gid)[0] == first_row
    state = owner.get(path).json['game']
    assert [entry['uid'] for entry in state['result']] == [1, 2, 1]
    assert all(type(entry['result']) is bool for entry in state['result'])
    assert all(
        set(entry)
        == {
            'uid',
            'word_id',
            'answer',
            'result',
            'usercombo',
            'globalcombo',
            'perf_delta',
            'raw_perf_delta',
            'perf',
            'rating_version',
        }
        for entry in state['result']
    )
    assert query(
        mysql_app, 'SELECT result, answer_mode, answer_count FROM game WHERE id = %s', (gid,)
    )[0] == {'result': None, 'answer_mode': 1, 'answer_count': 3}
    restarted = create_app(dict(mysql_app.config))
    with restarted.app_context():
        assert {
            'success': True,
            **game.answer_game(
                gid,
                1,
                11,
                'apple',
                **{key: first_command[key] for key in ('request_id', 'expected_version')},
            ),
        } == first.json
    assert len(recorded(mysql_app, gid)) == 3
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_relation_not_archived_json_controls_turns_scoring_and_answer_visibility(
    mysql_app, started_game
):
    gid = started_game
    execute(
        mysql_app,
        'UPDATE game SET result = %s WHERE id = %s',
        ('broken archived JSON with future answers', gid),
    )
    with mysql_app.app_context():
        assert game.get_game_state(gid)['result'] == []
        game.answer_game(gid, 1, 11, 'apple')
        game.end_game(gid, 2)
        state = game.get_game_state(gid)
    assert len(state['result']) == 1 and 'english' in state['words'][0]
    assert all('english' not in word for word in state['words'][1:])
    assert (
        query(mysql_app, 'SELECT result FROM game WHERE id = %s', (gid,))[0]['result']
        == 'broken archived JSON with future answers'
    )
    assert (
        query(mysql_app, 'SELECT ratinghistory FROM user WHERE id = 2')[0]['ratinghistory'] is None
    )
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_answer_prefix_can_exceed_legacy_result_text_capacity(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    for wid in range(100, 127):
        execute(
            mysql_app,
            'INSERT INTO word (id, dictid, english, chinese, deleted) VALUES (%s, 1, %s, %s, 0)',
            (wid, 'example', '例子'),
        )
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
        words = game.get_game_state(gid)['words']
        for index, word in enumerate(words):
            result = game.answer_game(gid, index % 2 + 1, word['id'], '🍎' * 255)
        assert result['status'] == game.FINISHED
        state = game.get_game_state(gid)
    assert len(json.dumps(state['result']).encode('utf-8')) > 65535
    assert len(recorded(mysql_app, gid)) == len(words) == state['current_index'] == 30
    assert query(mysql_app, 'SELECT result FROM game WHERE id = %s', (gid,))[0]['result'] is None


def test_new_answer_text_handles_unicode_lowercase_expansion(mysql_app, started_game):
    value = 'İ' * 255  # lower() expands each character; VARCHAR(255) would truncate/fail.
    with mysql_app.app_context():
        game.answer_game(started_game, 1, 11, value)
        assert game.get_game_state(started_game)['result'][0]['answer'] == value.lower()
    assert recorded(mysql_app, started_game)[0]['answer'] == value.lower()


@pytest.mark.parametrize('point', ['append', 'settle', 'receipt'])
def test_final_answer_failure_rolls_back_row_count_settlement_version_and_receipt(
    mysql_app, monkeypatch, point
):
    execute(mysql_app, 'DELETE FROM word WHERE id IN (22, 33)')
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
    module, name = {
        'append': (game_answers, 'append'),
        'settle': (game, '_settle'),
        'receipt': (game_requests, 'complete'),
    }[point]
    original = getattr(module, name)

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected after ' + point)

    monkeypatch.setattr(module, name, fail)
    request = command(2)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        game.answer_game(gid, 1, 11, 'apple', **request)
    assert not recorded(mysql_app, gid) and not query(mysql_app, 'SELECT * FROM game_request')
    assert query(
        mysql_app, 'SELECT status, version, answer_count, result FROM game WHERE id = %s', (gid,)
    )[0] == {'status': 0, 'version': 2, 'answer_count': 0, 'result': None}
    assert query(mysql_app, 'SELECT rating, gamehistory, ratinghistory FROM user WHERE id = 1')[
        0
    ] == {'rating': 1500, 'gamehistory': None, 'ratinghistory': None}
    monkeypatch.setattr(module, name, original)
    with mysql_app.app_context():
        first = game.answer_game(gid, 1, 11, 'apple', **request)
        assert first['status'] == game.FINISHED and first['version'] == 3
        assert game.answer_game(gid, 1, 11, 'apple', **request) == first
    assert len(recorded(mysql_app, gid)) == 1
    assert len(rating_history(mysql_app, 1)) == 1


@pytest.mark.parametrize('with_id', [False, True])
def test_concurrent_same_turn_inserts_once_with_or_without_request_id(
    mysql_app, started_game, with_id
):
    request = command(2) if with_id else {}
    replies = parallel(
        mysql_app,
        *[lambda: game.answer_game(started_game, 1, 11, 'apple', **request) for _ in range(4)],
    )
    if with_id:
        assert isinstance(replies[0], dict) and all(reply == replies[0] for reply in replies)
    else:
        assert sum(isinstance(reply, dict) for reply in replies) == 1
    assert len(recorded(mysql_app, started_game)) == 1
    assert query(
        mysql_app, 'SELECT answer_count, version FROM game WHERE id = %s', (started_game,)
    )[0] == {'answer_count': 1, 'version': 3}


def test_answer_end_race_and_duplicate_end_keep_single_settlement(mysql_app, started_game):
    gid = started_game
    replies = parallel(
        mysql_app,
        lambda: game.answer_game(gid, 1, 11, 'apple', **command(2)),
        lambda: game.end_game(gid, 2, **command(2)),
    )
    assert (
        sum(isinstance(reply, dict) for reply in replies) == 1 and 'stale_game_version' in replies
    )
    parallel(mysql_app, lambda: game.end_game(gid, 1), lambda: game.end_game(gid, 2))
    rows = recorded(mysql_app, gid)
    user = query(mysql_app, 'SELECT rating, ratinghistory FROM user WHERE id = 1')[0]
    if rows:
        assert user['rating'] == 1500 + rating_delta(1500, rows[0]['perf'])
        assert len(rating_history(mysql_app, 1)) == 1
    else:
        assert user == {'rating': 1500, 'ratinghistory': None}
    assert (
        query(mysql_app, 'SELECT ratinghistory FROM user WHERE id = 2')[0]['ratinghistory'] is None
    )


def test_cross_game_final_answers_with_reversed_participants_preserve_both_rating_updates(
    mysql_app, started_game
):
    gid = started_game
    with mysql_app.app_context():
        other = game.create_game(2, 1)['game_id']
        game.join_game(other, 1)  # [2, 1], opposite turn order; always ascending user locks.
        game.start_game(other, 2)
        for game_id, first, second in ((gid, 1, 2), (other, 2, 1)):
            game.answer_game(game_id, first, 11, 'apple')
            game.answer_game(game_id, second, 22, 'banana')
    replies = parallel(
        mysql_app,
        lambda: game.answer_game(gid, 1, 33, 'cat', **command(4)),
        lambda: game.answer_game(other, 2, 33, 'cat', **command(4)),
    )
    assert all(isinstance(reply, dict) and reply['status'] == game.FINISHED for reply in replies)
    for game_id in (gid, other):
        assert len(recorded(mysql_app, game_id)) == 3
    for user in query(mysql_app, 'SELECT id, rating, ratinghistory FROM user WHERE id IN (1, 2)'):
        assert user['ratinghistory'] is None
        history = rating_history(mysql_app, user['id'])
        assert len(history) == 2 and user['rating'] == 1500 + sum(
            entry['delta'] for entry in history
        )
        assert {entry['game_id'] for entry in history} == {gid, other}


@pytest.mark.parametrize(
    'sql',
    [
        'DELETE FROM game_answer WHERE game_id = %s',
        'UPDATE game_answer SET position = 1 WHERE game_id = %s',
        'UPDATE game_answer SET user_id = 2 WHERE game_id = %s',
        "UPDATE game_answer SET rating_version = 'unknown' WHERE game_id = %s",
        "UPDATE game_answer SET answer = '' WHERE game_id = %s",
        'UPDATE game SET answer_count = 0 WHERE id = %s',
        'UPDATE game SET status = -1 WHERE id = %s',
    ],
)
def test_corrupt_relations_fail_closed_without_json_fallback_or_new_writes(
    mysql_app, mysql_login, started_game, sql
):
    gid = started_game
    request = command(2)
    with mysql_app.app_context():
        receipt = game.answer_game(gid, 1, 11, 'private answer', **request)
    execute(mysql_app, sql, (gid,))
    before = recorded(mysql_app, gid)
    owner, _ = mysql_login()
    for response in (
        owner.get(f'/api/game/{gid}'),
        owner.post(f'/api/game/{gid}/end', json=command(3)),
    ):
        assert response.status_code == 409 and response.json['code'] == 'invalid_game_answers'
    assert recorded(mysql_app, gid) == before
    assert query(mysql_app, 'SELECT version FROM game WHERE id = %s', (gid,))[0]['version'] == 3
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 1
    with mysql_app.app_context():
        assert (
            game.answer_game(gid, 1, 11, 'private answer', **request) == receipt
        )  # A receipt is not repaired state.
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1 and 'invalid_game_answers' in {
        item['kind'] for item in json.loads(audit.output)['issues']
    }
    assert 'private answer' not in audit.output


def test_answer_unique_fk_check_constraints_and_metadata_checks(mysql_app, started_game):
    gid = started_game
    with mysql_app.app_context():
        game.answer_game(gid, 1, 11, 'apple')
    for sql, code in [
        ('INSERT INTO game_answer SELECT * FROM game_answer WHERE game_id = %s', 1062),
        ('UPDATE game_answer SET user_id = 3 WHERE game_id = %s', 1452),
        ('UPDATE game_answer SET position = 99 WHERE game_id = %s', 1452),
        ('UPDATE game_answer SET game_id = 999 WHERE game_id = %s', 1452),
        ('UPDATE game_answer SET correct = 2 WHERE game_id = %s', 3819),
        ('UPDATE game_answer SET usercombo = -1 WHERE game_id = %s', 3819),
        ('UPDATE game_answer SET globalcombo = -1 WHERE game_id = %s', 3819),
        ('DELETE FROM game_participant WHERE game_id = %s AND user_id = 1', 1451),
        ('DELETE FROM game_question WHERE game_id = %s AND position = 0', 1451),
        ('UPDATE game SET answer_count = NULL WHERE id = %s', 3819),
        ('UPDATE game SET answer_count = -1 WHERE id = %s', 3819),
        ('UPDATE game SET answer_mode = 0 WHERE id = %s', 3819),
        ('UPDATE game SET answer_mode = 2 WHERE id = %s', 3819),
        ('UPDATE game SET question_mode = 0 WHERE id = %s', 3819),
        ('UPDATE game SET participant_mode = 0, participant_count = NULL WHERE id = %s', 3819),
    ]:
        with pytest.raises(pymysql.MySQLError) as error:
            execute(mysql_app, sql, (gid,))
        assert error.value.args[0] == code, (sql, error.value)
    assert len(recorded(mysql_app, gid)) == 1
    assert {
        row['Column_name']
        for row in query(
            mysql_app, 'SHOW INDEX FROM game_answer WHERE Key_name = %s', ('ix_answer_participant',)
        )
    } == {'game_id', 'user_id', 'position'}


def test_legacy_answers_are_not_converted_and_remain_usable(mysql_app, started_game):
    with mysql_app.app_context():
        game.answer_game(1, 1, 11, 'apple')
        game.answer_game(started_game, 1, 11, 'apple')
    legacy = query(mysql_app, 'SELECT result, answer_mode, answer_count FROM game WHERE id = 1')[0]
    assert (
        legacy['answer_mode'] == 0
        and legacy['answer_count'] is None
        and len(json.loads(legacy['result'])) == 1
    )
    assert not recorded(mysql_app, 1) and len(recorded(mysql_app, started_game)) == 1
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_answer_version_exhaustion_rolls_back_relation_and_user_history(mysql_app, started_game):
    execute(
        mysql_app,
        'UPDATE game SET version = %s WHERE id = %s',
        (game_requests.MAX_VERSION, started_game),
    )
    with mysql_app.app_context(), pytest.raises(GameError, match='exhausted'):
        game.answer_game(started_game, 1, 11, 'apple', **command(game_requests.MAX_VERSION))
    assert not recorded(mysql_app, started_game) and not query(
        mysql_app, 'SELECT * FROM game_request'
    )
    assert query(mysql_app, 'SELECT gamehistory FROM user WHERE id = 1')[0]['gamehistory'] is None
    assert (
        query(mysql_app, 'SELECT answer_count FROM game WHERE id = %s', (started_game,))[0][
            'answer_count'
        ]
        == 0
    )


def test_answer_migration_preserves_old_values_snapshots_members_and_receipts(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, '0005_game_participants')
    application = create_app(legacy_database['config'])
    assert application.test_client().get('/health/ready').status_code == 503
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE game SET result = 'broken-json', version = 17, question_mode = 1, participant_mode = 1, participant_count = 2, perf = :perf, ratingdelta = :delta"
                ),
                {'perf': '{"1": 1600.25}', 'delta': '{"1": 37}'},
            )
            conn.execute(
                text(
                    'INSERT INTO game_question SELECT 1, ROW_NUMBER() OVER (ORDER BY id) - 1, id, english, chinese FROM word'
                )
            )
            conn.execute(
                text(
                    'INSERT INTO game_participant VALUES (1, 1, 0, NULL, UTC_TIMESTAMP(6)), (1, 2, 1, NULL, UTC_TIMESTAMP(6))'
                )
            )
            conn.execute(
                text(
                    "INSERT INTO game_request (actor_id, request_id, action, payload_hash, game_id, response, created_at) VALUES (1, :rid, 'end', :digest, 1, :response, UTC_TIMESTAMP())"
                ),
                {'rid': str(uuid4()), 'digest': 'a' * 64, 'response': '{"version":17}'},
            )
            tables = (
                'user',
                'dict',
                'word',
                'game',
                'game_question',
                'game_participant',
                'game_request',
            )
            before = {
                table: [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                for table in tables
            }
        migrate_database(legacy_database, '0006_game_answers')
        assert (
            application.test_client().get('/health/ready').status_code == 503
        )  # Explicit 0006 is no longer head.
        with engine.connect() as conn:
            for table, expected in before.items():
                actual = [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                if table == 'game':
                    assert all(
                        row.pop('answer_mode') == 0 and row.pop('answer_count') is None
                        for row in actual
                    )
                assert actual == expected
            assert conn.execute(text('SELECT COUNT(*) FROM game_answer')).scalar_one() == 0
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0006_game_answers'
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'custom_ddl',
    [
        'ALTER TABLE game ADD COLUMN Answer_Mode INT NOT NULL DEFAULT 0',
        'CREATE TABLE game_answer (id INT PRIMARY KEY) ENGINE=InnoDB',
        'ALTER TABLE game ADD CONSTRAINT CK_GAME_ANSWERS CHECK (version >= 0)',
        'CREATE TABLE unrelated (id INT, CONSTRAINT CK_ANSWER_COMBOS CHECK (id > 0)) ENGINE=InnoDB',
        'ALTER TABLE game MODIFY result TEXT NOT NULL',
        'ALTER TABLE game_question MODIFY position MEDIUMINT NOT NULL',
        'ALTER TABLE game_participant DROP PRIMARY KEY, ADD PRIMARY KEY (user_id, game_id)',
    ],
)
def test_answer_preflight_rejects_partial_custom_structure_before_any_ddl(
    legacy_database, migrate_database, custom_ddl
):
    migrate_database(legacy_database, '0005_game_participants')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(text(custom_ddl))
        tables = set(inspect(engine).get_table_names())
        columns = {column['name'] for column in inspect(engine).get_columns('game')}
        with pytest.raises(RuntimeError):
            migrate_database(legacy_database, '0006_game_answers')
        assert set(inspect(engine).get_table_names()) == tables
        assert {column['name'] for column in inspect(engine).get_columns('game')} == columns
        with engine.connect() as conn:
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0005_game_participants'
            )
    finally:
        engine.dispose()
