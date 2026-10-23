import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text

from wm_app import socketio
from wm_app.db import transaction
from wm_app.services import dictionary, game, game_questions, game_requests, lobby
from wm_app.services.errors import GameError
from wm_app.services.pagination import ListQuery

from .test_game_mysql import execute, parallel, query, rating_history

pytestmark = pytest.mark.mysql


def command(version=None):
    data = {'request_id': str(uuid4())}
    if version is not None:
        data['expected_version'] = version
    return data


def test_snapshot_http_socket_flow_survives_source_edit_and_deletion(
    mysql_app, mysql_login, monkeypatch
):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    monkeypatch.setattr('wm_app.services.rating.random.randint', lambda low, high: low)
    # This test audits the snapshot independently of a deliberately orphaned legacy seed.
    execute(mysql_app, 'DELETE FROM game WHERE id = 1')
    first, _ = mysql_login(1)
    second, csrf = mysql_login(2)
    admin, _ = mysql_login(3)
    creation = {'dict_id': 1, **command()}
    created = first.post('/api/game/create', json=creation)
    assert created.status_code == 201
    gid = created.json['game_id']
    path = f'/api/game/{gid}'
    waiting = first.get(path).json['game']
    assert waiting['question_source'] == 'snapshot' and waiting['version'] == 0
    assert waiting['words'] == [
        {'id': 11, 'chinese': '苹果'},
        {'id': 22, 'chinese': '香蕉'},
        {'id': 33, 'chinese': '猫'},
    ]
    assert second.post(path + '/join', json=command(0)).status_code == 200
    assert admin.put('/api/dict/1', json={'dictname': 'renamed'}).status_code == 200
    assert (
        admin.put('/api/word/11', json={'english': 'changed', 'chinese': '改变'}).status_code == 200
    )
    assert (
        admin.post('/api/dict/1/word', json={'english': 'extra', 'chinese': '额外'}).status_code
        == 201
    )
    assert admin.delete('/api/word/22', json={}).status_code == 200
    assert admin.delete('/api/dict/1', json={}).status_code == 200
    assert (
        first.post('/api/game/create', json=creation).json == created.json
    )  # No recapture on replay.
    assert first.post(path + '/start', json=command(1)).json['version'] == 2
    running = first.get(path).json['game']
    assert running['words'] == waiting['words'] and running['dictname'] == 'test dictionary'
    answer = first.post(path + '/answer', json={'word_id': 11, 'answer': 'APPLE', **command(2)})
    assert (
        answer.json['correct']
        and answer.json['expected'] == 'apple'
        and answer.json['perf'] == 1511
    )
    assert answer.json['next_word'] == {'id': 22, 'chinese': '香蕉'}
    socket = socketio.test_client(mysql_app, flask_test_client=second, auth={'csrf_token': csrf})
    try:
        socket.emit('game.subscribe', {'game_id': gid, 'csrf_token': csrf})
        socket.get_received()
        socket.emit(
            'game.answer',
            {'game_id': gid, 'csrf_token': csrf, 'word_id': 22, 'answer': 'banana', **command(3)},
        )
        events = socket.get_received()
        receipt = next(
            event['args'][0] for event in events if event['name'] == 'game.answer_result'
        )
        update = next(event['args'][0] for event in events if event['name'] == 'game.update')
        assert receipt['correct'] and receipt['expected'] == 'banana' and receipt['version'] == 4
        assert update['question_source'] == 'snapshot'
        assert (
            update['words'][0]['english'] == 'apple' and update['words'][1]['english'] == 'banana'
        )
        assert 'english' not in update['words'][2] and 'english' not in update['next_word']
    finally:
        socket.disconnect()
    # Direct physical removal is a test-only operation, not an application delete endpoint.
    execute(mysql_app, 'DELETE FROM word WHERE dictid = 1')
    execute(mysql_app, 'DELETE FROM dict WHERE id = 1')
    last = {'word_id': 33, 'answer': 'cat', **command(4)}
    finished = first.post(path + '/answer', json=last)
    assert finished.json['status'] == game.FINISHED and finished.json['version'] == 5
    assert first.post(path + '/answer', json=last).json == finished.json
    history = first.get(path).json['game']
    assert [word['english'] for word in history['words']] == ['apple', 'banana', 'cat']
    assert history['dictname'] == 'test dictionary' and history['total_words'] == 3
    for uid in (1, 2):
        assert len(rating_history(mysql_app, uid)) == 1
    with mysql_app.app_context():
        listing = lobby.list_games(1, ListQuery(q='test dictionary'))
        assert (
            listing['pagination']['total'] == 1
            and listing['games'][0]['dictname'] == 'test dictionary'
        )
        assert lobby.list_games(1, ListQuery(q='renamed'))['pagination']['total'] == 0
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 0, audit.output
    assert json.loads(audit.output)['issue_count'] == 0


