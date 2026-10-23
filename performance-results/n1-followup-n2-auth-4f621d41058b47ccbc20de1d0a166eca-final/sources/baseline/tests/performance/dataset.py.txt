"""Deterministic, bounded synthetic fixtures; not a production data generator."""

from dataclasses import dataclass
from datetime import datetime
from itertools import islice

from wm_app.db import reading, transaction

SIZES = {
    'smoke': {'users': 200, 'dictionaries': 40, 'words': 1000, 'games': 120},
    'medium': {'users': 20000, 'dictionaries': 1000, 'words': 100000, 'games': 10000},
    'large': {'users': 100000, 'dictionaries': 5000, 'words': 500000, 'games': 50000},
}


@dataclass(frozen=True)
class Distribution:
    hot_percent: int = 50
    spread: bool = False
    active_every: int = 0
    null_every: int = 17
    needle_every: int = 97
    wide: bool = False

    def deleted(self, index):
        if index % self.null_every == 0:
            return None
        return int(index % self.active_every != 0) if self.active_every else int(index % 10 == 0)

    def dictionary_id(self, index, counts):
        # A permutation, not random state: 104729 is coprime to all supported word counts.
        position = index * 104729 % counts['words'] if self.spread else index
        hot = counts['words'] * self.hot_percent // 100
        return 10 if position < hot else 11 + (position - hot) % (counts['dictionaries'] - 1)

    def word_text(self, index):
        english, chinese = label('entry', index, self.needle_every), f'词{index}'
        if self.wide:
            english = None if index % 37 == 0 else english.ljust(255, 'x')
            chinese = None if index % 41 == 0 else chinese.ljust(255, '汉')
        return english, chinese


DISTRIBUTIONS = {
    'standard': Distribution(),
    'spread': Distribution(spread=True),
    'sparse': Distribution(hot_percent=1, spread=True),
    'dominant': Distribution(hot_percent=90, spread=True),
    'deleted': Distribution(spread=True, active_every=20, null_every=7),
    'wide': Distribution(spread=True, needle_every=2, wide=True),
}


def chunks(rows, size=1000):
    iterator = iter(rows)
    while batch := list(islice(iterator, size)):
        yield batch


def insert(cursor, sql, rows):
    for batch in chunks(rows):
        cursor.executemany(sql, batch)


def label(kind, index, needle_every=97):
    return (
        f'{kind}-{index}'
        + (' needle' if index % needle_every == 0 else '')
        + (' %_!' if index % 193 == 0 else '')
    )


def seed(app, size, distribution='standard'):
    counts = SIZES[size]
    profile = DISTRIBUTIONS[distribution]
    n_dicts, n_words, n_games = counts['dictionaries'], counts['words'], counts['games']
    with app.app_context(), transaction() as cursor:
        cursor.execute('UPDATE game SET status = 2 WHERE id = 1')
        insert(
            cursor,
            'INSERT INTO user (id, username, introduction, pwhash, rating, type, deleted) VALUES (%s, %s, %s, %s, %s, %s, %s)',
            (
                (
                    10 + i,
                    label('person', i, profile.needle_every),
                    '长' * 255 if profile.wide else 'synthetic profile',
                    'x' * 162 if profile.wide else None,
                    None if i % 101 == 0 else i % 2000,
                    'normal',
                    profile.deleted(i),
                )
                for i in range(counts['users'])
            ),
        )
        insert(
            cursor,
            'INSERT INTO dict (id, dictname, ownerid, deleted) VALUES (%s, %s, %s, %s)',
            (
                (
                    10 + i,
                    label('dictionary', i) if i == 0 or i % 101 else None,
                    (None, 1, 2)[i % 3],
                    int(i != 0 and i % 23 == 0),
                )
                for i in range(n_dicts)
            ),
        )
        # Standard exactly retains the original half-contiguous-hot fixture.
        # Other profiles vary scope density, ID locality, text width and selectivity.
        insert(
            cursor,
            'INSERT INTO word (id, dictid, english, chinese, deleted) VALUES (%s, %s, %s, %s, %s)',
            (
                (
                    1000000 + i,
                    profile.dictionary_id(i, counts),
                    *profile.word_text(i),
                    profile.deleted(i),
                )
                for i in range(n_words)
            ),
        )
        insert(
            cursor,
            'INSERT INTO game (id, ownerid, dictid, users, wordlist, result, status, '
            'question_mode, dictname_snapshot, participant_mode, participant_count, answer_mode, answer_count) '
            'VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (
                (
                    100000 + i,
                    10 + i % n_dicts,
                    None if i % 3 else '[1, 2]',
                    '[11]',
                    None if i % 3 else '[]',
                    0 if i % 20 == 0 else -1 if i % 20 == 1 else 2,
                    int(i % 3 != 0),
                    label('snapshot', i) if i % 3 else None,
                    int(i % 3 != 0),
                    2 if i % 3 else None,
                    int(i % 3 != 0),
                    0 if i % 3 else None,
                )
                for i in range(n_games)
            ),
        )
        insert(
            cursor,
            'INSERT INTO game_participant (game_id, user_id, position, joined_at, recorded_at) VALUES (%s, %s, %s, NULL, %s)',
            (
                (100000 + i, uid, uid - 1, datetime(2020, 1, 1))
                for i in range(n_games)
                if i % 3
                for uid in (1, 2)
            ),
        )
        insert(
            cursor,
            'INSERT INTO game_question (game_id, position, word_id, english, chinese) VALUES (%s, 0, 11, %s, %s)',
            ((100000 + i, 'apple', '苹果') for i in range(n_games) if i % 3),
        )
    # Setup only, never on a normal application read. Refresh optimizer statistics explicitly.
    with app.app_context(), reading() as cursor:
        cursor.execute('ANALYZE TABLE user, dict, word, game, game_participant, game_question')
        assert all(
            row['Msg_type'] == 'status' and row['Msg_text'] == 'OK' for row in cursor.fetchall()
        )
    return counts
