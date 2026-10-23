import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pymysql
import pytest

from wm_app import create_app
from wm_app.services import game, rating_adjustments
from wm_app.services.errors import ApiError

from .test_game_mysql import execute, query
from .test_rating_events_mysql import prepare

pytestmark = pytest.mark.mysql
PASSWORD = 'test-password'


def finish_seed(app):
    with app.app_context():
        game.end_game(1, 1)


def payload(app, target=1, after=1700):
    user = query(app, 'SELECT rating, rating_event_id FROM user WHERE id = %s', (target,))[0]
    return {
        'request_id': str(uuid4()),
        'expected_rating': user['rating'],
        'expected_event_id': str(user['rating_event_id'])
        if user['rating_event_id'] is not None
        else None,
        'new_rating': after,
        'reason': '人工核准补正',
        'current_password': PASSWORD,
    }


def snapshot(app):
    return {
        name: query(app, f'SELECT * FROM {name} ORDER BY 1')
        for name in (
            'user',
            'game',
            'game_rating',
            'rating_event',
            'manual_rating',
            'rating_adjustment_request',
            'admin_audit',
        )
    }


def test_http_self_lower_review_replay_and_password_privacy(mysql_app, mysql_login):
    finish_seed(mysql_app)
    client, csrf = mysql_login(3)
    data = payload(mysql_app)
    response = client.post('/api/admin/user/1/rating', json=data)
    assert response.status_code == 200, response.json
    before = snapshot(mysql_app)
    assert client.post('/api/admin/user/1/rating', json=data).json == response.json
    assert snapshot(mysql_app) == before
    assert (
        client.post('/api/admin/user/1/rating', json={**data, 'reason': 'different'}).status_code
        == 409
    )
    assert (
        client.post(
            '/api/admin/user/1/rating', json={**data, 'current_password': 'wrong'}
        ).status_code
        == 401
    )
    assert snapshot(mysql_app) == before
    review = client.get('/api/admin/user/1/rating')
    assert review.status_code == 200
    assert (
        review.json['rating'] == 1700
        and review.json['rating_event_id'] == response.json['rating_event_id']
    )
    event = review.json['events'][0]
    assert event['kind'] == 'manual' and event['game_id'] is None and event['actor_id'] == 3
    assert event['reason'] == data['reason']
    assert not review.json['running_game']
    for table in ('rating_adjustment_request', 'manual_rating', 'admin_audit'):
        assert PASSWORD not in json.dumps(query(mysql_app, f'SELECT * FROM {table}'), default=str)
    assert client.get('/api/session').json['authenticated']  # Adjustment does not revoke sessions.
    assert (
        client.post('/api/admin/user/3/rating', json=payload(mysql_app, 3, -100)).status_code == 200
    )
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0
    csrf_bad = client.post(
        '/api/admin/user/1/rating',
        json=payload(mysql_app, after=1800),
        headers={'X-CSRF-Token': 'wrong'},
    )
    assert csrf_bad.status_code == 403


@pytest.mark.parametrize(
    'actor_level,target_level,deleted,status',
    [(3, 0, 0, 403), (4, 4, 0, 403), (4, 5, 0, 403), (4, 0, 1, 409), (4, 3, 0, 200)],
)
def test_locked_scope_and_account_state(mysql_app, actor_level, target_level, deleted, status):
    finish_seed(mysql_app)
    execute(
        mysql_app, 'UPDATE user SET admin_level = %s, type = %s WHERE id = 3', (actor_level, 'root')
    )
    execute(
        mysql_app,
        'UPDATE user SET admin_level = %s, type = %s, deleted = %s WHERE id = 1',
        (target_level, 'root' if target_level else 'normal', deleted),
    )
    data, before = payload(mysql_app), snapshot(mysql_app)
    with mysql_app.app_context():
        if status == 200:
            assert rating_adjustments.adjust(3, 1, data)['rating_after'] == 1700
        else:
            with pytest.raises(ApiError) as error:
                rating_adjustments.adjust(3, 1, data)
            assert error.value.status == status
            assert snapshot(mysql_app) == before


