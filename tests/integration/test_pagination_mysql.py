import pytest

pytestmark = pytest.mark.mysql


def test_dictionary_paging_search_and_metadata(mysql_login):
    owner, _ = mysql_login(1)
    first = owner.post('/api/dict', json={'dictname': '100%_literal'}).json['dict_id']
    second = owner.post('/api/dict', json={'dictname': 'other'}).json['dict_id']
    page = owner.get('/api/dicts?per_page=2').json
    assert [row['id'] for row in page['dicts']] == [second, first]
    assert page['pagination'] == {'page': 1, 'per_page': 2, 'total': 3, 'pages': 2}
    last = owner.get('/api/dicts?per_page=2&page=999').json
    assert last['pagination']['page'] == 2
    assert [row['id'] for row in last['dicts']] == [1]
    filtered = owner.get('/api/dicts', query_string={'q': '%_'}).json
    assert [row['id'] for row in filtered['dicts']] == [first]
    assert owner.get('/api/dict/1').json['dict']['can_manage'] is False
    assert owner.get('/api/dict/' + str(first)).json['dict']['can_manage'] is True
    assert owner.delete('/api/dict/' + str(second), json={}).status_code == 200
    assert owner.get('/api/dicts?per_page=2&page=2').json['pagination']['page'] == 1


def test_words_are_paged_but_export_is_complete(mysql_login):
    reader, _ = mysql_login(1)
    page = reader.get('/api/dict/1/words?per_page=1&page=2').json
    assert [word['id'] for word in page['words']] == [22]
    assert page['pagination']['total'] == 3
    assert reader.get('/api/dict/1/words', query_string={'q': '苹果'}).json['words'][0]['id'] == 11
    assert len(reader.get('/api/dict/1/export-csv').json['content'].splitlines()) == 3
    admin, _ = mysql_login(3)
    admin.post('/api/dict/1/word', json={'english': 'a_%!', 'chinese': '字面符号'})
    assert len(reader.get('/api/dict/1/words', query_string={'q': '_%!'}).json['words']) == 1
    assert reader.get('/api/dict/999/words').status_code == 404


def test_user_paging_filters_and_permissions(mysql_login):
    ordinary, _ = mysql_login(1)
    assert ordinary.get('/api/admin/users?per_page=1').status_code == 403
    admin, _ = mysql_login(3)
    page = admin.get('/api/admin/users?per_page=2').json
    assert [user['id'] for user in page['users']] == [3, 2]
    assert all('pwhash' not in user for user in page['users'])
    assert admin.get('/api/admin/users?per_page=2&page=2').json['users'][0]['id'] == 1
    admin.post('/api/admin/user/2/delete', json={})
    assert admin.get('/api/admin/users?q=user2').json['users'] == []
    assert (
        admin.get('/api/admin/users?q=user2&include_deleted=true').json['users'][0]['deleted'] == 1
    )
    assert admin.get('/api/admin/users?include_deleted=invalid').status_code == 400
