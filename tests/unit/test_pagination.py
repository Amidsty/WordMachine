from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields
from decimal import Decimal
from inspect import signature
from unittest.mock import MagicMock

import pytest
from werkzeug.datastructures import MultiDict

from wm_app.services import auth, dictionary, leaderboard, lobby
from wm_app.services.errors import ApiError
from wm_app.services.pagination import ListQuery, boolean_query


@pytest.mark.parametrize(
    'data',
    [
        {'page': '0'},
        {'page': '-1'},
        {'page': '1.5'},
        {'page': 'true'},
        {'page': '01'},
        {'page': '1000001'},
        {'per_page': '0'},
        {'per_page': '101'},
        {'per_page': '99999999'},
        {'q': 'x' * 101},
        {'q': 'x\x00'},
        {'q': '\ud800'},
        MultiDict([('page', '1'), ('page', '2')]),
        MultiDict([('q', 'a'), ('q', 'b')]),
    ],
)
def test_invalid_list_parameters_are_rejected(data):
    with pytest.raises(ApiError):
        ListQuery.parse(data)


def test_defaults_limits_literal_search_and_clamped_last_page():
    assert ListQuery.parse({}) == ListQuery(1, 20, '')
    assert ListQuery(99, 2).metadata(3) == {'page': 2, 'per_page': 2, 'total': 3, 'pages': 2}
    assert ListQuery(99, 2).metadata(0)['page'] == 1
    assert ListQuery(q=' %_! ').like == '%!%!_!!%'
    assert boolean_query({'include_deleted': 'TRUE'}, 'include_deleted')
    for data in (
        {'include_deleted': 'yes'},
        MultiDict([('include_deleted', 'true'), ('include_deleted', 'false')]),
    ):
        with pytest.raises(ApiError):
            boolean_query(data, 'include_deleted')


def test_shared_default_query_remains_immutable():
    # Ruff's B008 exception is valid only while ListQuery contains immutable fields.
    assert [(field.name, field.type) for field in fields(ListQuery)] == [
        ('page', int),
        ('per_page', int),
        ('q', str),
    ]
    for service in (
        auth.list_users,
        dictionary.list_dictionaries,
        dictionary.get_words,
        leaderboard.list_leaders,
        lobby.list_games,
    ):
        query = signature(service).parameters['query'].default
        assert query == ListQuery()
        with pytest.raises(FrozenInstanceError):
            query.q = 'changed'
        assert query == ListQuery()


def fake_read(monkeypatch, module, rows, results):
    cursor = MagicMock()
    cursor.fetchone.side_effect = rows
    cursor.fetchall.return_value = results

    @contextmanager
    def reading():
        yield cursor

    monkeypatch.setattr(module, 'reading', reading)
    return cursor


def test_dictionary_list_is_sql_bounded_and_owner_flags_are_derived(monkeypatch):
    actor = {'id': 1, 'type': 'normal'}
    cursor = fake_read(
        monkeypatch,
        dictionary,
        [{'total': 3}],
        [],
    )
    cursor.fetchall.side_effect = [
        [
            {
                'id': 1,
                'ownerid': None,
                'dictname': 'system',
                'multiplier': Decimal('1.00'),
                'config_version': 0,
            }
        ],
        [{'dictid': 1, 'word_count': 1}],
    ]
    result = dictionary.list_dictionaries(actor, ListQuery(50, 2, "%' OR 1=1--"))
    assert result['pagination']['page'] == 2
    assert result['dicts'][0]['can_manage'] is False
    sql, params = cursor.execute.call_args_list[1].args
    assert 'ORDER BY d.id DESC LIMIT %s OFFSET %s' in sql
    assert 'OR 1=1--' not in sql
    assert params[-2:] == [2, 2]
    assert params[0].startswith('%!%')
    assert 'FROM word' not in sql
    sql, params = cursor.execute.call_args_list[2].args
    assert 'GROUP BY dictid' in sql and 'dictid IN (%s)' in sql
    assert params == [1]
    assert result['dicts'][0]['word_count'] == 1
    assert cursor.execute.call_count == 3


def test_word_list_is_scoped_and_bounded(monkeypatch):
    cursor = fake_read(
        monkeypatch,
        dictionary,
        [{'id': 5, 'ownerid': 1}, {'total': 4}],
        [{'id': 11, 'dictid': 5}],
    )
    result = dictionary.get_words(5, ListQuery(2, 2, '_'))
    assert result['pagination'] == {'page': 2, 'per_page': 2, 'total': 4, 'pages': 2}
    sql, params = cursor.execute.call_args.args
    assert 'dictid = %s AND deleted = 0' in sql
    assert 'english LIKE %s' in sql and 'chinese LIKE %s' in sql
    assert params == [5, 5, '%!_%', '%!_%', 2, 2]
    count_sql, count_params = cursor.execute.call_args_list[1].args
    assert 'id BETWEEN bounds.first_id AND bounds.last_id' in count_sql
    assert count_params == params[:-2]
    assert 'JOIN (SELECT id FROM word JOIN (SELECT MIN(id)' in sql
    assert ') page ON page.id = w.id ORDER BY w.id' in sql
    assert cursor.execute.call_count == 3


