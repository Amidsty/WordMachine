"""Read optimizations must preserve exact results and MVCC semantics on MySQL."""

from contextlib import contextmanager

import pymysql
import pytest
from sqlalchemy import create_engine

from tests.performance.dataset import seed
from tests.performance.index_costs import storage, write_costs
from tests.performance.measurement import trace_reads
from wm_app.db import reading, transaction
from wm_app.services import auth, dictionary, leaderboard, lobby
from wm_app.services.pagination import ListQuery

from .test_list_indexes_mysql import snapshot

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize('actor_id,role', [(1, 'normal'), (2, 'normal'), (3, 'root')])
def test_page_word_counts_keep_nulls_soft_deletes_empty_dicts_and_owner_flags(
    mysql_app, actor_id, role
):
    with mysql_app.app_context(), transaction() as cursor:
        cursor.executemany(
            'INSERT INTO dict (id, dictname, ownerid, deleted) VALUES (%s, %s, %s, %s)',
            [
                (2, 'literal %_!', 1, 0),
                (3, None, 2, 0),
                (4, 'deleted', 1, 1),
                (5, 'unknown', 1, None),
            ],
        )
        cursor.execute('UPDATE word SET deleted = 1 WHERE id = 22')
        cursor.execute('UPDATE word SET deleted = NULL WHERE id = 33')
        cursor.executemany(
            'INSERT INTO word (dictid, english, chinese, deleted) VALUES (%s, %s, %s, %s)',
            [
                (2, 'not active', '软删', 1),
                (2, 'unknown', '未知', None),
                (3, None, None, 0),
                (3, 'another', '另一个', 0),
                (4, 'deleted parent', '旧词', 0),
                (5, 'unknown parent', '未知', 0),
                (999, 'orphan', '孤立', 0),
            ],
        )
    actor = {'id': actor_id, 'type': role, 'admin_level': 5 if role == 'root' else 0}
    with mysql_app.app_context():
        first = dictionary.list_dictionaries(actor, ListQuery(per_page=2))
        assert first['pagination'] == {'page': 1, 'per_page': 2, 'total': 3, 'pages': 2}
        assert [row['id'] for row in first['dicts']] == [3, 2]
        assert [row['word_count'] for row in first['dicts']] == [2, 0]
        assert first['dicts'][0]['dictname'] is None
        assert [row['can_manage'] for row in first['dicts']] == [
            role == 'root' or actor_id == 2,
            role == 'root' or actor_id == 1,
        ]
        last = dictionary.list_dictionaries(actor, ListQuery(page=1000000, per_page=2))
        assert last['pagination']['page'] == 2
        assert [(row['id'], row['word_count'], row['can_manage']) for row in last['dicts']] == [
            (1, 1, role == 'root')
        ]
        filtered = dictionary.list_dictionaries(actor, ListQuery(q='%_!'))
        assert [(row['id'], row['word_count']) for row in filtered['dicts']] == [(2, 0)]
        empty = dictionary.list_dictionaries(actor, ListQuery(q='no-such-dictionary'))
        # PyMySQL returns an empty tuple; the HTTP serializer exposes an empty array.
        assert not empty['dicts'] and empty['pagination']['total'] == 0


def test_dictionary_page_and_counts_share_snapshot_across_a_committed_writer(
    mysql_app, monkeypatch
):
    changed = False

    @contextmanager
    def paused_reading():
        nonlocal changed
        with reading() as cursor:
            execute = cursor.execute

            def after_page(sql, args=None):
                nonlocal changed
                result = execute(sql, args)
                if sql.startswith('SELECT d.id') and not changed:
                    # Another real connection commits after the accepted page but before counts.
                    with transaction() as writer:
                        writer.execute(
                            "UPDATE dict SET dictname = 'changed', ownerid = 2 WHERE id = 1"
                        )
                        writer.execute('UPDATE word SET deleted = 1 WHERE dictid = 1')
                        writer.execute(
                            "INSERT INTO word (dictid, english, chinese, deleted) VALUES (1, 'new', '新', 0)"
                        )
                    changed = True
                return result

            cursor.execute = after_page
            yield cursor

    monkeypatch.setattr(dictionary, 'reading', paused_reading)
    with mysql_app.app_context():
        actor = {'id': 1, 'type': 'normal'}
        first = dictionary.list_dictionaries(actor)['dicts'][0]
        assert changed
        assert (first['dictname'], first['ownerid'], first['word_count']) == (
            'test dictionary',
            None,
            3,
        )
        fresh = dictionary.list_dictionaries(actor)['dicts'][0]
        assert (fresh['dictname'], fresh['ownerid'], fresh['word_count']) == ('changed', 2, 1)


