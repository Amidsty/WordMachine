"""Shared game operations against the existing schema.

This adapter is transitional: legacy JSON and scoring remain unchanged. Durable
receipts/versioning and immutable new-game questions are shared by all commands.
New-game participation/answers and all future settlements are relational.
Legacy participation/answer conversion is explicit, never an automatic read repair.
No DDL or historical repair happens at runtime.
"""

import json
import random

from ..db import reading, transaction
from ..security.permissions import can_end_game
from ..utils import check_answer
from . import (
    game_answers,
    game_names,
    game_participants,
    game_questions,
    game_rating_policy,
    game_requests,
    game_settlements,
    rated_eligibility,
    weighted_games,
)
from .auth import public_person
from .dictionary_multipliers import game_multiplier
from .dictionary_multipliers import metadata as multiplier_metadata
from .errors import GameError, text
from .game_settlements import final_perfs as _perfs
from .legacy_game import invalid_data as _invalid_data
from .legacy_game import json_list as _list
from .legacy_game import unique_ids
from .rating import score_answer

WAITING, RUNNING, FINISHED, CANCELLED = -1, 0, 1, 2


def _decode_game(row, cursor=None):
    if row is None:
        raise GameError('Game not found', 404, 'not_found')
    game = dict(row)
    game_names.stored(game)
    game_questions.source(game)
    game_multiplier(game)
    game_rating_policy.rated(game)
    game_participants.load_many(cursor, [game])
    game['wordlist'] = unique_ids(game['wordlist'])
    game['result'] = game_answers.load(cursor, game)
    weighted_games.load(cursor, game)
    game_settlements.load(cursor, game)
    return game


def _locked_game(cursor, game_id):
    cursor.execute('SELECT * FROM game WHERE id = %s FOR UPDATE', (game_id,))
    return _decode_game(cursor.fetchone(), cursor)


def _require_status(game, status):
    if game['status'] != status:
        raise GameError('Operation is not allowed in the current game state')


def _require_participant(game, uid):
    if uid not in game['users']:
        raise GameError('Not in game', 403, 'forbidden')


def _lobby_action_error(game, uid, action):
    """Shared lobby preconditions; full JSON integrity/transaction checks remain in commands."""
    if action not in ('join', 'leave', 'start', 'cancel'):
        raise ValueError('Unsupported lobby action')
    if game['status'] != WAITING:
        return GameError('Operation is not allowed in the current game state')
    joined, owner = uid in game['users'], uid == game['ownerid']
    if action == 'join' and joined:
        return GameError('Already joined')
    if action in ('leave', 'start') and not joined:
        return GameError('Not in game', 403, 'forbidden')
    if action == 'leave' and owner:
        return GameError('Owner cannot leave the game')
    if action == 'start':
        if not owner:
            return GameError('Only the owner can start the game', 403, 'forbidden')
        if len(game['users']) < 2:
            return GameError('Need at least 2 players to start')
    if action == 'cancel' and not owner:
        return GameError('Only the owner can cancel the game', 403, 'forbidden')
    return None


def lobby_actions(game, uid):
    return {
        action: _lobby_action_error(game, uid, action) is None
        for action in ('join', 'leave', 'start', 'cancel')
    }


def _require_lobby_action(game, uid, action):
    error = _lobby_action_error(game, uid, action)
    if error:
        raise error


def _lock_users(cursor, user_ids):
    # All operations lock game first, then users in the same order.
    users = {}
    for uid in sorted(set(user_ids)):
        cursor.execute(
            'SELECT id, rating, gamehistory, ratinghistory, rating_ledger_id, rating_event_id, deleted, admin_level FROM user WHERE id = %s FOR UPDATE',
            (uid,),
        )
        row = cursor.fetchone()
        if row is None or type(row['rating']) is not int:
            raise _invalid_data()
        users[uid] = dict(row)
    return users


def _require_active_actor(users, uid):
    # Authentication before the transaction is not a lock: a ban may commit
    # while a command waits. Only the actor must be active; retain other players'
    # historical answers/settlements even when their accounts are now banned.
    actor = users.get(uid)
    if actor is None or actor['deleted'] != 0:
        raise GameError('Account is no longer active', 403, 'forbidden')


def _lock_membership_actor(cursor, user_ids, uid):
    # Membership writes may FK-check every member. Lock all of them in the same
    # order as settlement, never actor-first followed by a lower-ID participant.
    users = {}
    for user_id in sorted(set(user_ids) | {uid}):
        cursor.execute('SELECT id, deleted, rating FROM user WHERE id = %s FOR UPDATE', (user_id,))
        row = cursor.fetchone()
        if row is not None:
            users[user_id] = row
    _require_active_actor(users, uid)
    return users