def test_legacy_games_stay_explicitly_live_without_rewriting_history(mysql_app):
    with mysql_app.app_context():
        before = game.get_game_state(1)
        dictionary.update_word(3, 11, 'changed', '改变')
        after = game.get_game_state(1)
    assert before['question_source'] == after['question_source'] == 'legacy_live'
    assert (
        after['next_word'] == {'id': 11, 'chinese': '改变'}
        and after['version'] == before['version'] == 0
    )
    assert query(mysql_app, 'SELECT wordlist, result, question_mode, dictname_snapshot FROM game')[
        0
    ] == {'wordlist': '[11, 22, 33]', 'result': '[]', 'question_mode': 0, 'dictname_snapshot': None}
    assert not query(mysql_app, 'SELECT * FROM game_question')


def test_capture_is_one_consistent_view_and_stays_fixed_before_commit(mysql_app, monkeypatch):
    captured, release = Event(), Event()
    capture = game_questions.capture

    def pause_after_capture(*args):
        result = capture(*args)
        captured.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(game_questions, 'capture', pause_after_capture)

    def create():
        with mysql_app.app_context():
            return game.create_game(1, 1, **command())

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(create)
        try:
            assert captured.wait(10)
            with mysql_app.app_context(), transaction() as cursor:
                cursor.execute('SELECT @@transaction_isolation AS isolation_level')
                assert cursor.fetchone()['isolation_level'] == 'REPEATABLE-READ'
                cursor.execute("UPDATE dict SET dictname = 'new name' WHERE id = 1")
                cursor.execute(
                    "UPDATE word SET english = 'new text', chinese = '新题面' WHERE dictid = 1"
                )
        finally:
            release.set()
        gid = future.result(timeout=15)['game_id']
    assert {
        q['english']
        for q in query(mysql_app, 'SELECT english FROM game_question WHERE game_id = %s', (gid,))
    } == {'apple', 'banana', 'cat'}
    assert (
        query(mysql_app, 'SELECT dictname_snapshot FROM game WHERE id = %s', (gid,))[0][
            'dictname_snapshot'
        ]
        == 'test dictionary'
    )
    with mysql_app.app_context():
        later = game.create_game(1, 1, **command())['game_id']
    assert {
        q['english']
        for q in query(mysql_app, 'SELECT english FROM game_question WHERE game_id = %s', (later,))
    } == {'new text'}
    assert (
        query(mysql_app, 'SELECT dictname_snapshot FROM game WHERE id = %s', (later,))[0][
            'dictname_snapshot'
        ]
        == 'new name'
    )


def test_uncommitted_dictionary_transaction_is_never_captured(mysql_app):
    entered, release = Event(), Event()

    def edit():
        with mysql_app.app_context(), transaction() as cursor:
            cursor.execute("UPDATE dict SET dictname = 'uncommitted' WHERE id = 1")
            entered.set()
            assert release.wait(10)
            cursor.execute("UPDATE word SET english = 'committed together' WHERE id = 11")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(edit)
        try:
            assert entered.wait(10)
            with mysql_app.app_context():
                gid = game.create_game(1, 1, **command())['game_id']
        finally:
            release.set()
        future.result(timeout=15)
    assert (
        query(mysql_app, 'SELECT dictname_snapshot FROM game WHERE id = %s', (gid,))[0][
            'dictname_snapshot'
        ]
        == 'test dictionary'
    )
    assert (
        query(
            mysql_app,
            'SELECT english FROM game_question WHERE game_id = %s AND word_id = 11',
            (gid,),
        )[0]['english']
        == 'apple'
    )


