import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text

from wm_app import socketio
from wm_app.services import game, game_requests, lobby
from wm_app.services import game_participants as participants
from wm_app.services.errors import GameError
from wm_app.services.pagination import ListQuery
from wm_app.services.participant_conversion import convert_game

from .test_game_mysql import execute, parallel, query, rating_history

pytestmark = pytest.mark.mysql


def command(version=None):
    return {
        'request_id': str(uuid4()),
        **({'expected_version': version} if version is not None else {}),
    }


def members(app, gid):
    return query(app, 'SELECT * FROM game_participant WHERE game_id = %s ORDER BY position', (gid,))


def test_http_socket_membership_order_replay_and_complete_scoring(
    mysql_app, mysql_login, monkeypatch
):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: values.reverse())
    owner, _ = mysql_login(1)
    other, csrf = mysql_login(2)
    gid = owner.post('/api/game/create', json={'dict_id': 1, **command()}).json['game_id']
    path = f'/api/game/{gid}'
    assert query(
        mysql_app,
        'SELECT users, participant_mode, participant_count FROM game WHERE id = %s',
        (gid,),
    )[0] == {'users': None, 'participant_mode': 1, 'participant_count': 1}
    original_owner = members(mysql_app, gid)[0]
    join = command(0)
    socket = socketio.test_client(mysql_app, flask_test_client=other, auth={'csrf_token': csrf})
    try:
        socket.emit('game.join', {'game_id': gid, 'csrf_token': csrf, **join})
        assert [row['user_id'] for row in members(mysql_app, gid)] == [2, 1]
        assert other.post(path + '/leave', json=command(1)).status_code == 200
        assert (
            other.post(path + '/join', json=join).json['version'] == 1
        )  # Receipt, not current membership.
        assert [row['user_id'] for row in members(mysql_app, gid)] == [1]
        assert other.post(path + '/join', json=command(2)).status_code == 200
    finally:
        socket.disconnect()
    rows = members(mysql_app, gid)
    assert [row['position'] for row in rows] == [0, 1]
    assert rows[1]['joined_at'] == original_owner['joined_at']
    assert rows[1]['recorded_at'] == original_owner['recorded_at']
    assert owner.post(path + '/start', json=command(3)).status_code == 200
    state = owner.get(path).json['game']
    assert state['next_turn'] == 2
    answers = {11: 'apple', 22: 'banana', 33: 'cat'}
    while state['status'] == game.RUNNING:
        client = owner if state['next_turn'] == 1 else other
        word_id = state['next_word']['id']
        reply = client.post(
            path + '/answer',
            json={'word_id': word_id, 'answer': answers[word_id], **command(state['version'])},
        )
        assert reply.status_code == 200 and reply.json['correct']
        state = owner.get(path).json['game']
    assert state['status'] == game.FINISHED
    assert [answer['uid'] for answer in state['result']] == [2, 1, 2]
    assert members(mysql_app, gid) == rows  # Starting/answering/ending never rewrites membership.
    for uid in (1, 2):
        assert len(rating_history(mysql_app, uid)) == 1
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 0, audit.output


def test_concurrent_membership_and_start_version_race(mysql_app):
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
    joined = parallel(mysql_app, lambda: game.join_game(gid, 2), lambda: game.join_game(gid, 3))
    assert all(isinstance(reply, dict) for reply in joined)
    assert {row['user_id'] for row in members(mysql_app, gid)} == {1, 2, 3}
    assert [row['position'] for row in members(mysql_app, gid)] == [0, 1, 2]
    raced = parallel(
        mysql_app,
        lambda: game.start_game(gid, 1, **command(2)),
        lambda: game.leave_game(gid, 2, **command(2)),
    )
    assert sum(isinstance(reply, dict) for reply in raced) == 1 and 'stale_game_version' in raced
    with mysql_app.app_context():
        state = game.get_game_state(gid)
        if state['status'] == game.WAITING:
            game.start_game(gid, 1, **command(3))
        state = game.get_game_state(gid)
    assert state['status'] == game.RUNNING
    assert len(members(mysql_app, gid)) == len(state['users'])


