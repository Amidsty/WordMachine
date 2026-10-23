import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
from unittest.mock import MagicMock

import pymysql
import pytest
from sqlalchemy import create_engine, text

from wm_app import create_app, socketio
from wm_app.services import (
    answer_conversion as conversion,
)
from wm_app.services import (
    game,
    game_answers,
    participant_conversion,
)
from wm_app.services.errors import GameError

from .test_game_answers_mysql import command, recorded
from .test_game_mysql import execute, parallel, query, rating_history

pytestmark = pytest.mark.mysql

TABLE_ORDER = {
    'game': 'id',
    'user': 'id',
    'dict': 'id',
    'word': 'id',
    'game_question': 'game_id,position',
    'game_participant': 'game_id,position',
    'game_answer': 'game_id,position',
    'game_request': 'actor_id,request_id',
    'game_settlement': 'game_id',
    'game_rating': 'id',
}


def contents(app):
    return {
        table: query(app, f'SELECT * FROM `{table}` ORDER BY {order}')
        for table, order in TABLE_ORDER.items()
    }


@pytest.fixture
def eligible(mysql_app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
    # Synthetic pre-0006 shape, before any answer exists. Production never does this.
    execute(
        mysql_app,
        "UPDATE game SET perf_mode = 0, multiplier_snapshot = NULL, answer_mode = 0, answer_count = NULL, result = '[]' WHERE id = %s",
        (gid,),
    )
    return gid


def answer_prefix(app, gid, count=1):
    with app.app_context():
        for uid, wid, value in [(1, 11, 'apple'), (2, 22, 'banana')][:count]:
            game.answer_game(gid, uid, wid, value)


def test_cli_read_only_apply_round_trip_and_repeated_conversion_preserve_every_other_value(
    mysql_app, eligible
):
    gid = eligible
    execute(mysql_app, 'UPDATE user SET rating = 1433 WHERE id = 1')
    with mysql_app.app_context():
        game.answer_game(gid, 1, 11, 'İ' * 255, **command(2))
        original_state = game.get_game_state(gid)
    raw = ' \n' + json.dumps(original_state['result'], ensure_ascii=False, indent=1) + '\n'
    execute(mysql_app, 'UPDATE game SET result = %s WHERE id = %s', (raw, gid))
    before = contents(mysql_app)
    runner = mysql_app.test_cli_runner()
    args = ['convert-game-answers', '--game-id', str(gid)]
    dry = runner.invoke(args=args)
    assert dry.exit_code == 0 and json.loads(dry.output) == {
        'game_id': gid,
        'status': 'ready',
        'answers': 1,
        'version': 3,
    }
    assert contents(mysql_app) == before
    refused = runner.invoke(args=[*args, '--apply'])
    assert refused.exit_code == 1 and json.loads(refused.output)['code'] == 'invalid_parameters'
    applied = runner.invoke(args=[*args, '--apply', '--expected-version', '3'])
    assert applied.exit_code == 0 and json.loads(applied.output) == {
        'game_id': gid,
        'status': 'converted',
        'answers': 1,
        'version': 4,
    }
    after = contents(mysql_app)
    assert after['game'] == [
        row if row['id'] != gid else {**row, 'answer_mode': 1, 'answer_count': 1, 'version': 4}
        for row in before['game']
    ]
    for table in set(TABLE_ORDER) - {'game', 'game_answer'}:
        assert after[table] == before[table]
    row = recorded(mysql_app, gid)[0]
    assert row['answered_at'] is None and row['recorded_at'] is not None
    assert row['answer'] == ('İ' * 255).lower()
    assert row['perf'].hex() == original_state['result'][0]['perf'].hex()
    assert row['perf_delta'].hex() == original_state['result'][0]['perf_delta'].hex()
    with mysql_app.app_context():
        assert game.get_game_state(gid) == {**original_state, 'version': 4}
        assert (
            conversion.convert_game(gid, apply=True, expected_version=4)['status']
            == 'already_normalized'
        )
    assert contents(mysql_app) == after
    stale = runner.invoke(args=[*args, '--apply', '--expected-version', '3'])
    assert stale.exit_code == 1 and json.loads(stale.output)['code'] == 'stale_game_version'
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_conversion_neither_changes_receipts_nor_replays_scoring_and_future_answers_append(
    mysql_app, mysql_login, eligible
):
    gid = eligible
    owner, csrf = mysql_login(1)
    other, _ = mysql_login(2)
    payload = {'word_id': 11, 'answer': ' APPLE ', **command(2)}
    path = f'/api/game/{gid}'
    original = owner.post(path + '/answer', json=payload).json
    assert original['version'] == 3
    raw = query(mysql_app, 'SELECT result FROM game WHERE id = %s', (gid,))[0]['result']
    with mysql_app.app_context():
        conversion.convert_game(gid, apply=True, expected_version=3)
    first_row = recorded(mysql_app, gid)[0]
    socket = socketio.test_client(mysql_app, flask_test_client=owner, auth={'csrf_token': csrf})
    try:
        replay = socket.emit(
            'game.answer', {**payload, 'game_id': gid, 'csrf_token': csrf}, callback=True
        )
        assert replay == original
        assert owner.get(path).json['game']['version'] == 4
        assert (
            other.post(
                path + '/answer', json={'word_id': 22, 'answer': 'banana', **command(4)}
            ).json['version']
            == 5
        )
        last = socket.emit(
            'game.answer',
            {'word_id': 33, 'answer': 'wrong', 'game_id': gid, 'csrf_token': csrf, **command(5)},
            callback=True,
        )
        assert last['status'] == game.FINISHED and last['version'] == 6
    finally:
        socket.disconnect()
    rows = recorded(mysql_app, gid)
    assert len(rows) == 3 and rows[0] == first_row
    assert all(row['answered_at'] == row['recorded_at'] for row in rows[1:])
    assert query(mysql_app, 'SELECT result FROM game WHERE id = %s', (gid,))[0]['result'] == raw
    assert len(rating_history(mysql_app, 1)) == len(rating_history(mysql_app, 2)) == 1
    restarted = create_app(dict(mysql_app.config))
    with restarted.app_context():
        assert {
            'success': True,
            **game.answer_game(
                gid,
                1,
                11,
                'apple',
                **{key: payload[key] for key in ('request_id', 'expected_version')},
            ),
        } == original
    assert recorded(mysql_app, gid) == rows
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_real_pre_answer_migration_history_never_recovers_from_live_dictionary_or_recalculates(
    legacy_database, migrate_database, monkeypatch
):
    migrate_database(legacy_database, '0005_game_participants')
    entry = {
        'uid': 1,
        'word_id': 11,
        'answer': 'recorded text',
        'result': True,
        'usercombo': 1,
        'globalcombo': 1,
        'perf_delta': 11.123456789012345,
        'perf': 1511.1234567890124,
        'rating_version': 'legacy-v1',
    }
    raw = ' ' + json.dumps([entry]) + ' '
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE game SET status=1, question_mode=1, dictname_snapshot='original', result=:raw, "
                    "perf='original perf archive', ratingdelta='original delta archive' WHERE id=1"
                ),
                {'raw': raw},
            )
            # Explicit historical fixture evidence, not a conversion from current words.
            for position, wid in enumerate([11, 22, 33]):
                conn.execute(
                    text('INSERT INTO game_question VALUES (1,:position,:wid,:en,:zh)'),
                    {
                        'position': position,
                        'wid': wid,
                        'en': f'original-{wid}',
                        'zh': f'原题-{wid}',
                    },
                )
            conn.execute(
                text(
                    "UPDATE user SET rating=1510, gamehistory='[1]', ratinghistory=:history WHERE id=1"
                ),
                {'history': '[{"game_id":1,"delta":10,"new_rating":1510,"extra":"keep"}]'},
            )
            conn.execute(text('UPDATE user SET deleted=1 WHERE id=2'))
            conn.execute(text('DELETE FROM word'))
            conn.execute(text('DELETE FROM dict'))
        migrate_database(legacy_database)
        app = create_app(legacy_database['config'])
        with app.app_context():
            with pytest.raises(GameError) as error:
                conversion.convert_game(1)
            assert error.value.code == 'answer_conversion_requires_participants'
            participant_conversion.convert_game(1, apply=True, expected_version=0)
        before = contents(app)

        def forbidden(*args, **kwargs):
            raise AssertionError('conversion must not score, judge or capture questions')

        monkeypatch.setattr(game, 'score_answer', forbidden)
        monkeypatch.setattr('wm_app.services.game_questions.capture', forbidden)
        monkeypatch.setattr('wm_app.services.game_settlements.rating_delta', forbidden)
        with app.app_context():
            assert conversion.convert_game(1, apply=True, expected_version=1)['version'] == 2
            state = game.get_game_state(1)
            assert state['result'] == [entry] and state['status'] == game.FINISHED
            assert state['words'][0]['english'] == 'original-11'
            assert all('english' not in word for word in state['words'][1:])
            assert game.end_game(1, 1)['already_finished']
        after = contents(app)
        for table in set(TABLE_ORDER) - {'game', 'game_answer'}:
            assert after[table] == before[table]
        assert after['game'] == [
            {**before['game'][0], 'answer_mode': 1, 'answer_count': 1, 'version': 2}
        ]
        assert not after['game_settlement'] and not after['game_rating']
        assert recorded(app, 1)[0]['answered_at'] is None
        # Old opaque perf/delta archives are untouched, not certified by this tool.
    finally:
        engine.dispose()


