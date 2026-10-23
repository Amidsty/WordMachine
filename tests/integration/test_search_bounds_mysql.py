"""Search bounds are redundant predicates, never a change to stored facts or visibility."""

from contextlib import contextmanager

import pytest

from tests.performance.dataset import DISTRIBUTIONS, seed
from tests.performance.measurement import signature, trace_reads
from wm_app.db import reading, transaction
from wm_app.services import auth, dictionary
from wm_app.services.admin_policy import capabilities
from wm_app.services.errors import ApiError
from wm_app.services.pagination import ListQuery, page_offset

pytestmark = pytest.mark.mysql
ROOT = {'id': 3, 'type': 'root', 'admin_level': 5}


def reference_words(dict_id, query):
    where, params = 'dictid = %s AND deleted = 0', [dict_id]
    if query.q:
        where += " AND (english LIKE %s ESCAPE '!' OR chinese LIKE %s ESCAPE '!')"
        params.extend([query.like, query.like])
    with reading() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM word WHERE ' + where, params)
        pagination = query.metadata(cursor.fetchone()['total'])
        cursor.execute(
            'SELECT id, dictid, english, chinese FROM word WHERE '
            + where
            + ' ORDER BY id LIMIT %s OFFSET %s',
            [*params, query.per_page, page_offset(pagination)],
        )
        return {'words': list(cursor.fetchall()), 'pagination': pagination}


def reference_users(include_deleted, query):
    where, params = ('1 = 1' if include_deleted else 'deleted = 0'), []
    if query.q:
        where += " AND username LIKE %s ESCAPE '!'"
        params.append(query.like)
    with reading() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM user WHERE ' + where, params)
        pagination = query.metadata(cursor.fetchone()['total'])
        cursor.execute(
            'SELECT id, username, introduction, rating, type, deleted, admin_level, admin_version FROM user WHERE '
            + where
            + ' ORDER BY id DESC LIMIT %s OFFSET %s',
            [*params, query.per_page, page_offset(pagination)],
        )
        users = list(cursor.fetchall())
        for user in users:
            user['type'] = 'root' if user['admin_level'] else 'normal'
            user['capabilities'] = capabilities(ROOT, user)
        return {'users': users, 'pagination': pagination}


@pytest.mark.parametrize('distribution', DISTRIBUTIONS)
def test_expanded_distributions_match_unbounded_predicates_and_public_fields(
    mysql_app, distribution
):
    seed(mysql_app, 'smoke', distribution)
    with mysql_app.app_context():
        for did in (1, 10, 11):
            for q in ('', 'needle', '%_!', 'entry', '词', 'absent', "%' OR 1=1--"):
                for page in (1, 2, 1000000):
                    query = ListQuery(page=page, per_page=7, q=q)
                    assert signature(dictionary.get_words(did, query)) == signature(
                        reference_words(did, query)
                    )
        for include_deleted in (False, True):
            for q in ('', 'needle', '%_!', 'absent'):
                for page in (1, 2, 1000000):
                    query = ListQuery(page=page, per_page=7, q=q)
                    assert signature(auth.list_users(ROOT, include_deleted, query)) == signature(
                        reference_users(include_deleted, query)
                    )


def test_word_scope_accepts_signed_extreme_zero_ids_gaps_null_text_and_deleted_rows(mysql_app):
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute(
            "SET SESSION sql_mode = CONCAT(@@session.sql_mode, ',NO_AUTO_VALUE_ON_ZERO')"
        )
        cursor.execute(
            "INSERT INTO dict (id, dictname, deleted) VALUES (2, 'scope', 0), (3, 'other', 0), (4, 'empty', 0)"
        )
        cursor.executemany(
            'INSERT INTO word (id, dictid, english, chinese, deleted) VALUES (%s,%s,%s,%s,%s)',
            [
                (-2147483648, 2, 'Needle %_!', None, 0),
                (-200, 2, 'needle', 'unknown', None),
                (-100, 2, 'needle', 'deleted', 1),
                (-1, 2, None, 'needle 中文', 0),
                (0, 2, 'needle', 'zero', 0),
                (1000000, 3, 'needle', 'other dict', 0),
                (2147483647, 2, 'needle', 'last', 0),
            ],
        )
    with mysql_app.app_context():
        for q in ('needle', '%_!', '中文', 'missing'):
            query = ListQuery(page=1000000, per_page=2, q=q)
            assert dictionary.get_words(2, query) == reference_words(2, query)
        with trace_reads() as (statements, _):
            result = dictionary.get_words(4, ListQuery(page=999, q='needle'))
        assert result['pagination']['total'] == 0 and result['words'] == []
        assert len(statements) == 2 and 'MIN(id)' in statements[-1]['sql']
        assert sum('COUNT(*)' in s['sql'] for s in statements) == 1
        # Also exercise wholly negative / zero / positive scopes, not merely a
        # mixed range containing zero. Deleted and NULL flags remain in scope 2.
        for identifiers in ((-2147483648, -1), (-1,), (0,), (2147483647,)):
            with transaction() as cursor:
                cursor.execute('UPDATE word SET dictid = 3 WHERE dictid = 2 AND deleted = 0')
                placeholders = ','.join(['%s'] * len(identifiers))
                cursor.execute(
                    f'UPDATE word SET dictid = 2 WHERE id IN ({placeholders})', identifiers
                )
            query = ListQuery(q='needle')
            result = dictionary.get_words(2, query)
            assert result == reference_words(2, query)
            assert [row['id'] for row in result['words']] == list(identifiers)