def test_stale_head_including_balance_aba_and_noop(mysql_app):
    finish_seed(mysql_app)
    original = payload(mysql_app)
    with mysql_app.app_context():
        rating_adjustments.adjust(3, 1, original)
        rating_adjustments.adjust(3, 1, payload(mysql_app, after=1500))
        with pytest.raises(ApiError) as error:
            rating_adjustments.adjust(3, 1, {**original, 'request_id': str(uuid4())})
        assert error.value.code == 'stale_rating'
        assert (
            rating_adjustments.adjust(3, 1, original)['rating_after'] == 1700
        )  # Original receipt, not current balance.
        with pytest.raises(ApiError):
            rating_adjustments.adjust(3, 1, payload(mysql_app, after=1500))
    assert len(query(mysql_app, 'SELECT * FROM manual_rating')) == 2
    assert query(mysql_app, 'SELECT rating FROM user WHERE id = 1')[0]['rating'] == 1500


def test_manual_game_manual_game_chain_preserves_sources_and_history(mysql_app, monkeypatch):
    finish_seed(mysql_app)
    with mysql_app.app_context():
        rating_adjustments.adjust(3, 1, payload(mysql_app))
        first = prepare(mysql_app, monkeypatch)
        game.end_game(first, 1)
        source = query(mysql_app, 'SELECT * FROM game_rating ORDER BY id')
        state = game.get_game_state(first)['userrating']
        rating_adjustments.adjust(3, 1, payload(mysql_app, after=-200))
        second = prepare(mysql_app, monkeypatch)
        game.end_game(second, 1)
        assert (
            game.get_game_state(first)['userrating'][0]['ratinghistory'][0]
            == state[0]['ratinghistory'][0]
        )
        review = rating_adjustments.review(3, 1)
    assert [event['kind'] for event in reversed(review['events'])] == [
        'manual',
        'game',
        'manual',
        'game',
    ]
    assert query(mysql_app, 'SELECT * FROM game_rating WHERE id = %s', (source[0]['id'],)) == source
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_running_legacy_and_relational_games_block_adjustment(mysql_app, monkeypatch):
    with mysql_app.app_context():
        for _ in range(2):
            before = snapshot(mysql_app)
            assert rating_adjustments.review(3, 1)['running_game']
            with pytest.raises(ApiError) as error:
                rating_adjustments.adjust(3, 1, payload(mysql_app))
            assert error.value.code == 'rating_game_running'
            assert snapshot(mysql_app) == before
            game.end_game(1, 1)
            prepare(mysql_app, monkeypatch)


def test_audit_failure_rolls_back_source_balance_event_and_receipt(mysql_app, monkeypatch):
    finish_seed(mysql_app)
    before, data = snapshot(mysql_app), payload(mysql_app)

    def fail(*args, **kwargs):
        raise RuntimeError('synthetic audit fault')

    monkeypatch.setattr(rating_adjustments, 'audit', fail)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        rating_adjustments.adjust(3, 1, data)
    assert snapshot(mysql_app) == before


def test_concurrent_duplicate_and_different_intents(mysql_app):
    finish_seed(mysql_app)
    data = payload(mysql_app)

    def concurrent(commands):
        barrier = Barrier(2)

        def perform(command):
            with mysql_app.app_context():
                barrier.wait(timeout=10)
                try:
                    return rating_adjustments.adjust(3, 1, command)
                except ApiError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(perform, commands))

    results = concurrent([data, data])
    assert results[0] == results[1] and isinstance(results[0], dict)
    newer = payload(mysql_app, after=1900)
    results = concurrent([newer, {**newer, 'request_id': str(uuid4()), 'new_rating': 2000}])
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 'stale_rating' in results
    assert len(query(mysql_app, 'SELECT * FROM manual_rating')) == 2
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


