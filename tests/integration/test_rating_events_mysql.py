import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import create_engine, text

from wm_app import create_app
from wm_app.services import game, rating_events
from wm_app.services.errors import GameError

from .test_game_mysql import execute, query

pytestmark = pytest.mark.mysql


def prepare(app, monkeypatch):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
        game.answer_game(gid, 1, 11, 'apple')
    return gid


def chain(app, uid=1):
    return query(app, 'SELECT * FROM rating_event WHERE user_id = %s ORDER BY sequence', (uid,))


def test_new_games_use_one_event_chain_and_replay_never_appends(mysql_app, monkeypatch):
    first, second = prepare(mysql_app, monkeypatch), prepare(mysql_app, monkeypatch)
    request = {'request_id': str(uuid4()), 'expected_version': 3}
    with mysql_app.app_context():
        reply = game.end_game(second, 1, **request)
        assert game.end_game(second, 1, **request) == reply
        game.end_game(first, 1)
        state = game.get_game_state(first)
    events = chain(mysql_app)
    assert len(events) == 2
    assert [row['sequence'] for row in events] == [1, 2]
    assert events[0]['previous_id'] is None and events[0]['legacy_rating_id'] is None
    assert events[1]['previous_id'] == events[0]['id'] and events[1]['legacy_rating_id'] is None
    assert events[1]['rating_before'] == events[0]['rating_after']
    user = query(mysql_app, 'SELECT * FROM user WHERE id = 1')[0]
    sources = query(mysql_app, 'SELECT * FROM game_rating WHERE user_id = 1 ORDER BY id')
    rating_events.validate_history(user, sources, events)
    assert (
        user['rating_event_id'] == events[-1]['id'] and user['rating'] == events[-1]['rating_after']
    )
    assert user['ratinghistory'] is None
    assert [row['game_id'] for row in state['userrating'][0]['ratinghistory']] == [second, first]
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_simultaneous_games_share_user_chain_without_forks(mysql_app, monkeypatch):
    gids = [prepare(mysql_app, monkeypatch), prepare(mysql_app, monkeypatch)]
    barrier = Barrier(2)

    def finish(gid):
        with mysql_app.app_context():
            barrier.wait(timeout=5)
            return game.end_game(gid, 1, request_id=str(uuid4()), expected_version=3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(not value['already_finished'] for value in pool.map(finish, gids))
    events = chain(mysql_app)
    assert len(events) == 2 and events[1]['previous_id'] == events[0]['id']
    assert events[1]['rating_before'] == events[0]['rating_after']
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


@pytest.mark.parametrize(
    'corruption', ['lost_head', 'foreign_head', 'source_mismatch', 'broken_sequence']
)
def test_chain_corruption_is_rejected_without_repair(mysql_app, monkeypatch, corruption):
    gid = prepare(mysql_app, monkeypatch)
    with mysql_app.app_context():
        game.answer_game(gid, 2, 22, 'banana')
        game.end_game(gid, 1)
    event = chain(mysql_app)[0]
    if corruption == 'lost_head':
        execute(mysql_app, 'UPDATE user SET rating_event_id = NULL WHERE id = 1')
    elif corruption == 'foreign_head':
        execute(
            mysql_app,
            'UPDATE user SET rating_event_id = %s WHERE id = 1',
            (chain(mysql_app, 2)[0]['id'],),
        )
    elif corruption == 'source_mismatch':
        execute(
            mysql_app,
            'UPDATE rating_event SET rating_before = rating_before + 1, rating_after = rating_after + 1 WHERE id = %s',
            (event['id'],),
        )
    else:
        extra = prepare(mysql_app, monkeypatch)
        with mysql_app.app_context():
            game.end_game(extra, 1)
        execute(
            mysql_app, 'UPDATE rating_event SET sequence = 3 WHERE user_id = 1 AND sequence = 2'
        )
    before = query(mysql_app, 'SELECT * FROM user ORDER BY id')
    with mysql_app.app_context(), pytest.raises(GameError):
        game.get_game_state(gid)
    assert query(mysql_app, 'SELECT * FROM user ORDER BY id') == before
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 1


def test_database_blocks_manual_events_bad_arithmetic_and_deleting_referenced_head(
    mysql_app, monkeypatch
):
    gid = prepare(mysql_app, monkeypatch)
    with mysql_app.app_context():
        game.answer_game(gid, 2, 22, 'banana')
        game.end_game(gid, 1)
    eid = chain(mysql_app)[0]['id']
    for sql, code in [
        ("UPDATE rating_event SET kind = 'adjustment' WHERE id = %s", 3819),
        ('UPDATE rating_event SET delta = delta + 1 WHERE id = %s', 3819),
        ('UPDATE rating_event SET sequence = 0 WHERE id = %s', 3819),
        ('UPDATE rating_event SET previous_id = id WHERE id = %s', 3819),
        ('DELETE FROM rating_event WHERE id = %s', 1451),
    ]:
        with pytest.raises(pymysql.MySQLError) as error:
            execute(mysql_app, sql, (eid,))
        assert error.value.args[0] == code
    columns = 'user_id, sequence, previous_id, legacy_rating_id, game_rating_id, kind, rule_version, rating_before, delta, rating_after, recorded_at'
    with pytest.raises(pymysql.IntegrityError) as duplicate:
        execute(
            mysql_app,
            f'INSERT INTO rating_event ({columns}) SELECT {columns} FROM rating_event WHERE id = %s',
            (eid,),
        )
    assert duplicate.value.args[0] == 1062
    with pytest.raises(pymysql.IntegrityError) as foreign:
        execute(
            mysql_app,
            'UPDATE rating_event SET sequence = 2, previous_id = %s WHERE id = %s',
            (chain(mysql_app, 2)[0]['id'], eid),
        )
    assert foreign.value.args[0] == 1452
    assert len(chain(mysql_app)) == 1


def test_upgrade_keeps_existing_game_ledger_and_starts_with_explicit_anchor(
    legacy_database, migrate_database, monkeypatch
):
    migrate_database(legacy_database, '0009_admin_levels')
    app = create_app(legacy_database['config'])
    # Synthetic pre-0010 settlement: preserve exact recorded delta, never recompute it.
    execute(
        app,
        'UPDATE game SET status = 1, settlement_mode = 1, result = %s WHERE id = 1',
        (json.dumps([{'uid': 1, 'word_id': 11, 'perf': 1600}]),),
    )
    execute(
        app,
        "INSERT INTO game_settlement VALUES (1,1,'legacy-v1',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
    )
    execute(
        app,
        'INSERT INTO game_rating (game_id,user_id,perf,rating_before,delta,rating_after) VALUES (1,1,1600,1500,10,1510)',
    )
    old_id = query(app, 'SELECT id FROM game_rating')[0]['id']
    execute(app, 'UPDATE user SET rating = 1510, rating_ledger_id = %s WHERE id = 1', (old_id,))
    before = {
        table: query(app, f'SELECT * FROM {table} ORDER BY 1')
        for table in ('user', 'game', 'game_rating', 'game_settlement')
    }
    migrate_database(legacy_database, '0010_rating_events')
    assert not chain(app)
    for table, rows in before.items():
        after = query(app, f'SELECT * FROM {table} ORDER BY 1')
        if table == 'user':
            assert all(row.pop('rating_event_id') is None for row in after)
        assert after == rows
    migrate_database(
        legacy_database
    )  # Runtime uses the latest schema, not the frozen migration test target.
    gid = prepare(app, monkeypatch)
    with app.app_context():
        game.end_game(gid, 1)
        state = game.get_game_state(gid)
    event = chain(app)[0]
    assert event['legacy_rating_id'] == old_id and event['rating_before'] == 1510
    assert event['sequence'] == 1 and event['previous_id'] is None
    assert query(app, 'SELECT * FROM game_rating WHERE id = %s', (old_id,)) == before['game_rating']
    assert state['userrating'][0]['ratinghistory'][0] == {
        'game_id': 1,
        'delta': 10,
        'new_rating': 1510,
    }
    assert app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_partial_event_migration_is_not_adopted(legacy_database, migrate_database):
    migrate_database(legacy_database, '0009_admin_levels')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as connection:
            connection.execute(
                text('CREATE TABLE rating_event (id BIGINT PRIMARY KEY) ENGINE=InnoDB')
            )
        with pytest.raises(RuntimeError, match='Partial/custom'):
            migrate_database(legacy_database)
        with engine.connect() as connection:
            assert (
                connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0009_admin_levels'
            )
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user' AND COLUMN_NAME='rating_event_id'"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()