def test_legacy_live_is_rejected_even_when_answers_are_empty(mysql_app):
    before = contents(mysql_app)
    for apply in (False, True):
        with mysql_app.app_context(), pytest.raises(GameError) as error:
            conversion.convert_game(1, apply=apply, expected_version=0)
        assert error.value.code == 'answer_conversion_requires_snapshot'
    assert contents(mysql_app) == before


@pytest.mark.parametrize('status', [-1, 0, 1, 2])
def test_explicit_empty_answers_convert_without_creating_any_settlement(
    mysql_app, eligible, status
):
    execute(
        mysql_app,
        'UPDATE game SET status = %s, settlement_mode = 0 WHERE id = %s',
        (status, eligible),
    )
    before = contents(mysql_app)
    with mysql_app.app_context():
        result = conversion.convert_game(eligible, apply=True, expected_version=2)
    assert result == {'game_id': eligible, 'status': 'converted', 'answers': 0, 'version': 3}
    after = contents(mysql_app)
    assert not after['game_answer'] and not after['game_settlement'] and not after['game_rating']
    for table in set(TABLE_ORDER) - {'game'}:
        assert after[table] == before[table]


@pytest.mark.parametrize('raw', [None, '', '[{"uid":1,"perf":1511}]', '[{"uid":1,"uid":2}]'])
def test_unconvertible_source_returns_only_generic_report_and_changes_nothing(
    mysql_app, eligible, raw
):
    execute(mysql_app, 'UPDATE game SET result = %s WHERE id = %s', (raw, eligible))
    before = contents(mysql_app)
    result = mysql_app.test_cli_runner().invoke(
        args=[
            'convert-game-answers',
            '--game-id',
            str(eligible),
            '--apply',
            '--expected-version',
            '2',
        ]
    )
    assert result.exit_code == 1
    report = json.loads(result.output)
    assert (
        set(report) == {'game_id', 'code', 'message'}
        and report['code'] == 'unconvertible_game_answers'
    )
    assert '1511' not in result.output and 'uid' not in result.output
    assert contents(mysql_app) == before


