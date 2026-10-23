from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from wm_app.services import game_participants as participants
from wm_app.services import participant_conversion
from wm_app.services.errors import GameError


def row(uid, position, gid=7):
    return {
        'game_id': gid,
        'user_id': uid,
        'position': position,
        'joined_at': None,
        'recorded_at': datetime(2026, 1, 1),
    }


def normalized(**changes):
    return {
        'id': 7,
        'ownerid': 1,
        'participant_mode': 1,
        'participant_count': 2,
        'users': '[1, 2]',
        **changes,
    }


@pytest.mark.parametrize(
    'changes',
    [
        {'participant_mode': None},
        {'participant_mode': True},
        {'participant_mode': '1'},
        {'participant_mode': 2},
        {'participant_mode': 0, 'participant_count': 1},
        {'participant_count': None},
        {'participant_count': 0},
        {'participant_count': True},
    ],
)
def test_invalid_metadata_cannot_choose_a_fallback_source(changes):
    with pytest.raises(GameError) as error:
        participants.relational(normalized(**changes))
    assert error.value.code == 'invalid_game_participants'


@pytest.mark.parametrize(
    'rows',
    [
        [],
        [row(1, 0)],
        [row(1, 0), row(1, 1)],
        [row(1, 0), row(2, 3)],
        [row(2, 0), row(3, 1)],
        [row(True, 0), row(2, 1)],
        [{**row(1, 0), 'recorded_at': None}, row(2, 1)],
        [{**row(1, 0), 'joined_at': 'unknown'}, row(2, 1)],
    ],
)
def test_corruption_never_uses_the_archived_json(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    with pytest.raises(GameError) as error:
        participants.load_many(cursor, [normalized()])
    assert error.value.code == 'invalid_game_participants'
    assert cursor.execute.call_count == 1
    assert 'game_participant' in cursor.execute.call_args.args[0]


def test_mixed_page_batches_only_normalized_games_and_preserves_order():
    cursor = MagicMock()
    cursor.fetchall.return_value = [row(2, 0, 4), row(1, 1, 4), row(1, 0), row(3, 1)]
    games = [{'id': 9, 'users': '[3]'}, normalized(id=4, users='bad archived JSON'), normalized()]
    participants.load_many(cursor, games)
    assert [game['users'] for game in games] == [[3], [2, 1], [1, 3]]
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == [4, 7]


def test_reference_locks_precede_child_updates_and_follow_sorted_user_ids():
    cursor = MagicMock()
    current = normalized(users=[3, 2, 1], _participants=[row(2, 0), row(1, 1)])
    participants.save(cursor, current)
    calls = [call.args for call in cursor.execute.call_args_list]
    assert [params for sql, params in calls[:3]] == [(1,), (2,), (3,)]
    assert all(sql.endswith('FOR SHARE') for sql, _ in calls[:3])
    assert 'position = position +' in calls[3][0]
    assert not any(
        sql.startswith('DELETE') for sql, _ in calls
    )  # Reordering preserves row identity/timestamps.
    assert current['participant_count'] == 3
    assert current['_participants'][1]['joined_at'] is None
    assert current['_participants'][0]['joined_at'] is not None


def test_conversion_defaults_to_read_only_and_reports_no_personal_data(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {
            'id': 7,
            'ownerid': 1,
            'version': 9,
            'users': '[2,1]',
            'participant_mode': 0,
            'participant_count': None,
        },
        None,
    ]
    cursor.fetchall.return_value = [{'id': 1}, {'id': 2}]

    @contextmanager
    def reading():
        yield cursor

    monkeypatch.setattr(participant_conversion, 'reading', reading)
    report = participant_conversion.convert_game(7)
    assert report == {'game_id': 7, 'status': 'ready', 'participants': 2, 'version': 9}
    calls = [call.args[0] for call in cursor.execute.call_args_list]
    assert calls[0] == 'SET TRANSACTION READ ONLY'
    assert all(sql.startswith(('SET TRANSACTION READ ONLY', 'SELECT')) for sql in calls)
    assert not any('FOR UPDATE' in sql for sql in calls)


def test_conversion_apply_requires_reviewed_version_before_connecting(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(participant_conversion, 'transaction', connect)
    with pytest.raises(GameError) as error:
        participant_conversion.convert_game(7, apply=True)
    assert error.value.code == 'invalid_parameters'
    connect.assert_not_called()