@pytest.mark.parametrize('stage', ['questions', 'receipt'])
def test_failed_creation_rolls_back_parent_all_questions_and_request(mysql_app, monkeypatch, stage):
    module, name = (game_questions, 'save') if stage == 'questions' else (game_requests, 'complete')
    original = getattr(module, name)

    def fail(*args):
        original(*args)
        raise RuntimeError('injected creation failure')

    monkeypatch.setattr(module, name, fail)
    request = command()
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        game.create_game(1, 1, **request)
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game')[0]['n'] == 1
    assert not query(mysql_app, 'SELECT * FROM game_question')
    assert not query(mysql_app, 'SELECT * FROM game_request')
    monkeypatch.setattr(module, name, original)
    replies = parallel(mysql_app, *[lambda: game.create_game(1, 1, **request) for _ in range(4)])
    assert isinstance(replies[0], dict) and all(reply == replies[0] for reply in replies)
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_question')[0]['n'] == 3
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game_request')[0]['n'] == 1


@pytest.mark.parametrize(
    'sql',
    [
        'DELETE FROM game_question WHERE game_id = %s AND position = 1',
        "UPDATE game_question SET english = ' ' WHERE game_id = %s AND position = 1",
        'UPDATE game_question SET position = 9 WHERE game_id = %s AND position = 1',
    ],
)
def test_broken_snapshot_never_uses_live_source_or_partially_writes(mysql_app, mysql_login, sql):
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
    execute(mysql_app, sql, (gid,))  # Test-only corruption; no snapshot edit API exists.
    client, _ = mysql_login()
    assert client.get(f'/api/game/{gid}').json['code'] == 'invalid_game_snapshot'
    response = client.post(f'/api/game/{gid}/cancel', json=command(0))
    assert response.status_code == 409 and response.json['code'] == 'invalid_game_snapshot'
    assert query(mysql_app, 'SELECT status, version FROM game WHERE id = %s', (gid,))[0] == {
        'status': -1,
        'version': 0,
    }
    assert not query(mysql_app, 'SELECT * FROM game_request')
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1
    assert 'invalid_question_snapshot' in {
        issue['kind'] for issue in json.loads(audit.output)['issues']
    }
    assert 'apple' not in audit.output and 'banana' not in audit.output