@pytest.mark.parametrize(
    'damage,code',
    [
        ('DELETE FROM game_question WHERE game_id = %s AND position = 1', 'invalid_game_snapshot'),
        (
            'DELETE FROM game_participant WHERE game_id = %s AND user_id = 2',
            'invalid_game_participants',
        ),
        ('UPDATE game SET version = 2147483647 WHERE id = %s', 'invalid_game_state'),
        (
            "INSERT INTO game_settlement VALUES (%s,0,'legacy-v1',NULL,UTC_TIMESTAMP(6))",
            'invalid_game_settlement',
        ),
    ],
)
def test_parent_damage_partial_settlement_and_version_exhaustion_do_not_trigger_repair(
    mysql_app, eligible, damage, code
):
    execute(mysql_app, damage, (eligible,))
    before = contents(mysql_app)
    version = next(row['version'] for row in before['game'] if row['id'] == eligible)
    for apply in (False, True):
        with mysql_app.app_context(), pytest.raises(GameError) as error:
            conversion.convert_game(eligible, apply=apply, expected_version=version)
        assert error.value.code == code
    assert contents(mysql_app) == before


def test_partial_answer_copy_is_not_merged_and_normalized_corruption_never_falls_back(
    mysql_app, eligible
):
    answer_prefix(mysql_app, eligible)
    execute(
        mysql_app,
        """INSERT INTO game_answer (game_id,position,user_id,answer,correct,usercombo,globalcombo,perf_delta,perf,rating_version,answered_at,recorded_at) VALUES (%s,0,1,'apple',1,1,1,11,1511,'legacy-v1',NULL,UTC_TIMESTAMP(6))""",
        (eligible,),
    )
    before = contents(mysql_app)
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        conversion.convert_game(eligible, apply=True, expected_version=3)
    assert error.value.code == 'invalid_game_answers' and contents(mysql_app) == before
    execute(mysql_app, 'DELETE FROM game_answer WHERE game_id = %s', (eligible,))
    with mysql_app.app_context():
        conversion.convert_game(eligible, apply=True, expected_version=3)
    execute(mysql_app, 'DELETE FROM game_answer WHERE game_id = %s', (eligible,))
    for apply in (False, True):
        with mysql_app.app_context(), pytest.raises(GameError) as error:
            conversion.convert_game(eligible, apply=apply, expected_version=4)
        assert error.value.code == 'invalid_game_answers'
    assert not recorded(
        mysql_app, eligible
    )  # The still-valid archive must not restore the deleted row.


