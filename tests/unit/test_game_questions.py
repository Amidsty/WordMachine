from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from wm_app.services import game_questions as questions
from wm_app.services.errors import GameError


def snapshot():
    return [
        {'position': 0, 'word_id': 11, 'english': ' Apple/PEAR ', 'chinese': ' 多行\r\n,🍎 '},
        {'position': 1, 'word_id': 22, 'english': 'banana', 'chinese': '香蕉'},
    ]


def test_snapshot_preserves_exact_text_and_prompts_do_not_leak_english():
    rows = snapshot()
    before = deepcopy(rows)
    words = questions.validate_snapshot({'dictname_snapshot': None}, [11, 22], rows)
    assert words[0] == {'id': 11, 'english': ' Apple/PEAR ', 'chinese': ' 多行\r\n,🍎 '}
    assert questions.prompt(words[0]) == {'id': 11, 'chinese': ' 多行\r\n,🍎 '}
    assert rows == before


@pytest.mark.parametrize(
    'change',
    [
        {'position': 1},
        {'position': True},
        {'word_id': 22},
        {'word_id': True},
        {'english': None},
        {'english': ''},
        {'english': '  '},
        {'english': '\ud800'},
        {'chinese': '\x00'},
        {'chinese': '字' * 256},
    ],
)
def test_snapshot_corruption_never_falls_back_to_live_words(change):
    rows = snapshot()
    rows[0].update(change)
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    with pytest.raises(GameError) as error:
        questions.load(cursor, {'id': 1, 'question_mode': 1, 'wordlist': [11, 22]})
    assert error.value.code == 'invalid_game_snapshot'
    assert (
        cursor.execute.call_count == 1 and 'FROM game_question' in cursor.execute.call_args.args[0]
    )


@pytest.mark.parametrize(
    'ids,rows',
    [
        ([], []),
        ([11], []),
        ([11, 22], snapshot()[:1]),
        ([11], snapshot()),
        ([11, 11], snapshot()),
        ([True, 22], snapshot()),
    ],
)
def test_snapshot_requires_complete_unique_ordered_manifest(ids, rows):
    with pytest.raises(GameError, match='snapshot requires review'):
        questions.validate_snapshot({}, ids, rows)


@pytest.mark.parametrize('mode', [None, True, '1', -1, 2])
def test_unknown_mode_is_not_treated_as_legacy(mode):
    with pytest.raises(GameError):
        questions.source({'question_mode': mode})


def test_snapshot_cache_is_only_on_the_current_game_object():
    cursor = MagicMock()
    cursor.fetchall.return_value = snapshot()
    game = {'id': 1, 'question_mode': 1, 'wordlist': [11, 22]}
    assert questions.load(cursor, game) == questions.load(cursor, game)
    assert cursor.execute.call_count == 1
    questions.load(cursor, {'id': 1, 'question_mode': 1, 'wordlist': [11, 22]})
    assert cursor.execute.call_count == 2


def test_legacy_missing_words_require_review_not_a_shortened_question_list():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{'id': 11, 'english': 'apple', 'chinese': '苹果'}]
    with pytest.raises(GameError) as error:
        questions.load(cursor, {'id': 1, 'question_mode': 0, 'wordlist': [11, 22]})
    assert error.value.code == 'legacy_data_error'


@pytest.mark.parametrize(
    'rows,code',
    [
        ([], 'not_found'),
        ([{'id': None}], 'empty_dictionary'),
        (
            [{'id': 11, 'dictname': 'name', 'english': None, 'chinese': '字'}],
            'invalid_dictionary_data',
        ),
    ],
)
def test_capture_rejects_missing_empty_or_invalid_sources(rows, code):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    with pytest.raises(GameError) as error:
        questions.capture(cursor, 1)
    assert error.value.code == code
    assert cursor.execute.call_count == 1
    assert 'LEFT JOIN word' in cursor.execute.call_args.args[0]
