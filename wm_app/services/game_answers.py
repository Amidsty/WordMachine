"""Answer storage boundary; game.py owns turns, authorization and scoring.

Mode 1 is append-only through the application, never a fallback to result JSON.
Both paths expose the existing answer protocol, not database rows/timestamps.
"""

import json
import math
from datetime import datetime

from . import weighted_games, weighted_rating
from .dictionary_multipliers import PERF_VERSION, game_multiplier
from .errors import GameError
from .legacy_game import invalid_data, json_list
from .rating import CUMULATIVE_PERF_VERSION, MULTIPLIED_PERF_VERSION, RATING_VERSION

MAX_INT = 2147483647
SCORING_FIELDS = ('usercombo', 'globalcombo', 'perf_delta', 'perf', 'rating_version')
ANSWER_FIELDS = frozenset(('uid', 'word_id', 'answer', 'result', *SCORING_FIELDS))


def invalid_answers():
    return GameError('Game answers require review; run audit-legacy', 409, 'invalid_game_answers')


def relational(game):
    # Missing metadata is only for pre-migration audit/unit-test input.
    mode, count = game.get('answer_mode', 0), game.get('answer_count')
    if (
        type(mode) is not int
        or mode not in (0, 1)
        or (mode == 0 and count is not None)
        or (
            mode == 1
            and (
                type(count) is not int
                or not 0 <= count <= MAX_INT
                or type(game.get('question_mode')) is not int
                or game['question_mode'] != 1
                or type(game.get('participant_mode')) is not int
                or game['participant_mode'] != 1
            )
        )
    ):
        raise invalid_answers()
    return mode == 1


def _entry(game, index, row):
    multiplier = game_multiplier(game)
    expected_rules = (
        (PERF_VERSION, MULTIPLIED_PERF_VERSION)
        if multiplier is not None
        else (RATING_VERSION, CUMULATIVE_PERF_VERSION)
    )
    weighted = weighted_games.enabled(game)
    if weighted:
        expected_rules = (weighted_games.rules(game).PERF_VERSION,)
    if (
        row.get('game_id') != game['id']
        or type(row.get('position')) is not int
        or row['position'] != index
        or index >= len(game['wordlist'])
        or not game['users']
        or type(row.get('user_id')) is not int
        or row['user_id'] != game['users'][index % len(game['users'])]
        or type(row.get('correct')) not in (int, bool)
        or row['correct'] not in (0, 1)
        or row.get('rating_version') not in expected_rules
        or not isinstance(row.get('recorded_at'), datetime)
        or (row.get('answered_at') is not None and not isinstance(row['answered_at'], datetime))
    ):
        raise invalid_answers()
    for field in ('usercombo', 'globalcombo'):
        if type(row.get(field)) is not int or not 0 <= row[field] <= MAX_INT:
            raise invalid_answers()
    for field in ('perf_delta', 'perf'):
        if type(row.get(field)) not in (int, float) or not math.isfinite(row[field]):
            raise invalid_answers()
    raw = row.get('raw_perf_delta')
    if multiplier is None or weighted:
        if raw is not None:
            raise invalid_answers()
    elif (
        type(raw) not in (int, float)
        or not math.isfinite(raw)
        or row['perf_delta'] != (raw if multiplier == 1 else raw * float(multiplier))
    ):
        raise invalid_answers()
    answer = row.get('answer')
    try:
        if (
            not isinstance(answer, str)
            or not answer
            or answer != answer.strip().lower()
            or len(answer.encode('utf-8')) > 65535
        ):
            raise invalid_answers()
    except UnicodeEncodeError:
        raise invalid_answers() from None
    return {
        'uid': row['user_id'],
        'word_id': game['wordlist'][index],
        'answer': answer,
        'result': bool(row['correct']),
        **{field: row[field] for field in SCORING_FIELDS},
        **({'raw_perf_delta': raw} if multiplier is not None and not weighted else {}),
    }