def test_already_normalized_ignores_bad_archive_and_preserves_existing_settlement(
    mysql_app, eligible
):
    answer_prefix(mysql_app, eligible)
    with mysql_app.app_context():
        game.end_game(eligible, 2)
    settled = contents(mysql_app)
    with mysql_app.app_context():
        conversion.convert_game(eligible, apply=True, expected_version=4)
    converted = contents(mysql_app)
    for table in set(TABLE_ORDER) - {'game', 'game_answer'}:
        assert converted[table] == settled[table]
    execute(
        mysql_app, 'UPDATE game SET result = %s WHERE id = %s', ('broken private archive', eligible)
    )
    before = contents(mysql_app)
    with mysql_app.app_context():
        assert conversion.convert_game(eligible)['status'] == 'already_normalized'
        assert (
            conversion.convert_game(eligible, apply=True, expected_version=5)['status']
            == 'already_normalized'
        )
    assert contents(mysql_app) == before
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


@pytest.mark.parametrize('competitor', ['answer', 'end', 'conversion'])
def test_conversion_races_with_last_answer_end_or_another_conversion_on_one_version(
    mysql_app, eligible, competitor
):
    gid = eligible
    answer_prefix(mysql_app, gid, 2)
    operations = {
        'answer': lambda: game.answer_game(gid, 1, 33, 'cat', **command(4)),
        'end': lambda: game.end_game(gid, 2, **command(4)),
        'conversion': lambda: conversion.convert_game(gid, apply=True, expected_version=4),
    }
    results = parallel(
        mysql_app,
        lambda: conversion.convert_game(gid, apply=True, expected_version=4),
        operations[competitor],
    )
    assert (
        sum(isinstance(result, dict) for result in results) == 1 and 'stale_game_version' in results
    )
    row = query(mysql_app, 'SELECT * FROM game WHERE id = %s', (gid,))[0]
    assert row['version'] == 5
    if row['answer_mode'] == 1:
        assert (
            row['answer_count'] == len(recorded(mysql_app, gid)) == 2
            and row['status'] == game.RUNNING
        )
    else:
        assert not recorded(mysql_app, gid) and row['status'] == game.FINISHED
    with mysql_app.app_context():
        game.end_game(gid, 1)
    assert len(rating_history(mysql_app, 1)) == len(rating_history(mysql_app, 2)) == 1
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_conversion_and_other_game_final_answer_follow_same_user_lock_order(
    mysql_app, eligible, monkeypatch
):
    answer_prefix(mysql_app, eligible, 2)
    with mysql_app.app_context():
        other = game.create_game(2, 1)['game_id']
        game.join_game(other, 1)  # Reversed participant order, still ascending user locks.
        game.start_game(other, 2)
        game.answer_game(other, 2, 11, 'apple')
        game.answer_game(other, 1, 22, 'banana')
    clock = MagicMock()
    clock.utcnow.return_value = datetime(2026, 1, 1)
    write_time = datetime(2026, 1, 2, 0, 0, 0, 123456)
    references = conversion.participants.lock_references

    def lock_then_advance(cursor, ids):
        references(cursor, ids)
        clock.utcnow.return_value = write_time

    monkeypatch.setattr(conversion, 'datetime', clock)
    monkeypatch.setattr(conversion.participants, 'lock_references', lock_then_advance)
    results = parallel(
        mysql_app,
        lambda: conversion.convert_game(eligible, apply=True, expected_version=4),
        lambda: game.answer_game(other, 2, 33, 'cat', **command(4)),
    )
    assert all(isinstance(result, dict) for result in results)
    assert len(recorded(mysql_app, eligible)) == 2 and len(recorded(mysql_app, other)) == 3
    assert all(row['recorded_at'] == write_time for row in recorded(mysql_app, eligible))
    assert all(
        [row['game_id'] for row in rating_history(mysql_app, uid)] == [other] for uid in (1, 2)
    )