def test_user_list_is_root_only_and_never_selects_passwords(monkeypatch):
    cursor = fake_read(monkeypatch, auth, [{'total': 1}], [{'id': 2, 'username': 'other'}])
    with pytest.raises(ApiError):
        auth.list_users({'id': 1, 'type': 'normal'}, query=ListQuery())
    cursor.execute.assert_not_called()
    result = auth.list_users(
        {'id': 1, 'type': 'root', 'admin_level': 5}, False, ListQuery(q='other')
    )
    assert result['pagination']['total'] == 1
    sql, params = cursor.execute.call_args.args
    assert 'deleted = 0' in sql and 'pwhash' not in sql and 'SELECT *' not in sql
    assert params == ['%other%', 20, 0]
    assert 'JOIN (SELECT id FROM user WHERE' in sql
    assert ') page ON page.id = u.id ORDER BY u.id DESC' in sql
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize(
    'path', ['/api/dicts?per_page=101', '/api/dict/1/words?page=0', '/api/dicts?page=1&page=2']
)
def test_http_rejects_bad_pagination_before_database(authenticated_client, path):
    assert authenticated_client.get(path).status_code == 400


def test_metadata_is_readable_but_does_not_grant_write_access(
    authenticated_client, monkeypatch, app
):
    fake_read(
        monkeypatch,
        dictionary,
        [
            {
                'id': 9,
                'dictname': 'other',
                'ownerid': 2,
                'multiplier': Decimal('1.00'),
                'config_version': 0,
            }
        ],
        [],
    )
    app.config.update(CSV_MAX_BYTES=8, CSV_MAX_ROWS=1)
    response = authenticated_client.get('/api/dict/9')
    assert response.status_code == 200
    assert response.json['dict']['can_manage'] is False
    assert response.json['csv_limits'] == {'max_bytes': 8, 'max_rows': 1}


@pytest.mark.parametrize(
    'path, module, rows, key',
    [
        ('/api/dicts', dictionary, [{'total': 0}], 'dicts'),
        (
            '/api/dict/1/words',
            dictionary,
            [{'id': 1, 'ownerid': None}, {'total': 0}],
            'words',
        ),
        ('/api/admin/users', auth, [{'total': 0}], 'users'),
    ],
)
def test_list_http_contract(authenticated_client, identity, monkeypatch, path, module, rows, key):
    identity.user.update(type='root', admin_level=5)
    fake_read(monkeypatch, module, rows, [])
    response = authenticated_client.get(path + '?page=2&per_page=5&q=none')
    assert response.status_code == 200
    assert response.json == {
        'success': True,
        key: [],
        'pagination': {'page': 1, 'per_page': 5, 'pages': 1, 'total': 0},
    }


def test_management_shell_routes_do_not_read_user_lists(authenticated_client, identity):
    for path in ('/admin/', '/admin/dicts/9/'):
        assert authenticated_client.get(path).status_code == 200
    assert authenticated_client.get('/admin/users/').status_code == 403
    identity.user.update(type='root', admin_level=5)
    assert authenticated_client.get('/admin/users/').status_code == 200
    assert authenticated_client.get('/admin/not-a-route/').status_code == 404


@pytest.mark.parametrize('per_page', [1, 20, 100])
def test_dictionary_counts_use_one_bounded_query_not_one_per_row(monkeypatch, per_page):
    cursor = fake_read(monkeypatch, dictionary, [{'total': 500}], [])
    ids = list(range(500, 500 - per_page, -1))
    cursor.fetchall.side_effect = [
        [
            {
                'id': uid,
                'dictname': None,
                'ownerid': None,
                'multiplier': Decimal('1.00'),
                'config_version': 0,
            }
            for uid in ids
        ],
        [{'dictid': ids[-1], 'word_count': 7}],
    ]
    result = dictionary.list_dictionaries({'id': 1, 'type': 'normal'}, ListQuery(per_page=per_page))
    assert cursor.execute.call_count == 3
    sql, params = cursor.execute.call_args.args
    assert sql.count('%s') == per_page and params == ids
    assert 'GROUP BY dictid' in sql and 'deleted = 0' in sql
    assert [row['id'] for row in result['dicts']] == ids
    assert [row['word_count'] for row in result['dicts']] == [0] * (per_page - 1) + [7]