def test_password_recheck_limits_are_committed_on_failure(mysql_app, mysql_login):
    finish_seed(mysql_app)
    mysql_app.config['RATING_ADJUST_LIMIT'] = 2
    client, _ = mysql_login(3)
    before = snapshot(mysql_app)
    data = {**payload(mysql_app), 'current_password': 'incorrect'}
    assert client.post('/api/admin/user/1/rating', json=data).status_code == 401
    assert client.post('/api/admin/user/1/rating', json=data).status_code == 401
    result = client.post('/api/admin/user/1/rating', json={**data, 'current_password': PASSWORD})
    assert result.status_code == 429 and int(result.headers['Retry-After']) > 0
    assert snapshot(mysql_app) == before


def test_database_source_checks_and_restrict(mysql_app):
    finish_seed(mysql_app)
    with mysql_app.app_context():
        rating_adjustments.adjust(3, 1, payload(mysql_app))
    for statement, code in [
        ("UPDATE rating_event SET kind = 'game'", 3819),
        ('UPDATE rating_event SET manual_rating_id = NULL', 3819),
        ('UPDATE manual_rating SET actor_level = 3', 3819),
        ('UPDATE manual_rating SET delta = 0', 3819),
        ("UPDATE manual_rating SET reason = ''", 3819),
        ('DELETE FROM manual_rating', 1451),
        ('DELETE FROM rating_adjustment_request', 1451),
    ]:
        with pytest.raises(pymysql.MySQLError) as error:
            execute(mysql_app, statement)
        assert error.value.args[0] == code


@pytest.mark.parametrize(
    'operation,first', [('start', 'game'), ('start', 'adjust'), ('end', 'game'), ('end', 'adjust')]
)
def test_game_start_and_settlement_serialize_with_adjustment(
    mysql_app, monkeypatch, operation, first
):
    finish_seed(mysql_app)
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        if operation == 'end':
            game.start_game(gid, 1)
            game.answer_game(gid, 1, 11, 'apple')
    data = payload(mysql_app)
    held, waiting, release = Event(), Event(), Event()
    game_name = '_lock_membership_actor' if operation == 'start' else '_lock_users'
    original_game = getattr(game, game_name)
    original_manual = rating_adjustments.lock_users

    def wrapped(original, role):
        def call(*args):
            if first != role:
                waiting.set()
                return original(*args)
            result = original(*args)
            held.set()
            assert release.wait(10)
            return result

        return call

    monkeypatch.setattr(game, game_name, wrapped(original_game, 'game'))
    monkeypatch.setattr(rating_adjustments, 'lock_users', wrapped(original_manual, 'adjust'))

    def perform(role):
        with mysql_app.app_context():
            try:
                if role == 'game':
                    return getattr(game, operation + '_game')(gid, 1)
                return rating_adjustments.adjust(3, 1, data)
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(perform, first)
        try:
            assert held.wait(10)
            follower = pool.submit(perform, 'adjust' if first == 'game' else 'game')
            assert waiting.wait(10)
            assert not follower.done()
        finally:
            release.set()
        results = {
            first: winner.result(timeout=10),
            ('adjust' if first == 'game' else 'game'): follower.result(timeout=10),
        }
    assert isinstance(results['game'], dict)
    if operation == 'start' and first == 'adjust':
        assert results['adjust']['rating_after'] == 1700
        assert query(mysql_app, 'SELECT rating FROM user WHERE id = 1')[0]['rating'] == 1700
    else:
        assert results['adjust'] == (
            'stale_rating' if operation == 'end' and first == 'game' else 'rating_game_running'
        )
        assert not query(mysql_app, 'SELECT * FROM manual_rating')
        assert not query(mysql_app, 'SELECT * FROM rating_adjustment_request')
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