def _check_rated_admission(cursor, current, users, expected_ids):
    if game_rating_policy.rated(current):
        if set(users) != set(expected_ids):
            raise _invalid_data()
        rated_eligibility.require_eligible(cursor, current['dictid'], users)


def _settle(cursor, game, users):
    return game_settlements.settle(cursor, game, users)


def _execute(action, uid, game_id, payload, request_id, expected_version):
    request_id, expected_version = game_requests.validate_options(request_id, expected_version)
    if action == 'create' and expected_version is not None:
        raise GameError('Creation has no expected_version', 400, 'invalid_parameters')
    with transaction() as cursor:
        replay = game_requests.reserve(
            cursor, uid, request_id, action, game_id, payload, expected_version
        )
        if replay is not None:
            return replay  # Before version/turn checks: a successful retry must remain successful.
        current = _locked_game(cursor, game_id) if game_id is not None else None
        if current is not None:
            game_requests.check_version(current, expected_version)
            if game_questions.source(current) == 'snapshot':
                game_questions.load(cursor, current)
        result = _OPERATIONS[action](cursor, current, uid, payload)
        version = 0
        if current is not None:
            version = current['version']
            if not (action == 'end' and result['already_finished']):
                if version == game_requests.MAX_VERSION:
                    raise GameError('Game version exhausted', 409, 'invalid_game_state')
                version += 1
                cursor.execute('UPDATE game SET version = %s WHERE id = %s', (version, game_id))
        else:
            game_id = result['game_id']
        return game_requests.complete(cursor, uid, request_id, game_id, version, result)


def rename_game(game_id, uid, name, *, request_id=None, expected_version=None):
    if request_id is None or expected_version is None:
        raise GameError(
            'Rename requires request_id and expected_version', 400, 'invalid_parameters'
        )
    return _execute(
        'rename', uid, game_id, {'name': game_names.parse(name)}, request_id, expected_version
    )


def _rename(cursor, game, uid, payload):
    _lock_membership_actor(cursor, [uid], uid)
    if game['ownerid'] != uid:
        raise GameError('Only the game creator may rename it', 403, 'forbidden')
    if game['status'] not in (WAITING, RUNNING, FINISHED, CANCELLED):
        raise _invalid_data()
    before = game_names.stored(game)
    if before == payload['name']:
        raise GameError('Game name is unchanged', 400, 'unchanged_game_name')
    cursor.execute('UPDATE game SET name=%s WHERE id=%s', (payload['name'], game['id']))
    return {
        'message': 'Game renamed',
        'game_id': game['id'],
        'name': payload['name'],
        'previous_name': before,
    }


def create_game(uid, dict_id, *, rated=True, request_id=None, expected_version=None):
    game_rating_policy.choice(rated)
    # Preserve pre-0013 Rated request fingerprints and their durable receipts.
    payload = {'dict_id': dict_id} if rated else {'dict_id': dict_id, 'rated': False}
    return _execute('create', uid, None, payload, request_id, expected_version)


def join_game(game_id, uid, *, request_id=None, expected_version=None):
    return _execute('join', uid, game_id, {}, request_id, expected_version)


def leave_game(game_id, uid, *, request_id=None, expected_version=None):
    return _execute('leave', uid, game_id, {}, request_id, expected_version)


def start_game(game_id, uid, *, request_id=None, expected_version=None):
    return _execute('start', uid, game_id, {}, request_id, expected_version)


def cancel_game(game_id, uid, *, request_id=None, expected_version=None):
    return _execute('cancel', uid, game_id, {}, request_id, expected_version)


def answer_game(game_id, uid, word_id, answer, *, request_id=None, expected_version=None):
    answer = text({'answer': answer}, 'answer').lower()
    try:
        answer.encode('utf-8')
    except UnicodeEncodeError:
        raise GameError('Invalid answer Unicode', 400, 'invalid_parameters') from None
    return _execute(
        'answer', uid, game_id, {'word_id': word_id, 'answer': answer}, request_id, expected_version
    )


def end_game(game_id, uid, *, request_id=None, expected_version=None):
    return _execute('end', uid, game_id, {}, request_id, expected_version)