@pytest.mark.parametrize('size', [0, 1, 99, 100, 101])
def test_bounded_leaderboard_preserves_empty_small_ties_nulls_and_exact_cap(mysql_app, size):
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute('UPDATE user SET deleted = 1, rating = 99999')
        cursor.execute('UPDATE user SET deleted = NULL WHERE id = 2')
        rows = [(10 + i, f'ranked-{i}', None if i % 9 == 0 else i % 5 - 2) for i in range(size)]
        if rows:
            cursor.executemany(
                'INSERT INTO user (id, username, rating, introduction, pwhash, deleted) VALUES (%s, %s, %s, NULL, %s, 0)',
                [(uid, name, rating, 'must-not-be-public') for uid, name, rating in rows],
            )
    ranked = sorted(rows, key=lambda row: (row[2] is None, -(row[2] or 0), row[0]))[:100]
    with mysql_app.app_context():
        for page in (1, 2, 1000000):
            query = ListQuery(page=page, per_page=60)
            result = leaderboard.list_leaders(query)
            pagination = query.metadata(len(ranked))
            offset = (pagination['page'] - 1) * query.per_page
            assert result['pagination'] == pagination
            assert [(row['id'], row['rating']) for row in result['users']] == [
                (row[0], row[2]) for row in ranked[offset : offset + 60]
            ]
            assert [row['rank'] for row in result['users']] == list(
                range(offset + 1, offset + len(result['users']) + 1)
            )
            assert all(
                set(row) == {'id', 'username', 'introduction', 'rating', 'rank'}
                for row in result['users']
            )


def test_lobby_count_keeps_missing_deleted_and_snapshot_dictionary_semantics(mysql_app):
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute("UPDATE dict SET dictname = 'live needle', deleted = 1 WHERE id = 1")
        cursor.executemany(
            'INSERT INTO game (id, ownerid, dictid, users, wordlist, result, status, question_mode, dictname_snapshot) '
            'VALUES (%s, 1, %s, %s, %s, %s, -1, %s, %s)',
            [
                (2, None, '[1, 2]', '[11]', '[]', 0, None),
                (3, 999, '[1, 2]', '[11]', '[]', 0, None),
                (4, 1, '[1, 2]', '[11]', '[]', 1, 'Saved needle'),
            ],
        )
        cursor.execute(
            "INSERT INTO game_question (game_id, position, word_id, english, chinese) VALUES (4, 0, 11, 'apple', '苹果')"
        )
    with mysql_app.app_context():
        result = lobby.list_games(1)
        assert result['pagination']['total'] == 4 and result['active_game_id'] == 1
        assert [(row['id'], row['dictname']) for row in result['games']] == [
            (4, 'Saved needle'),
            (3, None),
            (2, None),
            (1, 'live needle'),
        ]
        assert lobby.list_games(1, status='waiting')['pagination']['total'] == 3
        assert lobby.list_games(1, ListQuery(q='live'))['pagination']['total'] == 1
        assert lobby.list_games(1, ListQuery(q='needle'))['pagination']['total'] == 2
        empty = lobby.list_games(1, ListQuery(q='absent'))
        assert empty['games'] == [] and empty['pagination']['total'] == 0
        assert empty['active_game_id'] == 1


def test_benchmark_read_transaction_rejects_dml_even_bypassing_the_recorder(mysql_app):
    with mysql_app.app_context(), trace_reads() as (statements, counters):
        with reading() as cursor:
            cursor.execute('SELECT rating FROM user WHERE id = 1')
            assert cursor.fetchone()['rating'] == 1500
            with pytest.raises(ValueError, match='SELECT'):
                cursor.execute('UPDATE user SET rating = rating + 1 WHERE id = 1')
            # Exercise MySQL enforcement separately from the Python statement guard.
            with pytest.raises(pymysql.err.OperationalError) as error:
                cursor.cursor.execute('UPDATE user SET rating = rating + 1 WHERE id = 1')
            assert error.value.args[0] == 1792
        assert len(statements) == 1 and counters
    with mysql_app.app_context(), reading() as cursor:
        cursor.execute('SELECT rating FROM user WHERE id = 1')
        assert cursor.fetchone()['rating'] == 1500