def test_empty_dictionary_page_does_not_issue_an_empty_in_query(monkeypatch):
    cursor = fake_read(monkeypatch, dictionary, [{'total': 0}], [])
    result = dictionary.list_dictionaries({'id': 1, 'type': 'normal'})
    assert result['dicts'] == []
    assert cursor.execute.call_count == 2
    assert all('FROM word' not in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize('domain', ['words', 'users'])
def test_zero_exact_count_skips_the_page_query(monkeypatch, domain):
    module = dictionary if domain == 'words' else auth
    rows = ([{'id': 5, 'ownerid': 1}] if domain == 'words' else []) + [{'total': 0}]
    cursor = fake_read(monkeypatch, module, rows, [])
    query = ListQuery(page=999, q='missing')
    result = (
        dictionary.get_words(5, query)
        if domain == 'words'
        else auth.list_users({'id': 3, 'type': 'root', 'admin_level': 5}, query=query)
    )
    assert result[domain] == [] and result['pagination']['page'] == 1
    assert cursor.execute.call_count == (2 if domain == 'words' else 1)
    cursor.fetchall.assert_not_called()


@pytest.mark.parametrize('q', ['needle', '%_!', "%' OR 1=1--", '词'])
def test_word_search_joins_one_scoped_bounds_row_without_a_round_trip_or_index_hint(monkeypatch, q):
    cursor = fake_read(monkeypatch, dictionary, [{'id': 5}, {'total': 1}], [])
    query = ListQuery(q=q)
    dictionary.get_words(5, query)
    assert cursor.execute.call_count == 3
    for call in cursor.execute.call_args_list[1:]:
        sql, params = call.args
        assert 'OR 1=1--' not in sql
        assert 'id BETWEEN bounds.first_id AND bounds.last_id' in sql
        assert sql.count('MIN(id)') == sql.count('MAX(id)') == 1
        assert sql.count('dictid = %s AND deleted = 0') == 2
        assert params[:4] == [5, 5, query.like, query.like]
        assert 'USE INDEX' not in sql and 'FORCE INDEX' not in sql
        assert 'LIKE' not in sql.split(') bounds')[0]


def test_empty_search_matches_keep_exact_count_and_skip_the_page_query(monkeypatch):
    cursor = fake_read(monkeypatch, dictionary, [{'id': 5}, {'total': 0}], [])
    result = dictionary.get_words(5, ListQuery(page=1000000, q='missing'))
    assert result == {
        'words': [],
        'pagination': {'page': 1, 'per_page': 20, 'total': 0, 'pages': 1},
    }
    assert cursor.execute.call_count == 2
    cursor.fetchall.assert_not_called()


def test_unfiltered_word_page_does_not_read_search_bounds(monkeypatch):
    cursor = fake_read(monkeypatch, dictionary, [{'id': 5}, {'total': 1}], [])
    dictionary.get_words(5)
    assert cursor.execute.call_count == 3
    assert all(
        'MIN(id)' not in call.args[0] and 'BETWEEN' not in call.args[0]
        for call in cursor.execute.call_args_list
    )


def test_missing_dictionary_is_rejected_before_bounds_or_count(monkeypatch):
    cursor = fake_read(monkeypatch, dictionary, [None], [])
    with pytest.raises(ApiError) as error:
        dictionary.get_words(5, ListQuery(q='missing'))
    assert error.value.status == 404
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    'page,total,expected_join,offset',
    [(1, 100, False, 0), (999, 1, False, 0), (2, 100, True, 20), (999, 100, True, 80)],
)
@pytest.mark.parametrize('include_deleted', [False, True])
@pytest.mark.parametrize('q', ['', '%_!'])
def test_user_page_strategy_uses_clamped_offset_and_the_same_public_fields(
    monkeypatch, page, total, expected_join, offset, include_deleted, q
):
    cursor = fake_read(monkeypatch, auth, [{'total': total}], [])
    auth.list_users(
        {'id': 3, 'type': 'root', 'admin_level': 5}, include_deleted, ListQuery(page=page, q=q)
    )
    sql, params = cursor.execute.call_args.args
    assert ('JOIN (SELECT id' in sql) is (expected_join or bool(q))
    assert ('deleted = 0' in sql) is (not include_deleted)
    assert params == (['%!%!_!!%'] if q else []) + [20, offset]
    assert sql.startswith(
        'SELECT u.id, u.username, u.introduction, u.rating, u.type, u.deleted, u.admin_level, u.admin_version '
    )
    assert 'pwhash' not in sql and 'SELECT *' not in sql
    assert cursor.execute.call_count == 2