def test_concurrent_snapshot_answers_and_end_keep_single_settlement(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
    request = command(2)
    replies = parallel(
        mysql_app, *[lambda: game.answer_game(gid, 1, 11, 'apple', **request) for _ in range(4)]
    )
    assert isinstance(replies[0], dict) and all(reply == replies[0] for reply in replies)
    assert replies[0]['version'] == 3
    race = parallel(
        mysql_app,
        lambda: game.answer_game(gid, 2, 22, 'banana', **command(3)),
        lambda: game.end_game(gid, 1, **command(3)),
    )
    assert sum(isinstance(reply, dict) for reply in race) == 1 and 'stale_game_version' in race
    with mysql_app.app_context():
        game.end_game(gid, 1, **command(4))
        state = game.get_game_state(gid)
    assert state['status'] == game.FINISHED
    assert len(rating_history(mysql_app, 1)) == 1
    assert len(rating_history(mysql_app, 2)) == len(state['result']) - 1


def test_snapshot_preserves_unicode_newlines_alternatives_and_missing_name(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    english, chinese = ' Apple/PEAR ', ' 多行\r\n含,引号" 🍎 '
    execute(mysql_app, 'UPDATE dict SET dictname = NULL WHERE id = 1')
    execute(
        mysql_app, 'UPDATE word SET english = %s, chinese = %s WHERE id = 11', (english, chinese)
    )
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
        dictionary.update_dictionary(3, 1, 'not the snapshot name')
        assert game.get_game_state(gid)['dictname'] is None
        assert (
            next(row for row in lobby.list_games(1)['games'] if row['id'] == gid)['dictname']
            is None
        )
        answer = game.answer_game(gid, 1, 11, 'pear')
        assert answer['correct'] and answer['expected'] == english
        assert game.get_game_state(gid)['words'][0] == {
            'id': 11,
            'english': english,
            'chinese': chinese,
        }


@pytest.mark.parametrize(
    'sql',
    [
        'UPDATE word SET english = NULL WHERE id = 11',
        "UPDATE word SET chinese = '' WHERE id = 11",
        'UPDATE word SET id = -11 WHERE id = 11',
    ],
)
def test_invalid_source_is_not_silently_cleaned_or_dropped(mysql_app, sql):
    execute(mysql_app, sql)
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        game.create_game(1, 1, **command())
    assert error.value.code == 'invalid_dictionary_data'
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM game')[0]['n'] == 1
    assert not query(mysql_app, 'SELECT * FROM game_question')
    assert not query(mysql_app, 'SELECT * FROM game_request')


def test_question_constraints_are_enforced_by_mysql(mysql_app):
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
    for position, wid, code in [(0, 44, 1062), (3, 11, 1062), (-1, 44, 3819), (3, 0, 3819)]:
        with pytest.raises(pymysql.MySQLError) as error:
            execute(
                mysql_app,
                "INSERT INTO game_question VALUES (%s, %s, %s, 'new', '新')",
                (gid, position, wid),
            )
        assert error.value.args[0] == code
    with pytest.raises(pymysql.IntegrityError) as error:
        execute(mysql_app, "INSERT INTO game_question VALUES (999, 0, 11, 'new', '新')")
    assert error.value.args[0] == 1452
    with pytest.raises(pymysql.OperationalError) as error:
        execute(mysql_app, 'UPDATE game SET question_mode = 2 WHERE id = %s', (gid,))
    assert error.value.args[0] == 3819


def test_migration_preserves_old_business_values_and_does_not_invent_snapshots(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, '0003_game_requests')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE game SET result = 'broken-json', version = 17, perf = :perf, ratingdelta = :delta"
                ),
                {'perf': '{"1":1600}', 'delta': '{"1":37}'},
            )
            conn.execute(
                text(
                    "INSERT INTO game_request VALUES (1, :rid, 'end', :digest, 1, :response, NOW())"
                ),
                {
                    'rid': str(uuid4()),
                    'digest': '0' * 64,
                    'response': '{"version":17,"perf":{"1":1600}}',
                },
            )
            before = {
                table: [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                for table in ('user', 'dict', 'word', 'game', 'game_request')
            }
        migrate_database(legacy_database, '0004_game_questions')
        with engine.connect() as conn:
            for table, expected in before.items():
                actual = [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                if table == 'game':
                    assert all(
                        row.pop('question_mode') == 0 and row.pop('dictname_snapshot') is None
                        for row in actual
                    )
                assert actual == expected
            assert conn.execute(text('SELECT COUNT(*) FROM game_question')).scalar_one() == 0
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0004_game_questions'
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'ddl',
    [
        'ALTER TABLE game ADD COLUMN question_mode INT',
        'ALTER TABLE game ADD COLUMN dictname_snapshot VARCHAR(255)',
        'CREATE TABLE game_question (id INT PRIMARY KEY) ENGINE=InnoDB',
        'ALTER TABLE game ADD CONSTRAINT ck_game_question_mode CHECK (version >= 0)',
        'ALTER TABLE word ENGINE=MyISAM',
    ],
)
def test_snapshot_migration_preflight_precedes_all_ddl(legacy_database, migrate_database, ddl):
    migrate_database(legacy_database, '0003_game_requests')
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
                == '0003_game_requests'
            )
    finally:
        engine.dispose()