@pytest.mark.parametrize('stage', ['dictionary', 'count', 'page'])
def test_search_bounds_count_and_page_share_snapshot_with_new_extreme_ids(
    mysql_app, monkeypatch, stage
):
    changed = False
    prefix = {
        'dictionary': 'SELECT id, dictname',
        'page': 'SELECT w.id',
        'count': 'SELECT COUNT(*)',
    }[stage]

    @contextmanager
    def paused():
        nonlocal changed
        with reading() as cursor:
            execute = cursor.execute

            def after(sql, args=None):
                nonlocal changed
                result = execute(sql, args)
                if not changed and sql.startswith(prefix):
                    with transaction() as writer:
                        writer.execute("UPDATE word SET english = 'changed' WHERE id = 11")
                        writer.execute('UPDATE word SET deleted = 1 WHERE id = 22')
                        writer.execute(
                            "INSERT INTO word (id,dictid,english,chinese,deleted) VALUES (-5,1,'apple','新低',0), (100,1,'apple','新高',0)"
                        )
                    changed = True
                return result

            cursor.execute = after
            yield cursor

    monkeypatch.setattr(dictionary, 'reading', paused)
    with mysql_app.app_context():
        before = dictionary.get_words(1, ListQuery(q='a'))
        assert changed and before['pagination']['total'] == 3
        assert [row['id'] for row in before['words']] == [11, 22, 33]
        assert before['words'][0]['english'] == 'apple'
        fresh = dictionary.get_words(1, ListQuery(q='a'))
        assert [row['id'] for row in fresh['words']] == [-5, 11, 33, 100]
        assert fresh['words'][1]['english'] == 'changed'


def test_empty_scope_stays_empty_when_a_writer_commits_after_bounded_count(mysql_app, monkeypatch):
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute('UPDATE word SET deleted = 1 WHERE dictid = 1')
    changed = False

    @contextmanager
    def paused():
        nonlocal changed
        with reading() as cursor:
            execute = cursor.execute

            def after(sql, args=None):
                nonlocal changed
                result = execute(sql, args)
                if not changed and sql.startswith('SELECT COUNT(*)'):
                    with transaction() as writer:
                        writer.execute(
                            "INSERT INTO word (dictid,english,chinese,deleted) VALUES (1,'match','新',0)"
                        )
                    changed = True
                return result

            cursor.execute = after
            yield cursor

    monkeypatch.setattr(dictionary, 'reading', paused)
    with mysql_app.app_context():
        assert dictionary.get_words(1, ListQuery(q='match'))['pagination']['total'] == 0
        assert changed
        assert dictionary.get_words(1, ListQuery(q='match'))['pagination']['total'] == 1


@pytest.mark.parametrize('page', [1, 1000000])
def test_direct_first_user_page_is_selected_after_clamping_and_keeps_count_snapshot(
    mysql_app, monkeypatch, page
):
    changed, statements = False, []

    @contextmanager
    def paused():
        nonlocal changed
        with reading() as cursor:
            execute = cursor.execute

            def after(sql, args=None):
                nonlocal changed
                statements.append(sql)
                result = execute(sql, args)
                if not changed and sql.startswith('SELECT COUNT(*)'):
                    with transaction() as writer:
                        writer.execute('UPDATE user SET deleted = 1 WHERE id = 2')
                        writer.execute("UPDATE user SET introduction = 'updated' WHERE id = 3")
                        writer.execute(
                            "INSERT INTO user (id,username,deleted) VALUES (10,'new-match',0)"
                        )
                    changed = True
                return result

            cursor.execute = after
            yield cursor

    monkeypatch.setattr(auth, 'reading', paused)
    with mysql_app.app_context():
        before = auth.list_users(ROOT, query=ListQuery(page=page))
        assert before['pagination']['page'] == 1 and before['pagination']['total'] == 3
        assert [row['id'] for row in before['users']] == [3, 2, 1]
        assert before['users'][0]['introduction'] != 'updated'
        assert 'JOIN' not in statements[-1]
        fresh = auth.list_users(ROOT)
        assert [row['id'] for row in fresh['users']] == [10, 3, 1]
        assert fresh['users'][1]['introduction'] == 'updated'


def test_search_bounds_do_not_bypass_missing_or_deleted_dictionary_checks(mysql_app):
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute('UPDATE dict SET deleted = 1 WHERE id = 1')
    with mysql_app.app_context():
        for did in (1, 999):
            with trace_reads() as (statements, _), pytest.raises(ApiError) as error:
                dictionary.get_words(did, ListQuery(q='apple'))
            assert error.value.status == 404
            assert len(statements) == 1 and 'MIN(id)' not in statements[0]['sql']