@pytest.mark.parametrize(
    'change', ['demote', 'ban_actor', 'reset_password', 'promote_target', 'ban_target']
)
def test_authorization_is_rechecked_after_http_authentication(
    mysql_app, mysql_login, monkeypatch, change
):
    from wm_app.services import auth

    finish_seed(mysql_app)
    execute(mysql_app, "UPDATE user SET admin_level = 4, type = 'root' WHERE id = 3")
    execute(mysql_app, "UPDATE user SET admin_level = 5, type = 'root' WHERE id = 2")
    client, _ = mysql_login(3)
    data = payload(mysql_app)
    entered, release = Event(), Event()
    original = rating_adjustments.lock_users

    def pause(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(rating_adjustments, 'lock_users', pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, '/api/admin/user/1/rating', json=data)
        try:
            assert entered.wait(10)
            with mysql_app.app_context():
                if change == 'demote':
                    auth.set_admin_level(
                        2, 3, {'admin_level': 3, 'expected_version': 0, 'reason': 'revoked'}
                    )
                elif change == 'promote_target':
                    auth.set_admin_level(
                        2, 1, {'admin_level': 4, 'expected_version': 0, 'reason': 'promoted'}
                    )
                else:
                    auth.admin_user_action(
                        2,
                        1 if change == 'ban_target' else 3,
                        'reset-password' if change == 'reset_password' else 'delete',
                        'New-password-123!',
                    )
        finally:
            release.set()
        response = future.result(timeout=10)
    assert response.status_code in (401, 403, 409), response.json
    assert not query(mysql_app, 'SELECT * FROM manual_rating')
    assert not query(mysql_app, 'SELECT * FROM rating_event')
    assert not query(mysql_app, 'SELECT * FROM rating_adjustment_request')
    assert query(mysql_app, 'SELECT rating FROM user WHERE id = 1')[0]['rating'] == 1500


def test_lost_confirmation_replays_committed_receipt(mysql_app, mysql_login, monkeypatch):
    finish_seed(mysql_app)
    client, _ = mysql_login(3)
    data = payload(mysql_app)
    original = rating_adjustments.adjust

    def lose(*args):
        original(*args)
        raise pymysql.OperationalError(2013, 'synthetic lost confirmation')

    monkeypatch.setattr(rating_adjustments, 'adjust', lose)
    assert client.post('/api/admin/user/1/rating', json=data).status_code == 503
    assert query(mysql_app, 'SELECT rating FROM user WHERE id = 1')[0]['rating'] == 1700
    monkeypatch.setattr(rating_adjustments, 'adjust', original)
    reply = client.post('/api/admin/user/1/rating', json=data)
    assert reply.status_code == 200 and reply.json['request_id'] == data['request_id']
    assert len(query(mysql_app, 'SELECT * FROM manual_rating')) == 1
    assert len(query(mysql_app, "SELECT * FROM admin_audit WHERE action = 'adjust-rating'")) == 1


def test_orphan_manual_source_is_not_hidden_by_null_head(mysql_app):
    finish_seed(mysql_app)
    with mysql_app.app_context():
        rating_adjustments.adjust(3, 1, payload(mysql_app))
    execute(mysql_app, 'UPDATE user SET rating_event_id = NULL WHERE id = 1')
    execute(mysql_app, 'DELETE FROM rating_event WHERE user_id = 1')
    before = snapshot(mysql_app)
    with mysql_app.app_context():
        with pytest.raises(ApiError) as error:
            rating_adjustments.review(3, 1)
        assert error.value.code == 'invalid_rating_event'
        with pytest.raises(ApiError) as error:
            rating_adjustments.adjust(3, 1, payload(mysql_app, after=1800))
        assert error.value.code == 'invalid_rating_event'
    assert snapshot(mysql_app) == before
    audit = mysql_app.test_cli_runner().invoke(args=['audit-legacy'])
    assert audit.exit_code == 1 and 'unreferenced_manual_rating' in audit.output


def test_signed_int_extremes_and_bigint_delta(mysql_app):
    finish_seed(mysql_app)
    with mysql_app.app_context():
        rating_adjustments.adjust(3, 1, payload(mysql_app, after=-2147483648))
        result = rating_adjustments.adjust(3, 1, payload(mysql_app, after=2147483647))
        assert result['delta'] == 4294967295
        assert rating_adjustments.review(3, 1)['rating'] == 2147483647
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


@pytest.mark.parametrize('has_event', [False, True])
def test_0011_upgrade_preserves_existing_data_and_requires_new_head(
    legacy_database, migrate_database, has_event
):
    migrate_database(legacy_database, '0011_dictionary_multipliers')
    app = create_app(legacy_database['config'])
    # Frozen 0011 facts, not current runtime services against an obsolete schema.
    execute(
        app,
        'UPDATE game SET status = 1, settlement_mode = 1, result = %s WHERE id = 1',
        (json.dumps([{'uid': 1, 'word_id': 11, 'perf': 1600}]),),
    )
    execute(
        app,
        "INSERT INTO game_settlement VALUES (1, 1, 'legacy-v1', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))",
    )
    execute(
        app,
        'INSERT INTO game_rating (id, game_id, user_id, perf, rating_before, delta, rating_after) VALUES (9, 1, 1, 1600, 1500, 10, 1510)',
    )
    if has_event:
        execute(
            app,
            "INSERT INTO rating_event (id, user_id, sequence, game_rating_id, kind, rule_version, rating_before, delta, rating_after, recorded_at) VALUES (7, 1, 1, 9, 'game', 'legacy-v1', 1500, 10, 1510, UTC_TIMESTAMP(6))",
        )
    execute(
        app,
        'UPDATE user SET rating = 1510, rating_ledger_id = 9, rating_event_id = %s WHERE id = 1',
        (7 if has_event else None,),
    )
    before = {
        name: query(app, f'SELECT * FROM {name} ORDER BY 1')
        for name in (
            'user',
            'game',
            'dict',
            'word',
            'admin_audit',
            'game_rating',
            'game_settlement',
            'rating_event',
        )
    }
    assert app.test_client().get('/health/ready').status_code == 503
    migrate_database(legacy_database)
    assert app.test_client().get('/health/ready').status_code == 200
    for table, rows in before.items():
        after = query(app, f'SELECT * FROM {table} ORDER BY 1')
        if table == 'rating_event':
            assert all(row.pop('manual_rating_id') is None for row in after)
        assert after == rows
    assert not query(app, 'SELECT * FROM manual_rating')
    assert not query(app, 'SELECT * FROM rating_adjustment_request')
    with app.app_context():
        rating_adjustments.adjust(3, 1, payload(app))
        assert game.get_game_state(1)['userrating'][0]['ratinghistory'] == [
            {'game_id': 1, 'delta': 10, 'new_rating': 1510}
        ]
    assert query(app, 'SELECT * FROM game_rating') == before['game_rating']
    assert app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0


@pytest.mark.parametrize('partial', ['table', 'source_type', 'source_fk', 'constraint'])
def test_partial_migration_is_not_adopted(legacy_database, migrate_database, partial):
    migrate_database(legacy_database, '0011_dictionary_multipliers')
    app = create_app(legacy_database['config'])
    if partial == 'table':
        execute(app, 'CREATE TABLE manual_rating (id BIGINT PRIMARY KEY) ENGINE=InnoDB')
    elif partial == 'constraint':
        execute(
            app,
            'CREATE TABLE collision (value INT, CONSTRAINT ck_event_source CHECK (value >= 0)) ENGINE=InnoDB',
        )
    else:
        execute(app, 'ALTER TABLE rating_event DROP FOREIGN KEY fk_event_game_rating')
        if partial == 'source_type':
            execute(app, 'ALTER TABLE rating_event MODIFY game_rating_id VARCHAR(32) NOT NULL')
    with pytest.raises(RuntimeError, match='Partial/custom'):
        migrate_database(legacy_database)
    assert (
        query(app, 'SELECT version_num FROM alembic_version')[0]['version_num']
        == '0011_dictionary_multipliers'
    )
    assert not query(
        app,
        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rating_adjustment_request'",
    )