def test_join_fk_locks_cannot_invert_another_games_rating_locks(mysql_app, monkeypatch):
    with mysql_app.app_context():
        gid = game.create_game(2, 1)['game_id']
        game.join_game(gid, 1)
    # Force turn order opposite to user-ID lock order.
    monkeypatch.setattr(game.random, 'shuffle', lambda values: values.sort(reverse=True))
    first_locked, reference_attempted = Event(), Event()
    original_users, original_references = game._lock_users, participants.lock_references
    original_membership = game._lock_membership_actor
    membership_order = []

    def pause_rating(cursor, ids):
        cursor.execute('SELECT id FROM user WHERE id = 1 FOR UPDATE')
        first_locked.set()
        assert reference_attempted.wait(10)
        return original_users(cursor, ids)

    class ReferenceCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def __getattr__(self, name):
            return getattr(self.cursor, name)

        def execute(self, sql, params):
            if params == (1,):
                reference_attempted.set()  # Before blocking on the first ordered user lock.
            if sql.startswith('SELECT id, deleted FROM user'):
                membership_order.append(params[0])
            return self.cursor.execute(sql, params)

    monkeypatch.setattr(game, '_lock_users', pause_rating)
    monkeypatch.setattr(
        game,
        '_lock_membership_actor',
        lambda cursor, ids, uid: original_membership(ReferenceCursor(cursor), ids, uid),
    )
    monkeypatch.setattr(
        participants,
        'lock_references',
        lambda cursor, ids: original_references(ReferenceCursor(cursor), ids),
    )

    def answer():
        with mysql_app.app_context():
            return game.answer_game(1, 1, 11, 'apple')

    def join():
        with mysql_app.app_context():
            return game.join_game(gid, 3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        scoring = pool.submit(answer)
        try:
            assert first_locked.wait(10)
            joining = pool.submit(join)
            assert scoring.result(timeout=20)['correct']
            assert joining.result(timeout=20)['version'] == 2
        finally:
            reference_attempted.set()
    assert membership_order == [1, 2, 3]
    assert {row['user_id'] for row in members(mysql_app, gid)} == {1, 2, 3}


def test_conversion_defaults_readonly_preserves_business_values_and_old_receipts(mysql_app):
    request = command(0)
    with mysql_app.app_context():
        receipt = game.answer_game(1, 1, 11, 'apple', **request)
    tables = ('game', 'user', 'dict', 'word', 'game_request')
    before = {table: query(mysql_app, f'SELECT * FROM `{table}`') for table in tables}
    runner = mysql_app.test_cli_runner()
    dry = runner.invoke(args=['convert-game-participants', '--game-id', '1'])
    assert dry.exit_code == 0
    assert json.loads(dry.output) == {
        'game_id': 1,
        'status': 'ready',
        'participants': 2,
        'version': 1,
    }
    assert {table: query(mysql_app, f'SELECT * FROM `{table}`') for table in tables} == before
    refused = runner.invoke(args=['convert-game-participants', '--game-id', '1', '--apply'])
    assert refused.exit_code == 1 and json.loads(refused.output)['code'] == 'invalid_parameters'
    applied = runner.invoke(
        args=['convert-game-participants', '--game-id', '1', '--apply', '--expected-version', '1']
    )
    assert applied.exit_code == 0 and json.loads(applied.output)['status'] == 'converted'
    current = query(mysql_app, 'SELECT * FROM game WHERE id = 1')[0]
    assert current == {
        **before['game'][0],
        'participant_mode': 1,
        'participant_count': 2,
        'version': 2,
    }
    for table in tables[1:]:
        assert query(mysql_app, f'SELECT * FROM `{table}`') == before[table]
    rows = members(mysql_app, 1)
    assert [row['user_id'] for row in rows] == [1, 2]
    assert all(row['joined_at'] is None and row['recorded_at'] is not None for row in rows)
    assert not query(
        mysql_app, 'SELECT * FROM game_question'
    )  # Participation does not recover old questions.
    with mysql_app.app_context():
        assert convert_game(1, apply=True, expected_version=2)['status'] == 'already_normalized'
        assert members(mysql_app, 1) == rows
        assert game.answer_game(1, 1, 11, 'apple', **request) == receipt
        assert game.answer_game(1, 2, 22, 'banana', **command(2))['version'] == 3
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_archive_never_establishes_membership_and_active_lookup_covers_both_sources(
    mysql_app, monkeypatch
):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    execute(mysql_app, 'UPDATE game SET status = -1 WHERE id = 1')
    with mysql_app.app_context():
        convert_game(1, apply=True, expected_version=0)
        game.leave_game(1, 2)
        assert [u['id'] for u in game.get_game_state(1)['users']] == [1]
        assert not lobby.list_games(1)['games'][0]['actions']['start']
        game.join_game(1, 3)
        game.start_game(1, 1)
        assert lobby.list_games(2, status='finished')['active_game_id'] is None
        assert lobby.list_games(3, status='finished')['active_game_id'] == 1
        gid = game.create_game(3, 1)['game_id']
        game.join_game(gid, 1)
        game.start_game(gid, 3)
        assert lobby.list_games(3, ListQuery(99, 1), 'waiting')['active_game_id'] == gid
    assert query(mysql_app, 'SELECT users FROM game WHERE id = 1')[0]['users'] == '[1, 2]'
    execute(
        mysql_app,
        "INSERT INTO game (ownerid, dictid, users, wordlist, result, status) VALUES (2, 1, '[2, 1]', '[11]', '[]', 0)",
    )
    with mysql_app.app_context():
        assert lobby.list_games(1)['active_game_id'] == gid + 1
        assert lobby.list_games(2)['active_game_id'] == gid + 1
        assert lobby.list_games(3)['active_game_id'] == gid
    indexes = query(
        mysql_app,
        'SHOW INDEX FROM game_participant WHERE Key_name = %s',
        ('ix_participant_user_game',),
    )
    assert [row['Column_name'] for row in indexes] == ['user_id', 'game_id']


@pytest.mark.parametrize('users', ['broken-json', '[1,1]', '[1,true]', '[2]', '[1,999]'])
def test_conversion_reports_bad_membership_without_repair(mysql_app, users):
    execute(mysql_app, 'UPDATE game SET users = %s WHERE id = 1', (users,))
    before = query(mysql_app, 'SELECT * FROM game')
    result = mysql_app.test_cli_runner().invoke(
        args=['convert-game-participants', '--game-id', '1', '--apply', '--expected-version', '0']
    )
    assert result.exit_code == 1
    assert json.loads(result.output)['code'] in ('legacy_data_error', 'invalid_game_participants')
    assert query(mysql_app, 'SELECT * FROM game') == before
    assert not members(mysql_app, 1)


def test_conversion_rejects_partial_copies_stale_versions_and_exhaustion(mysql_app):
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        convert_game(1, apply=True, expected_version=7)
    assert error.value.code == 'stale_game_version'
    execute(mysql_app, 'UPDATE game SET version = 2147483647 WHERE id = 1')
    for apply in (False, True):
        with mysql_app.app_context(), pytest.raises(GameError, match='exhausted'):
            convert_game(1, apply=apply, expected_version=2147483647)
    execute(mysql_app, 'UPDATE game SET version = 0 WHERE id = 1')
    execute(mysql_app, 'INSERT INTO game_participant VALUES (1, 1, 0, NULL, UTC_TIMESTAMP(6))')
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        convert_game(1, apply=True, expected_version=0)
    assert error.value.code == 'invalid_game_participants'
    assert len(members(mysql_app, 1)) == 1
    assert query(mysql_app, 'SELECT participant_mode, version FROM game')[0] == {
        'participant_mode': 0,
        'version': 0,
    }
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1 and 'unexpected_game_participants' in audit.output


def test_conversion_and_answer_race_serializes_on_game_version(mysql_app):
    results = parallel(
        mysql_app,
        lambda: convert_game(1, apply=True, expected_version=0),
        lambda: game.answer_game(1, 1, 11, 'apple', **command(0)),
    )
    assert (
        sum(isinstance(reply, dict) for reply in results) == 1 and 'stale_game_version' in results
    )
    row = query(mysql_app, 'SELECT participant_mode, version, result FROM game')[0]
    assert row['version'] == 1
    if row['participant_mode'] == 1:
        assert row['result'] == '[]' and len(members(mysql_app, 1)) == 2
    else:
        assert len(json.loads(row['result'])) == 1 and not members(mysql_app, 1)


def test_conversion_failure_rolls_back_rows_metadata_and_version(mysql_app, monkeypatch):
    save = participants.save

    def fail(*args, **kwargs):
        save(*args, **kwargs)
        raise RuntimeError('injected post-conversion failure')

    monkeypatch.setattr(participants, 'save', fail)
    before = query(mysql_app, 'SELECT * FROM game')
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        convert_game(1, apply=True, expected_version=0)
    assert query(mysql_app, 'SELECT * FROM game') == before
    assert not members(mysql_app, 1)


def test_failed_receipt_rolls_back_reshuffle_members_count_and_request(mysql_app, monkeypatch):
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
    before, game_before = members(mysql_app, gid), query(mysql_app, 'SELECT * FROM game')
    complete = game_requests.complete

    def fail(*args):
        complete(*args)
        raise RuntimeError('injected receipt failure')

    monkeypatch.setattr(game_requests, 'complete', fail)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        game.join_game(gid, 3, **command(1))
    assert members(mysql_app, gid) == before
    assert query(mysql_app, 'SELECT * FROM game') == game_before
    assert not query(mysql_app, 'SELECT * FROM game_request')


@pytest.mark.parametrize(
    'corrupt',
    [
        'DELETE FROM game_participant WHERE game_id = %s AND user_id = 2',
        'UPDATE game_participant SET position = 9 WHERE game_id = %s AND user_id = 2',
        'UPDATE game SET participant_count = 3 WHERE id = %s',
        'UPDATE game SET ownerid = 3 WHERE id = %s',
    ],
)
def test_invalid_relations_fail_closed_without_falling_back(mysql_app, mysql_login, corrupt):
    with mysql_app.app_context():
        convert_game(1, apply=True, expected_version=0)
    execute(mysql_app, corrupt, (1,))
    client, _ = mysql_login()
    assert client.get('/api/game/1').json['code'] == 'invalid_game_participants'
    assert client.get('/api/game/list').json['code'] == 'invalid_game_participants'
    response = client.post(
        '/api/game/1/answer', json={'word_id': 11, 'answer': 'apple', **command(1)}
    )
    assert response.status_code == 409 and response.json['code'] == 'invalid_game_participants'
    assert query(mysql_app, 'SELECT version, result FROM game')[0] == {'version': 1, 'result': '[]'}
    assert not query(mysql_app, 'SELECT * FROM game_request')
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1 and 'invalid_game_participants' in audit.output


def test_constraints_enforce_unique_members_slots_references_and_metadata(mysql_app):
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
    for uid, position, code in [(1, 1, 1062), (2, 0, 1062), (2, -1, 3819), (999, 1, 1452)]:
        with pytest.raises(pymysql.MySQLError) as error:
            execute(
                mysql_app,
                'INSERT INTO game_participant VALUES (%s, %s, %s, NULL, UTC_TIMESTAMP(6))',
                (gid, uid, position),
            )
        assert error.value.args[0] == code
    with pytest.raises(pymysql.IntegrityError) as error:
        execute(
            mysql_app, 'INSERT INTO game_participant VALUES (999, 1, 0, NULL, UTC_TIMESTAMP(6))'
        )
    assert error.value.args[0] == 1452
    for mode, count in [(1, None), (1, 0), (0, 1), (2, 1)]:
        with pytest.raises(pymysql.OperationalError) as error:
            execute(
                mysql_app,
                'UPDATE game SET participant_mode = %s, participant_count = %s WHERE id = %s',
                (mode, count, gid),
            )
        assert error.value.args[0] == 3819


def test_migration_preserves_every_old_value_without_converting_json(
    legacy_database, migrate_database
):
    migrate_database(legacy_database, '0004_game_questions')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE game SET users = 'broken-json', version = 17"))
            conn.execute(
                text(
                    'INSERT INTO game (id, ownerid, dictid, users, wordlist, result, status, question_mode, dictname_snapshot) '
                    "VALUES (2, 1, 1, '[2, 1]', '[11]', '[]', -1, 1, 'original title')"
                )
            )
            conn.execute(text("INSERT INTO game_question VALUES (2, 0, 11, 'apple', '苹果')"))
            before = {
                table: [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                for table in ('user', 'dict', 'word', 'game', 'game_request', 'game_question')
            }
        migrate_database(legacy_database, '0005_game_participants')
        with engine.connect() as conn:
            for table, expected in before.items():
                actual = [
                    dict(row) for row in conn.execute(text(f'SELECT * FROM `{table}`')).mappings()
                ]
                if table == 'game':
                    assert all(
                        row.pop('participant_mode') == 0 and row.pop('participant_count') is None
                        for row in actual
                    )
                assert actual == expected
            assert conn.execute(text('SELECT COUNT(*) FROM game_participant')).scalar_one() == 0
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0005_game_participants'
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'ddl',
    [
        'ALTER TABLE game ADD COLUMN participant_mode INT',
        'ALTER TABLE game ADD COLUMN PARTICIPANT_COUNT INT',
        'CREATE TABLE game_participant (id INT PRIMARY KEY) ENGINE=InnoDB',
        'ALTER TABLE game ADD CONSTRAINT ck_game_participants CHECK (version >= 0)',
        'CREATE INDEX IX_GAME_PARTICIPANT_STATUS ON game(status)',
        'ALTER TABLE game MODIFY users TEXT NOT NULL',
        (
            'ALTER TABLE auth_session DROP FOREIGN KEY fk_session_user',
            'ALTER TABLE dict DROP FOREIGN KEY fk_dict_owner',
            'ALTER TABLE user MODIFY id MEDIUMINT NOT NULL AUTO_INCREMENT',
        ),
        (
            'ALTER TABLE game_request DROP FOREIGN KEY fk_request_game',
            'ALTER TABLE game_question DROP FOREIGN KEY fk_question_game',
            'ALTER TABLE game ENGINE=MyISAM',
        ),
    ],
)
def test_participant_migration_preflight_precedes_changes(legacy_database, migrate_database, ddl):
    migrate_database(legacy_database, '0004_game_questions')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            for statement in (ddl,) if isinstance(ddl, str) else ddl:
                conn.execute(text(statement))
        tables = set(inspect(engine).get_table_names())
        columns = {column['name'] for column in inspect(engine).get_columns('game')}
        with pytest.raises(RuntimeError):
            migrate_database(legacy_database, '0005_game_participants')
        assert set(inspect(engine).get_table_names()) == tables
        assert {column['name'] for column in inspect(engine).get_columns('game')} == columns
        with engine.connect() as conn:
            assert (
                conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0004_game_questions'
            )
    finally:
        engine.dispose()