def validate_rows(game, rows):
    """Check a complete committed prefix without rejudging answers or rerolling Perf."""
    if (
        not relational(game)
        or len(rows) != game['answer_count']
        or len(rows) > len(game['wordlist'])
        or game['status'] not in (-1, 0, 1, 2)
        or (game['status'] in (-1, 2) and rows)
        or (game['status'] == 0 and len(rows) == len(game['wordlist']))
    ):
        raise invalid_answers()
    entries = [_entry(game, index, row) for index, row in enumerate(rows)]
    validate_rule_order(
        entries,
        weighted=weighted_games.enabled(game),
        perf_version=weighted_games.rules(game).PERF_VERSION
        if weighted_games.enabled(game)
        else None,
    )
    return entries


def validate_rule_order(entries, *, weighted=False, perf_version=None):
    if weighted:
        expected = perf_version or weighted_rating.PERF_VERSION
        if expected not in weighted_games.PERF_VERSIONS or any(
            e.get('rating_version') != expected for e in entries
        ):
            raise invalid_answers()
        return
    if any(e.get('rating_version') in weighted_games.PERF_VERSIONS for e in entries):
        raise invalid_answers()
    cumulative = False
    for entry in entries:
        if entry.get('rating_version') in (CUMULATIVE_PERF_VERSION, MULTIPLIED_PERF_VERSION):
            cumulative = True
        elif cumulative:
            # Mixed old/new writers must not silently reintroduce baseline resets.
            raise invalid_answers()


def read_rows(cursor, game_id):
    cursor.execute('SELECT * FROM game_answer WHERE game_id = %s ORDER BY position', (game_id,))
    return list(cursor.fetchall())


def load(cursor, game):
    if relational(game):
        return validate_rows(game, read_rows(cursor, game['id']))
    result = json_list(game['result'])
    if len(result) > len(game['wordlist']) or any(not isinstance(entry, dict) for entry in result):
        raise invalid_data()
    validate_rule_order(result)
    return result


def encode(game, index, entry, *, answered_at, recorded_at):
    """Map one complete protocol entry without normalizing or inventing values."""
    fields = ANSWER_FIELDS | (
        {'raw_perf_delta'}
        if game_multiplier(game) is not None and not weighted_games.enabled(game)
        else set()
    )
    if (
        not isinstance(entry, dict)
        or set(entry) != fields
        or type(entry['word_id']) is not int
        or not 0 <= index < len(game['wordlist'])
        or entry['word_id'] != game['wordlist'][index]
        or type(entry['result']) is not bool
    ):
        raise invalid_answers()
    row = {
        'game_id': game['id'],
        'position': index,
        'user_id': entry['uid'],
        'correct': entry['result'],
        'answered_at': answered_at,
        'recorded_at': recorded_at,
        'answer': entry['answer'],
        **{field: entry[field] for field in SCORING_FIELDS},
        'raw_perf_delta': entry.get('raw_perf_delta'),
    }
    _entry(game, index, row)
    return row


def insert(cursor, row):
    cursor.execute(
        """INSERT INTO game_answer
        (game_id, position, user_id, answer, correct, usercombo, globalcombo,
         perf_delta, perf, rating_version, answered_at, recorded_at, raw_perf_delta)
        VALUES (%(game_id)s, %(position)s, %(user_id)s, %(answer)s, %(correct)s, %(usercombo)s,
                %(globalcombo)s, %(perf_delta)s, %(perf)s, %(rating_version)s, %(answered_at)s, %(recorded_at)s, %(raw_perf_delta)s)""",
        row,
    )


def append(cursor, game, entry):
    """Called with the game lock and all ordered user locks already held.

    Insert once; do not rewrite prior rows. The last-answer settlement, count,
    version and request receipt are committed by the caller's same transaction.
    """
    if relational(game):
        index = len(game['result'])
        now = datetime.utcnow()
        if game['answer_count'] != index:
            raise invalid_answers()
        row = encode(game, index, entry, answered_at=now, recorded_at=now)
        insert(cursor, row)
        cursor.execute('UPDATE game SET answer_count = %s WHERE id = %s', (index + 1, game['id']))
        game['answer_count'] = index + 1
    else:
        cursor.execute(
            'UPDATE game SET result = %s WHERE id = %s',
            (json.dumps([*game['result'], entry]), game['id']),
        )
    game['result'].append(entry)
