"""Question storage boundary; no scoring, permissions or historical reconstruction.

New games capture one MVCC statement's dictionary view. Legacy games explicitly
read live words; snapshot games must never fall back to that source.
"""

from .dictionary_multipliers import stored as stored_multiplier
from .errors import ApiError, GameError
from .legacy_game import invalid_data
from .validation import string

LEGACY, SNAPSHOT = 0, 1

# Use the same expression for state, lobby display and lobby search (including NULL).
DICTNAME_SQL = 'CASE WHEN g.question_mode = 1 THEN g.dictname_snapshot ELSE d.dictname END'


def snapshot_error():
    return GameError(
        'Game question snapshot requires review; run audit-legacy', 409, 'invalid_game_snapshot'
    )


def source(game):
    # Missing only for pre-migration audit input; runtime queries require the new schema.
    mode = game.get('question_mode', LEGACY)
    if type(mode) is not int or mode not in (LEGACY, SNAPSHOT):
        raise snapshot_error()
    return 'snapshot' if mode == SNAPSHOT else 'legacy_live'


def valid_text(value, *, name=False):
    if name and value is None:
        return True  # Preserve missing legacy dictionary names; never invent a title.
    try:
        string(value, 'Snapshot text', minimum=0 if name else 1, strip=False)
        return name or bool(value.strip())
    except ApiError:
        return False


def capture(cursor, dict_id, require_system=False, *, weighted=False):
    # A single non-locking SELECT gives one consistent InnoDB view, even at READ
    # COMMITTED. Do not split name/word reads or introduce dictionary -> user locks.
    cursor.execute(
        """SELECT d.dictname, d.multiplier, d.ownerid, d.difficulty, w.id, w.english, w.chinese
                      FROM dict d LEFT JOIN word w ON w.dictid = d.id AND w.deleted = 0
                      WHERE d.id = %s AND d.deleted = 0 ORDER BY w.id""",
        (dict_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        raise GameError('Dictionary not found', 404, 'not_found')
    # A concurrent approval must not launder a previously personal snapshot into
    # Rated. Still recheck current policy under user -> dictionary locks later.
    if require_system and rows[0]['ownerid'] is not None:
        raise GameError(
            'Rated games require a system dictionary snapshot',
            409,
            'rated_system_dictionary_required',
        )
    if rows[0]['id'] is None:
        raise GameError('Dictionary has no words', 400, 'empty_dictionary')
    name = rows[0]['dictname']
    if not valid_text(name, name=True) or any(
        type(row['id']) is not int
        or row['id'] <= 0
        or not valid_text(row['english'])
        or not valid_text(row['chinese'])
        for row in rows
    ):
        raise GameError(
            'Dictionary data requires review; no game created', 409, 'invalid_dictionary_data'
        )
    # Do not normalize case, whitespace, slash alternatives or CSV newlines.
    multiplier = stored_multiplier(rows[0]['multiplier'])
    result = (
        name,
        [{'id': row['id'], 'english': row['english'], 'chinese': row['chinese']} for row in rows],
        multiplier,
    )
    if weighted:
        difficulty = rows[0]['difficulty']
        if type(difficulty) is not int or not 0 <= difficulty <= 4000:
            raise GameError('Dictionary difficulty requires review', 409, 'invalid_dictionary_data')
        return (*result, difficulty)
    return result


def save(cursor, game_id, words):
    cursor.executemany(
        """INSERT INTO game_question (game_id, position, word_id, english, chinese)
                          VALUES (%s, %s, %s, %s, %s)""",
        [
            (game_id, index, word['id'], word['english'], word['chinese'])
            for index, word in enumerate(words)
        ],
    )


def validate_snapshot(game, word_ids, rows):
    """Validate the transitional ID manifest, not today's dictionary references."""
    if (
        not word_ids
        or len(rows) != len(word_ids)
        or not valid_text(game.get('dictname_snapshot'), name=True)
        or any(type(wid) is not int or wid <= 0 for wid in word_ids)
        or len(set(word_ids)) != len(word_ids)
    ):
        raise snapshot_error()
    for index, (wid, row) in enumerate(zip(word_ids, rows, strict=True)):
        if (
            type(row.get('position')) is not int
            or row['position'] != index
            or type(row.get('word_id')) is not int
            or row['word_id'] != wid
            or not valid_text(row.get('english'))
            or not valid_text(row.get('chinese'))
        ):
            raise snapshot_error()
    return [
        {'id': row['word_id'], 'english': row['english'], 'chinese': row['chinese']} for row in rows
    ]


def load(cursor, game):
    if source(game) == 'snapshot':
        if '_questions' not in game:
            cursor.execute(
                """SELECT position, word_id, english, chinese FROM game_question
                              WHERE game_id = %s ORDER BY position""",
                (game['id'],),
            )
            game['_questions'] = validate_snapshot(game, game['wordlist'], cursor.fetchall())
        # Only cached inside this read/command, never across transactions.
        return game['_questions']
    ids = game['wordlist']
    if not ids:
        return []
    placeholders = ', '.join(['%s'] * len(ids))
    cursor.execute('SELECT id, english, chinese FROM word WHERE id IN (' + placeholders + ')', ids)
    words = {word['id']: word for word in cursor.fetchall()}
    if any(wid not in words for wid in ids):
        raise invalid_data()  # Missing references need review, not silently shortened question lists.
    return [words[wid] for wid in ids]


def prompt(word):
    return {'id': word['id'], 'chinese': word['chinese']}
