import json
from datetime import datetime
from unittest.mock import MagicMock

from wm_app.audit import inspect_legacy


def dataset():
    users = [
        {'id': 1, 'username': 'first', 'rating': 1500, 'gamehistory': '[1]', 'ratinghistory': None}
    ]
    dictionaries = [{'id': 1}]
    words = [{'id': 1, 'dictid': 1, 'english': 'apple', 'chinese': '苹果'}]
    games = [
        {
            'id': 1,
            'ownerid': 1,
            'dictid': 1,
            'users': '[1]',
            'wordlist': '[1]',
            'result': '[]',
            'status': -1,
        }
    ]
    return users, dictionaries, words, games


def test_valid_legacy_rows():
    report = inspect_legacy(*dataset())
    assert report['issue_count'] == 0
    assert report['counts'] == {'users': 1, 'dictionaries': 1, 'words': 1, 'games': 1}


def test_audit_reports_corruption_without_repairing_rows():
    users, dictionaries, words, games = dataset()
    users.append({**users[0], 'id': 2})
    users[0]['ratinghistory'] = json.dumps([{'game_id': 1}, {'game_id': 1}])
    games[0]['result'] = '[{"uid": 1, "word_id": 1, "result": true}]'
    games[0]['status'] = 0
    before = json.dumps([users, dictionaries, words, games])
    report = inspect_legacy(users, dictionaries, words, games)
    kinds = {issue['kind'] for issue in report['issues']}
    assert {
        'duplicate_username',
        'duplicate_settlement',
        'missing_or_invalid_perf',
        'settled_unfinished_game',
    } <= kinds
    assert before == json.dumps([users, dictionaries, words, games])
    assert 'first' not in json.dumps(report)  # Report IDs, not profile data.


def test_malformed_arrays_and_references_are_reported():
    users, dictionaries, words, games = dataset()
    users[0]['gamehistory'] = '{broken'
    games[0]['users'] = '[{}, 999, 999]'
    games[0]['wordlist'] = '{}'
    report = inspect_legacy(users, dictionaries, words, games)
    assert {'invalid_json_array', 'invalid_reference', 'duplicate_reference'} <= {
        i['kind'] for i in report['issues']
    }


def test_snapshot_audit_uses_captured_ids_not_deleted_sources():
    users, dictionaries, words, games = dataset()
    games[0].update(question_mode=1, dictname_snapshot='private title')
    snapshot = [
        {
            'game_id': 1,
            'position': 0,
            'word_id': 1,
            'english': 'private answer',
            'chinese': '私有题面',
        }
    ]
    report = inspect_legacy(users, [], [], games, snapshot)
    assert report['issue_count'] == 0
    snapshot[0]['position'] = 1
    report = inspect_legacy(users, [], [], games, snapshot)
    assert {item['kind'] for item in report['issues']} == {'invalid_question_snapshot'}
    assert 'private' not in json.dumps(report) and '私有' not in json.dumps(
        report, ensure_ascii=False
    )


def test_audit_reports_invalid_modes_and_orphan_snapshots_without_repairs():
    users, dictionaries, words, games = dataset()
    games[0]['question_mode'] = 2
    rows = [{'game_id': 999, 'position': 0, 'word_id': 1, 'english': 'apple', 'chinese': '苹果'}]
    report = inspect_legacy(users, dictionaries, words, games, rows)
    assert {item['kind'] for item in report['issues']} == {
        'unknown_question_mode',
        'missing_game_reference',
    }
    assert games[0]['question_mode'] == 2


def test_audit_reads_relations_not_the_archived_json_and_reports_missing_rows():
    users, dictionaries, words, games = dataset()
    games[0].update(participant_mode=1, participant_count=1, users='invalid archived JSON')
    rows = [
        {
            'game_id': 1,
            'user_id': 1,
            'position': 0,
            'joined_at': None,
            'recorded_at': datetime(2026, 1, 1),
        }
    ]
    assert inspect_legacy(users, dictionaries, words, games, members=rows)['issue_count'] == 0
    report = inspect_legacy(users, dictionaries, words, games)
    assert 'invalid_game_participants' in {issue['kind'] for issue in report['issues']}
    assert games[0]['users'] == 'invalid archived JSON'


def test_answer_audit_ignores_archive_and_reports_rows_without_answer_contents():
    users, dictionaries, words, games = dataset()
    games[0].update(
        question_mode=1,
        participant_mode=1,
        participant_count=1,
        answer_mode=1,
        answer_count=1,
        status=1,
        users='broken archive',
        result='broken archive',
    )
    now = datetime(2026, 1, 1)
    questions = [
        {
            'game_id': 1,
            'position': 0,
            'word_id': 1,
            'english': 'private answer',
            'chinese': '私有题面',
        }
    ]
    members = [{'game_id': 1, 'user_id': 1, 'position': 0, 'joined_at': None, 'recorded_at': now}]
    answers = [
        {
            'game_id': 1,
            'position': 0,
            'user_id': 1,
            'answer': 'private submission',
            'correct': 0,
            'usercombo': 0,
            'globalcombo': 0,
            'perf_delta': -1.0,
            'perf': 1499.0,
            'rating_version': 'legacy-v1',
            'answered_at': None,
            'recorded_at': now,
        }
    ]
    assert inspect_legacy(users, [], [], games, questions, members, answers)['issue_count'] == 0
    before = json.dumps(games)
    report = inspect_legacy(users, [], [], games, questions, members)
    assert {item['kind'] for item in report['issues']} == {'invalid_game_answers'}
    games[0].update(answer_mode=0, answer_count=None, result='[]')
    report = inspect_legacy(
        users, [], [], games, questions, members, [*answers, {**answers[0], 'game_id': 999}]
    )
    assert {'unexpected_game_answers', 'missing_game_reference'} <= {
        item['kind'] for item in report['issues']
    }
    assert 'private' not in json.dumps(report) and 'broken archive' in before


def test_cli_runs_read_only_and_always_rolls_back(app, monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = list(dataset())
    cursor.fetchone.return_value = None  # Pre-snapshot schema.
    monkeypatch.setattr('wm_app.audit.get_db_connection', lambda: connection)
    result = app.test_cli_runner().invoke(args=['audit-legacy'])
    assert result.exit_code == 0
    assert json.loads(result.output)['issue_count'] == 0
    assert cursor.execute.call_args_list[0].args == ('SET TRANSACTION READ ONLY',)
    assert all(
        call.args[0].startswith(('SELECT ', 'SET TRANSACTION READ ONLY'))
        for call in cursor.execute.call_args_list
    )
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