def test_dry_run_uses_one_snapshot_while_concurrent_end_commits_and_apply_rechecks(
    mysql_app, eligible, monkeypatch
):
    answer_prefix(mysql_app, eligible)
    paused, committed = Event(), Event()
    original = conversion.prepare

    def pause(*args, **kwargs):
        paused.set()
        assert committed.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(conversion, 'prepare', pause)

    def inspect():
        with mysql_app.app_context():
            return conversion.convert_game(eligible)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(inspect)
        try:
            assert paused.wait(10)
            with mysql_app.app_context():
                game.end_game(eligible, 2, **command(3))
        finally:
            committed.set()
        report = future.result(timeout=15)
    assert report == {'game_id': eligible, 'status': 'ready', 'answers': 1, 'version': 3}
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        conversion.convert_game(eligible, apply=True, expected_version=3)
    assert error.value.code == 'stale_game_version'
    assert not recorded(mysql_app, eligible)


@pytest.mark.parametrize('point', ['first_insert', 'last_insert', 'metadata', 'verification'])
def test_failure_after_each_conversion_write_rolls_back_every_table(
    mysql_app, eligible, monkeypatch, point
):
    answer_prefix(mysql_app, eligible, 2)
    before = contents(mysql_app)
    original = pymysql.cursors.Cursor.execute
    inserts = reads = 0

    def fail(cursor, sql, params=None):
        nonlocal inserts, reads
        result = original(cursor, sql, params)
        if sql.startswith('INSERT INTO game_answer'):
            inserts += 1
            if (point == 'first_insert' and inserts == 1) or (
                point == 'last_insert' and inserts == 2
            ):
                raise RuntimeError('injected insert failure')
        if point == 'metadata' and sql.startswith('UPDATE game SET answer_mode = 1'):
            raise RuntimeError('injected metadata failure')
        if sql.startswith('SELECT * FROM game_answer WHERE'):
            reads += 1
            if point == 'verification' and reads == 2:
                raise RuntimeError('injected readback failure')
        return result

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.cursors.Cursor, 'execute', fail)
        with mysql_app.app_context(), pytest.raises(RuntimeError):
            conversion.convert_game(eligible, apply=True, expected_version=4)
    assert contents(mysql_app) == before


