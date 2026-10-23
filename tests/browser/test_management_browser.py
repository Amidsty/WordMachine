"""SQL cross-checks are separate from UI/API observations and use synthetic data only."""

import pytest

from tests.integration.test_game_mysql import query
from wm_app.security.passwords import verify_password

pytestmark = pytest.mark.mysql


@pytest.fixture
def unchanged_history(mysql_app):
    users_sql = """SELECT id, rating, type, ratinghistory, gamehistory, rating_ledger_id
                   FROM user WHERE id <= 3 ORDER BY id"""
    game_sql = """SELECT id, ownerid, dictid, users, wordlist, result, perf, ratingdelta, version,
                 question_mode, participant_mode, answer_mode, settlement_mode FROM game ORDER BY id"""
    users, games = query(mysql_app, users_sql), query(mysql_app, game_sql)
    yield
    assert query(mysql_app, users_sql) == users
    assert query(mysql_app, game_sql) == games
    # Only the harness cancels the inherited game to prevent automatic lobby navigation.
    assert query(mysql_app, 'SELECT status FROM game') == [{'status': 2}]
    for table in (
        'game_request',
        'game_question',
        'game_participant',
        'game_answer',
        'game_settlement',
        'game_rating',
    ):
        assert query(mysql_app, f'SELECT COUNT(*) AS n FROM {table}')[0]['n'] == 0


def test_real_browser_registration_and_password(mysql_app, run_browser, unchanged_history):
    run_browser('auth.spec.ts')
    users = query(mysql_app, 'SELECT * FROM user ORDER BY id')
    assert len(users) == 4
    user = users[-1]
    assert user['username'] == 'browser-account'
    assert user['type'] == 'normal' and user['rating'] == 0 and user['deleted'] == 0
    assert user['introduction'] == '<img src=x onerror="window.injected=1"> saved profile'
    assert user['pwhash'].startswith('scrypt:32768:8:1$')
    assert verify_password(user['pwhash'], ' changed secret ')
    assert not verify_password(user['pwhash'], 'changed secret')
    assert not verify_password(user['pwhash'], ' register secret ')
    assert not query(mysql_app, 'SELECT token_hash FROM auth_session')
    assert all(row['introduction'] is None for row in users[:3])
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM dict')[0]['n'] == 1


def test_real_browser_admin_revocation(mysql_app, run_browser, unchanged_history):
    run_browser('admin.spec.ts')
    users = query(mysql_app, 'SELECT id, introduction, pwhash, deleted FROM user ORDER BY id')
    assert len(users) == 3 and all(row['deleted'] == 0 for row in users)
    assert all(row['introduction'] is None for row in users)
    assert verify_password(users[0]['pwhash'], ' admin reset secret ')
    assert not verify_password(users[0]['pwhash'], 'test-password')
    assert not verify_password(users[0]['pwhash'], 'admin reset secret')
    assert all(verify_password(row['pwhash'], 'test-password') for row in users[1:])
    assert not query(mysql_app, 'SELECT token_hash FROM auth_session')


def test_real_browser_dictionary_permissions(mysql_app, run_browser, unchanged_history):
    run_browser('dictionaries.spec.ts')
    dictionaries = query(mysql_app, 'SELECT id, dictname, ownerid, deleted FROM dict ORDER BY id')
    assert (
        len(dictionaries) == 2
    )  # No anonymous, CSRF-failed, forged or automatic duplicate create.
    system, owned = dictionaries
    assert system == {'id': 1, 'dictname': '管理员系统词典', 'ownerid': None, 'deleted': 1}
    assert owned['ownerid'] == 1 and owned['dictname'] == '管理员维护 %_!' and owned['deleted'] == 1
    words = query(
        mysql_app,
        'SELECT english, chinese, deleted FROM word WHERE dictid = %s ORDER BY id',
        (owned['id'],),
    )
    expected = [('edited word', '已编辑')]
    expected += [
        (f'word{index:02}', '管理员修改' if index == 0 else f'词{index}') for index in range(21)
    ]
    expected += [('say "hi", please', '第一行\n第二行')]
    assert words == [
        {'english': english, 'chinese': chinese, 'deleted': 1} for english, chinese in expected
    ]
    system_words = query(
        mysql_app, 'SELECT english, chinese, deleted FROM word WHERE dictid = 1 ORDER BY id'
    )
    assert system_words == [
        {'english': english, 'chinese': chinese, 'deleted': 1}
        for english, chinese in [
            ('apple', '苹果'),
            ('banana', '香蕉'),
            ('cat', '猫'),
            ('root-created', '管理员新增'),
            ('root-imported', '管理员导入'),
        ]
    ]