def _create(cursor, game, uid, payload):
    dict_id = payload['dict_id']
    name, words, multiplier, difficulty = game_questions.capture(
        cursor, dict_id, payload.get('rated', True), weighted=True
    )
    random.shuffle(words)
    # Keep the old ID list as an integrity manifest until the remaining JSON migration.
    # Text always comes from game_question for these games, never from word.
    manifest = json.dumps([word['id'] for word in words])
    if len(manifest.encode('utf-8')) > 65535:
        raise GameError('Dictionary exceeds the game question limit', 400, 'dictionary_too_large')
    cursor.execute(
        """INSERT INTO game (dictid, users, wordlist, result, status, ownerid, version, question_mode, dictname_snapshot,
                             participant_mode, participant_count, answer_mode, answer_count, settlement_mode, perf_mode, multiplier_snapshot, rated, rating_model, difficulty_snapshot, rating_parameters)
           VALUES (%s, NULL, %s, NULL, %s, %s, 0, 1, %s, 1, 1, 1, 0, 1, 1, %s, %s, 1, %s, %s)""",
        (
            dict_id,
            manifest,
            WAITING,
            uid,
            name,
            multiplier,
            int(payload.get('rated', True)),
            difficulty,
            json.dumps(weighted_games.parameters()),
        ),
    )
    game_id = cursor.lastrowid
    game_questions.save(cursor, game_id, words)
    users = _lock_membership_actor(cursor, [uid], uid)
    _check_rated_admission(
        cursor, {'dictid': dict_id, 'rated': int(payload.get('rated', True))}, users, [uid]
    )
    game_participants.save(
        cursor,
        {
            'id': game_id,
            'ownerid': uid,
            'users': [uid],
            'participant_mode': 1,
            'participant_count': 1,
        },
    )
    return {'game_id': game_id, 'message': 'Game created'}


def _join(cursor, game, uid, payload):
    _require_status(game, WAITING)
    if game['result']:
        raise _invalid_data()
    _require_lobby_action(game, uid, 'join')
    users = _lock_membership_actor(cursor, game['users'], uid)
    _check_rated_admission(cursor, game, users, [*game['users'], uid])
    game['users'].append(uid)
    random.shuffle(game['users'])
    game_participants.save(cursor, game)
    return {'message': 'Joined game'}


def _leave(cursor, game, uid, payload):
    _require_lobby_action(game, uid, 'leave')
    if game['result']:
        raise _invalid_data()
    _lock_membership_actor(cursor, game['users'], uid)
    game['users'].remove(uid)
    game_participants.save(cursor, game)
    return {'message': 'Left game'}


def _start(cursor, game, uid, payload):
    _require_lobby_action(game, uid, 'start')
    if game['result'] or not game['wordlist']:
        raise _invalid_data()
    users = _lock_users(cursor, game['users'])
    _require_active_actor(users, uid)
    _check_rated_admission(cursor, game, users, game['users'])
    weighted_games.start(cursor, game, users)
    cursor.execute('UPDATE game SET status = %s WHERE id = %s', (RUNNING, game['id']))
    return {'message': 'Game started'}


def _cancel(cursor, game, uid, payload):
    _require_lobby_action(game, uid, 'cancel')
    _lock_membership_actor(cursor, game['users'], uid)
    cursor.execute('UPDATE game SET status = %s WHERE id = %s', (CANCELLED, game['id']))
    return {'message': 'Game cancelled'}


def _answer(cursor, game, uid, payload):
    word_id, answer, game_id = payload['word_id'], payload['answer'], game['id']
    _require_status(game, RUNNING)
    _require_participant(game, uid)
    index = len(game['result'])
    if index >= len(game['wordlist']):
        raise GameError('All words have been answered')
    if game['users'][index % len(game['users'])] != uid:
        raise GameError('Not your turn')
    if game['wordlist'][index] != word_id:
        raise GameError('This is not the expected word for your turn')
    _perfs(game)  # Reject malformed legacy records before any writes.
    words = game_questions.load(cursor, game)
    word = words[index]
    if not game_questions.valid_text(word['english']):
        raise _invalid_data()
    users = _lock_users(cursor, game['users'])
    _require_active_actor(users, uid)
    user = users[uid]
    history = _list(user['gamehistory'])
    if any(type(item) is not int for item in history):
        raise _invalid_data()
    if game_id not in history:
        history.append(game_id)
    previous = next((item for item in reversed(game['result']) if item['uid'] == uid), None)
    correct = check_answer(answer, word['english'])
    weighted_score = None
    if weighted_games.enabled(game):
        weighted_games.check_current(cursor, game, users)
        weighted_score = weighted_games.answer(cursor, game, uid, correct)
        scoring = weighted_games.core_fields(weighted_score)
    else:
        scoring = score_answer(
            rating=user['rating'],
            played_games=len(set(history)),
            previous=previous,
            last_global_combo=game['result'][-1].get('globalcombo', 0) if game['result'] else 0,
            correct=correct,
            multiplier=game_multiplier(game),
        )
    game_answers.append(
        cursor,
        game,
        {'uid': uid, 'word_id': word_id, 'answer': answer, 'result': correct, **scoring},
    )
    if weighted_score is not None:
        weighted_games.save_answer(cursor, game, uid, weighted_score)
    # Historical participation stays intact; new placement counts advance only at settlement.
    if game_rating_policy.rated(game):
        cursor.execute('UPDATE user SET gamehistory = %s WHERE id = %s', (json.dumps(history), uid))
    next_turn, next_word = None, None
    if len(game['result']) == len(game['wordlist']):
        _settle(cursor, game, users)
    else:
        next_turn = game['users'][len(game['result']) % len(game['users'])]
        next_word = game_questions.prompt(words[len(game['result'])])
    return {
        'message': 'Answer recorded',
        'correct': correct,
        'expected': word['english'],
        'next_turn': next_turn,
        'next_word': next_word,
        'current_index': len(game['result']),
        'status': game['status'],
        **scoring,
    }