def test_mysql_enforces_dry_run_read_only_even_if_an_internal_helper_attempts_a_write(
    mysql_app, eligible, monkeypatch
):
    before = contents(mysql_app)
    original = conversion._check_references

    def attempt(cursor, ids):
        cursor.execute('UPDATE game SET version = version + 1 WHERE id = %s', (eligible,))
        original(cursor, ids)

    monkeypatch.setattr(conversion, '_check_references', attempt)
    with mysql_app.app_context(), pytest.raises(pymysql.OperationalError) as error:
        conversion.convert_game(eligible)
    assert error.value.args[0] == 1792  # Cannot execute statement in a READ ONLY transaction.
    assert contents(mysql_app) == before


def test_sql_readback_difference_is_rejected_before_commit(mysql_app, eligible, monkeypatch):
    answer_prefix(mysql_app, eligible)
    before = contents(mysql_app)
    insert = game_answers.insert

    def altered(cursor, row):
        insert(cursor, {**row, 'perf': row['perf'] + 0.125})

    monkeypatch.setattr(game_answers, 'insert', altered)
    with mysql_app.app_context(), pytest.raises(GameError) as error:
        conversion.convert_game(eligible, apply=True, expected_version=3)
    assert error.value.code == 'unconvertible_game_answers'
    assert contents(mysql_app) == before


def test_mismatching_existing_ledger_is_not_certified_or_repaired(mysql_app, eligible):
    answer_prefix(mysql_app, eligible)
    with mysql_app.app_context():
        game.end_game(eligible, 2)
    execute(mysql_app, 'UPDATE game_rating SET perf = perf + 1 WHERE game_id = %s', (eligible,))
    before = contents(mysql_app)
    for apply in (False, True):
        with mysql_app.app_context(), pytest.raises(GameError) as error:
            conversion.convert_game(eligible, apply=apply, expected_version=4)
        assert error.value.code == 'invalid_game_settlement'
    assert contents(mysql_app) == before


def test_lost_commit_ack_reports_uncertainty_and_read_only_check_finds_committed_conversion(
    mysql_app, eligible, monkeypatch
):
    answer_prefix(mysql_app, eligible)
    original = pymysql.connections.Connection.commit

    def lost_ack(connection):
        original(connection)
        raise pymysql.OperationalError(2013, 'sensitive simulated connection detail')

    args = ['convert-game-answers', '--game-id', str(eligible)]
    with monkeypatch.context() as patch:
        patch.setattr(pymysql.connections.Connection, 'commit', lost_ack)
        response = mysql_app.test_cli_runner().invoke(
            args=[*args, '--apply', '--expected-version', '3']
        )
    assert (
        response.exit_code == 1
        and json.loads(response.output)['code'] == 'conversion_database_error'
    )
    assert 'sensitive' not in response.output and 'rollback' not in response.output
    rows = recorded(mysql_app, eligible)
    check = mysql_app.test_cli_runner().invoke(args=args)
    assert check.exit_code == 0 and json.loads(check.output) == {
        'game_id': eligible,
        'status': 'already_normalized',
        'answers': 1,
        'version': 4,
    }
    assert recorded(mysql_app, eligible) == rows