@pytest.mark.parametrize('domain', ['words', 'users'])
def test_id_page_and_full_rows_keep_count_snapshot_across_committed_changes(
    mysql_app, monkeypatch, domain
):
    module = dictionary if domain == 'words' else auth
    changed = False

    @contextmanager
    def paused_reading():
        nonlocal changed
        with reading() as cursor:
            execute = cursor.execute

            def after_count(sql, args=None):
                nonlocal changed
                result = execute(sql, args)
                if sql.startswith('SELECT COUNT(*)') and not changed:
                    with transaction() as writer:
                        if domain == 'words':
                            writer.execute('UPDATE word SET deleted = 1 WHERE id = 22')
                            writer.execute("UPDATE word SET english = 'changed' WHERE id = 33")
                        else:
                            writer.execute('UPDATE user SET deleted = 1 WHERE id = 2')
                            writer.execute("UPDATE user SET introduction = 'changed' WHERE id = 1")
                    changed = True
                return result

            cursor.execute = after_count
            yield cursor

    monkeypatch.setattr(module, 'reading', paused_reading)
    with mysql_app.app_context():

        def listing():
            query = ListQuery(page=2, per_page=1)
            return (
                dictionary.get_words(1, query)
                if domain == 'words'
                else auth.list_users({'id': 3, 'type': 'root', 'admin_level': 5}, query=query)
            )

        first = listing()
        assert first['pagination']['total'] == 3
        assert first[domain][0]['id'] == (22 if domain == 'words' else 2)
        fresh = listing()
        assert fresh['pagination']['total'] == 2
        assert fresh[domain][0]['id'] == (33 if domain == 'words' else 1)
        assert fresh[domain][0]['english' if domain == 'words' else 'introduction'] == 'changed'


@pytest.mark.parametrize('domain', ['words', 'users'])
def test_zero_count_skips_page_read_even_if_another_connection_commits_a_match(
    mysql_app, monkeypatch, domain
):
    module = dictionary if domain == 'words' else auth
    statements, changed = [], False

    @contextmanager
    def paused_reading():
        nonlocal changed
        with reading() as cursor:
            execute = cursor.execute

            def after_count(sql, args=None):
                nonlocal changed
                statements.append(sql)
                result = execute(sql, args)
                if sql.startswith('SELECT COUNT(*)') and not changed:
                    with transaction() as writer:
                        if domain == 'words':
                            writer.execute(
                                "INSERT INTO word (dictid,english,chinese,deleted) VALUES (1,'new-match','新',0)"
                            )
                        else:
                            writer.execute(
                                "INSERT INTO user (username,deleted) VALUES ('new-match',0)"
                            )
                    changed = True
                return result

            cursor.execute = after_count
            yield cursor

    monkeypatch.setattr(module, 'reading', paused_reading)
    with mysql_app.app_context():

        def listing():
            query = ListQuery(page=999, q='new-match')
            return (
                dictionary.get_words(1, query)
                if domain == 'words'
                else auth.list_users({'id': 3, 'type': 'root', 'admin_level': 5}, query=query)
            )

        first = listing()
        assert first[domain] == [] and first['pagination']['total'] == 0
        assert not any('JOIN (SELECT id' in sql for sql in statements)
        fresh = listing()
        assert fresh['pagination']['total'] == 1 and len(fresh[domain]) == 1


def test_optional_committed_index_probes_restore_all_fixture_rows(mysql_app, legacy_database):
    seed(mysql_app, 'smoke')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.connect() as connection:
            before = snapshot(connection)
        result = write_costs(mysql_app, 1)
        assert result['csv_import']['rows'] == 5000 and result['rating_updates']['rows'] == 100
        assert (
            len(result['csv_import']['ms']['samples'])
            == len(result['rating_updates']['ms']['samples'])
            == 1
        )
        with engine.connect() as connection:
            assert snapshot(connection) == before
        sizes = storage(mysql_app)
        assert {row['TABLE_NAME'] for row in sizes['tables']} == {'word', 'user'}
        assert any(row['INDEX_NAME'] == 'ix_word_dict_deleted_id' for row in sizes['indexes'])
    finally:
        engine.dispose()