def _end(cursor, game, uid, payload):
    # A nonparticipant administrator is an actor, NOT an additional player. Lock
    # actor and participants together in ascending order, never actor-first.
    members = game['users'] if game['status'] == RUNNING else []
    users = _lock_users(cursor, [*members, uid])
    _require_active_actor(users, uid)
    if not can_end_game(users[uid], game['ownerid']):
        raise GameError(
            'Only the owner or an administrator of level 2 or higher may end the game; send an end request instead',
            403,
            'game_end_forbidden',
        )
    if game['status'] == FINISHED:
        return {'message': 'Game already finished', 'already_finished': True}
    _require_status(game, RUNNING)
    perfs = _settle(cursor, game, {member: users[member] for member in members})
    return {
        'message': 'Game ended and ratings updated'
        if game_rating_policy.rated(game)
        else 'Unrated game ended; ratings unchanged',
        'perf': perfs,
        'already_finished': False,
    }


_OPERATIONS = {
    'rename': _rename,
    'create': _create,
    'join': _join,
    'leave': _leave,
    'start': _start,
    'cancel': _cancel,
    'answer': _answer,
    'end': _end,
}


def get_game_state(game_id):
    with reading() as cursor:
        cursor.execute(
            'SELECT g.*, '
            + game_questions.DICTNAME_SQL
            + ' AS dictname FROM game g LEFT JOIN dict d ON d.id = g.dictid WHERE g.id = %s',
            (game_id,),
        )
        game = _decode_game(cursor.fetchone(), cursor)
        users_info, history_users = [], []
        for uid in game['users']:
            cursor.execute(
                'SELECT id, username, rating, ratinghistory, rating_ledger_id, rating_event_id, deleted FROM user WHERE id = %s',
                (uid,),
            )
            user = cursor.fetchone()
            if user:
                users_info.append(public_person(user))
                history_users.append(user)
        histories = game_settlements.histories(cursor, history_users)
        cursor.execute(
            'SELECT id, username, rating, deleted FROM user WHERE id = %s', (game['ownerid'],)
        )
        owner = public_person(cursor.fetchone())
        words = []
        for index, word in enumerate(game_questions.load(cursor, game)):
            # Only completed prefix positions may reveal answers. Malformed legacy
            # result IDs cannot expose a future question's English text.
            public = game_questions.prompt(word)
            if index < len(game['result']):
                public['english'] = word['english']
            words.append(public)
    index = len(game['result'])
    next_turn, next_word = None, None
    if game['status'] == RUNNING and game['users'] and index < len(game['wordlist']):
        next_turn = game['users'][index % len(game['users'])]
        next_word = next((word for word in words if word['id'] == game['wordlist'][index]), None)
    perfs = {uid: {'correct': 0, 'wrong': 0, 'perf': 0} for uid in game['users']}
    for answer in game['result']:
        if answer.get('uid') in perfs:
            stats = perfs[answer['uid']]
            stats['correct' if answer.get('result') else 'wrong'] += 1
            stats['perf'] = answer.get('perf')
    return {
        'id': game['id'],
        'version': game['version'],
        'name': game_names.stored(game),
        'dictid': game['dictid'],
        'dictname': game['dictname'],
        'question_source': game_questions.source(game),
        'rated': game_rating_policy.rated(game),
        **multiplier_metadata(game),
        'users': users_info,
        'userrating': histories,
        'scoring': weighted_games.public_game(game),
        'owner': owner,
        'words': words,
        'total_words': len(game['wordlist']),
        'result': game['result'],
        'perf': perfs,
        'status': game['status'],
        'current_index': index,
        'next_turn': next_turn,
        'next_word': next_word,
    }
