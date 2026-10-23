"""Explicit, single-game participation conversion. Never called by HTTP/Socket."""

from ..db import reading, transaction
from . import game_participants as participants
from . import game_requests
from .errors import GameError
from .legacy_game import unique_ids


def convert_game(game_id, *, apply=False, expected_version=None):
    game_requests.validate_options(expected_version=expected_version)
    if apply and expected_version is None:
        raise GameError(
            'Applying conversion requires expected_version from a reviewed dry run',
            400,
            'invalid_parameters',
        )
    with transaction() if apply else reading() as cursor:
        if not apply:
            cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute(
            'SELECT * FROM game WHERE id = %s' + (' FOR UPDATE' if apply else ''), (game_id,)
        )
        game = cursor.fetchone()
        if game is None:
            raise GameError('Game not found', 404, 'not_found')
        game_requests.check_version(game, expected_version)
        if participants.relational(game):
            participants.load_many(cursor, [game])
            return {
                'game_id': game_id,
                'status': 'already_normalized',
                'participants': len(game['users']),
                'version': game['version'],
            }
        ids = unique_ids(game['users'])
        participants.validate_ids(ids, game['ownerid'])
        # Preserve exact order and raw JSON. Never overwrite a partial/custom copy.
        cursor.execute(
            'SELECT user_id FROM game_participant WHERE game_id = %s LIMIT 1', (game_id,)
        )
        if cursor.fetchone() is not None:
            raise participants.invalid_participants()
        placeholders = ', '.join(['%s'] * len(ids))
        cursor.execute('SELECT id FROM user WHERE id IN (' + placeholders + ')', ids)
        if {row['id'] for row in cursor.fetchall()} != set(ids):
            raise participants.invalid_participants()
        if game['version'] == game_requests.MAX_VERSION:
            raise GameError('Game version exhausted', 409, 'invalid_game_state')
        report = {
            'game_id': game_id,
            'status': 'ready',
            'participants': len(ids),
            'version': game['version'],
        }
        if not apply:
            return report
        # Version check and conversion occur under the same game lock as commands.
        # All rows and metadata commit together; raw users JSON remains an archive.
        version = game['version'] + 1
        cursor.execute(
            'UPDATE game SET participant_mode = 1, participant_count = %s, version = %s WHERE id = %s',
            (len(ids), version, game_id),
        )
        game.update(participant_mode=1, participant_count=len(ids), users=ids)
        participants.save(cursor, game, historical=True)
        return {**report, 'status': 'converted', 'version': version}
