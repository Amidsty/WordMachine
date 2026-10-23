from contextlib import contextmanager
from unittest.mock import MagicMock, Mock

import pytest
from werkzeug.datastructures import MultiDict

from wm_app.services import leaderboard, lobby
from wm_app.services.errors import ApiError
from wm_app.services.legacy_game import unique_ids
from wm_app.services.pagination import ListQuery


def fake_read(monkeypatch, module, one, many):
    cursor = MagicMock()
    cursor.fetchone.side_effect = one
    cursor.fetchall.side_effect = many

    @contextmanager
    def reading():
        yield cursor

    monkeypatch.setattr(module, 'reading', reading)
    return cursor


def game_row(**changes):
    return {
        'id': 10,
        'version': 0,
        'dictid': 1,
        'ownerid': 1,
        'dictname': 'dictionary',
        'status': -1,
        'users': '[1, 2]',
        **changes,
    }


def test_lobby_queries_only_page_members_and_returns_summary(monkeypatch):
    cursor = fake_read(
        monkeypatch,
        lobby,
        [{'total': 3}, None, {'id': 99, 'users': '[1, 3]'}],
        [[game_row()], [{'id': 1, 'username': 'first'}]],
    )
    data = lobby.list_games(1, ListQuery(99, 2, '%_'), 'waiting')
    assert data['pagination'] == {'page': 2, 'per_page': 2, 'pages': 2, 'total': 3}
    assert data['active_game_id'] == 99  # Independent of the selected page/filter.
    summary = data['games'][0]
    assert summary['actions'] == {'join': False, 'leave': False, 'start': True, 'cancel': True}
    assert summary['users'][1] == {'id': 2, 'username': None, 'rating': None}
    assert set(summary) == {
        'id',
        'version',
        'dictid',
        'dictname',
        'multiplier_snapshot',
        'perf_rule_version',
        'status',
        'owner',
        'users',
        'is_joined',
        'actions',
    }
    calls = [call.args for call in cursor.execute.call_args_list]
    assert calls[1][1] == [-1, '%!%!_%', 2, 2]
    assert (
        'g.*' not in calls[1][0] and 'wordlist' not in calls[1][0] and 'result' not in calls[1][0]
    )
    assert 'LIMIT %s OFFSET %s' in calls[1][0]
    assert 'WHERE id IN' in calls[2][0] and calls[2][1] == [1, 2]
    assert 'FROM game_participant' in calls[3][0] and calls[3][1] == (1, 0)
    assert 'JSON_VALID' in calls[4][0] and calls[4][1] == (0, '1')
    assert 'g.participant_mode = 0' in calls[4][0]
    assert not any(sql.startswith(('UPDATE', 'INSERT', 'DELETE')) for sql, *_ in calls)


@pytest.mark.parametrize(
    'actor,status,expected',
    [
        (3, -1, {'join': True, 'leave': False, 'start': False, 'cancel': False}),
        (2, -1, {'join': False, 'leave': True, 'start': False, 'cancel': False}),
        (1, 0, {'join': False, 'leave': False, 'start': False, 'cancel': False}),
        (1, 2, {'join': False, 'leave': False, 'start': False, 'cancel': False}),
    ],
)
def test_lobby_action_flags_are_server_derived(monkeypatch, actor, status, expected):
    fake_read(monkeypatch, lobby, [{'total': 1}, None, None], [[game_row(status=status)], []])
    assert lobby.list_games(actor)['games'][0]['actions'] == expected


@pytest.mark.parametrize(
    'data', [{'status': 'unknown'}, MultiDict([('status', 'waiting'), ('status', 'running')])]
)
def test_invalid_status_filters_are_rejected(data):
    with pytest.raises(ApiError):
        lobby.status_query(data)


@pytest.mark.parametrize('value', ['{bad', '{}', '[true]', '[1,1]', '[0]', '["1"]', '[[1]]'])
def test_legacy_participants_are_not_repaired(value):
    with pytest.raises(ApiError) as error:
        unique_ids(value)
    assert error.value.code == 'legacy_data_error'


def test_lobby_http_forwards_filters_and_never_trusts_uid(authenticated_client, monkeypatch):
    listing = Mock(return_value={'games': [], 'pagination': {}, 'active_game_id': None})
    monkeypatch.setattr(lobby, 'list_games', listing)
    result = authenticated_client.get(
        '/api/game/list?status=finished&page=2&per_page=5&q=word&uid=99'
    )
    assert result.status_code == 200
    listing.assert_called_once_with(1, ListQuery(2, 5, 'word'), 'finished')
    for query in ('status=unknown', 'status=waiting&status=running', 'page=0', 'per_page=101'):
        assert authenticated_client.get('/api/game/list?' + query).status_code == 400
    assert listing.call_count == 1


def test_top_100_leaderboard_preserves_order_and_bounds_last_page(client, monkeypatch):
    cursor = fake_read(
        monkeypatch,
        leaderboard,
        [],
        [
            [
                {'id': uid, 'username': f'user{uid}', 'introduction': None, 'rating': None}
                for uid in range(1, 101)
            ]
        ],
    )
    response = client.get('/api/leaderboard?page=99&per_page=60')
    assert response.status_code == 200  # Public, no session cookie or CSRF required.
    assert response.json['pagination'] == {'page': 2, 'per_page': 60, 'pages': 2, 'total': 100}
    assert response.json['users'][0]['rank'] == 61
    assert response.json['users'][0]['rating'] is None
    sql = cursor.execute.call_args.args[0]
    assert 'ORDER BY rating DESC, id ASC' in sql and 'deleted = 0' in sql
    assert '*' not in sql and 'pwhash' not in sql and 'LIMIT 100' in sql
    assert cursor.execute.call_count == 1
    cursor.fetchone.assert_not_called()
    assert len(response.json['users']) == 40
    assert response.json['users'][-1]['rank'] == 100


def test_leaderboard_rejects_unsupported_search(client):
    assert client.get('/api/leaderboard?q=anything').status_code == 400


def test_public_profile_keeps_html_404_and_serves_shell_for_existing_user(client, monkeypatch):
    getter = Mock(return_value={'id': 1})
    monkeypatch.setattr('wm_app.routes_main.auth.get_user', getter)
    assert '<div id="app">' in client.get('/user/1/').text
    getter.side_effect = ApiError('User not found', 404, 'not_found')
    assert client.get('/user/999/').status_code == 404
    assert client.get('/api/user/999').status_code == 404


@pytest.mark.parametrize('q', ['', 'needle'])
def test_lobby_count_only_joins_dictionary_when_search_requires_it(monkeypatch, q):
    cursor = fake_read(monkeypatch, lobby, [{'total': 0}, None, None], [[]])
    assert lobby.list_games(1, ListQuery(q=q))['games'] == []
    count_sql = cursor.execute.call_args_list[0].args[0]
    page_sql = cursor.execute.call_args_list[1].args[0]
    assert ('JOIN dict' in count_sql) == bool(q)
    assert ('dictname_snapshot' in count_sql) == bool(q)
    assert 'JOIN dict' in page_sql and 'dictname_snapshot' in page_sql
