"""Versioned transactional adapter for weighted-perf-v1/v2. Caller owns game -> sorted user locks.

No commits, migrations, account adoption or historical repair. Read validation
uses frozen facts; never today's dictionary, account rating or fresh randomness.
"""

import json
import random
from dataclasses import asdict
from datetime import datetime

from pymysql import IntegrityError

from . import weighted_rating as engine
from . import weighted_rating_v2 as engine_v2
from .errors import GameError

NEW_MODEL = 2
PERF_VERSIONS = (engine.PERF_VERSION, engine_v2.PERF_VERSION)
RATING_VERSIONS = (engine.RATING_VERSION, engine_v2.RATING_VERSION)


def rules(game):
    mode = game.get('rating_model', 1)
    if type(mode) is not int or mode not in (1, 2):
        raise invalid()
    return engine if mode == 1 else engine_v2


def invalid():
    return GameError('Weighted rating facts require review', 409, 'invalid_weighted_rating')


def exact(value):
    # MySQL JSON numeric parsing is not a binary64 round-trip contract. Persist
    # floats as hex strings; SQL DOUBLE answer/source columns remain numeric.
    if type(value) is float:
        return {'binary64': engine.finite(value).hex()}
    if isinstance(value, dict):
        return {key: exact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [exact(item) for item in value]
    return value


def parameters(model=1):
    if type(model) is not int or model not in (1, 2):
        raise invalid()
    if model == 2:
        return exact(
            dict(
                perf_version=engine_v2.PERF_VERSION,
                rating_version=engine_v2.RATING_VERSION,
                bonus_version=engine.BONUS_VERSION,
                bonuses=list(engine.BONUSES),
                difficulty_extra=0.25,
                difficulty_scale=800,
                alpha=0.5,
                delta_max=200,
                high_threshold=1500,
                high_scale=1000,
                up_min=0.75,
                down_max=1.25,
                reward_extra=0.30,
                reward_tau=10,
                penalty_extra=2.0,
                penalty_tau=8,
                global_protection_min=0.5,
            )
        )
    return exact(
        dict(
            perf_version=engine.PERF_VERSION,
            rating_version=engine.RATING_VERSION,
            bonus_version=engine.BONUS_VERSION,
            bonuses=list(engine.BONUSES),
            kappa=10,
            perf_scale=400,
            alpha=0.5,
            delta_max=200,
            high_threshold=1500,
            high_scale=1000,
            up_min=0.25,
            down_max=2.0,
            reward_extra=0.30,
            penalty_extra=0.40,
            reward_tau=10,
            penalty_tau=8,
        )
    )


def decoded(value):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        # Canonical text also distinguishes bool/int and rejects nonfinite numbers.
        return json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise invalid() from None


def enabled(game):
    mode = game.get('rating_model', 0)
    if type(mode) is not int or mode not in (0, 1, 2):
        raise invalid()
    if not mode:
        if game.get('difficulty_snapshot') is not None or game.get('rating_parameters') is not None:
            raise invalid()
        return False
    if (
        type(game.get('difficulty_snapshot')) is not int
        or not 0 <= game['difficulty_snapshot'] <= 4000
        or any(
            type(game.get(k)) is not int or game.get(k) != 1
            for k in (
                'question_mode',
                'participant_mode',
                'answer_mode',
                'settlement_mode',
                'perf_mode',
            )
        )
        or decoded(game.get('rating_parameters')) != decoded(parameters(mode))
    ):
        raise invalid()
    return True


def _snapshot(game, row):
    try:
        if type(row['newcomer_enabled']) is not int or row['newcomer_enabled'] not in (0, 1):
            raise invalid()
        selected = rules(game)
        if row['rule_version'] != selected.RATING_VERSION:
            raise invalid()
        snap = selected.Snapshot(
            row['public_rating'],
            row['remaining_bonus'],
            row['completed_games'],
            bool(row['newcomer_enabled']),
            game['difficulty_snapshot'],
            game['multiplier_snapshot'],
        )
        expected = dict(
            difficulty=snap.difficulty,
            multiplier=snap.multiplier,
            internal_rating=snap.internal_rating,
            streak_protection=snap.streak_protection,
            rating_protection=snap.rating_protection,
            speed_up=snap.speed_factors[0],
            speed_down=snap.speed_factors[1],
        )
        if any(row[k] != v for k, v in expected.items()) or not isinstance(
            row['recorded_at'], datetime
        ):
            raise invalid()
        return snap
    except (KeyError, ValueError, TypeError, OverflowError):
        raise invalid() from None


def state(cursor, uid):
    # No missing-range read is followed by an INSERT. Missing state is corruption,
    # never an opportunity to adopt an old account as a newcomer.
    cursor.execute('SELECT * FROM user_rating_state WHERE user_id=%s FOR SHARE', (uid,))
    row = cursor.fetchone()
    if row is None:
        raise invalid()
    try:
        engine.integer(row['newcomer_enabled'], 0, 1)
        engine.Snapshot(
            0, row['remaining_bonus'], row['completed_games'], bool(row['newcomer_enabled'])
        )
    except (ValueError, KeyError):
        raise invalid() from None
    if row['completed_games']:
        cursor.execute(
            'SELECT r.remaining_after,s.newcomer_enabled FROM weighted_result r JOIN game_rating_snapshot s ON s.game_id=r.game_id AND s.user_id=r.user_id WHERE r.user_id=%s AND r.completed_after=%s FOR SHARE',
            (uid, row['completed_games']),
        )
        head = cursor.fetchone()
        if (
            not head
            or head['remaining_after'] != row['remaining_bonus']
            or head['newcomer_enabled'] != row['newcomer_enabled']
        ):
            raise invalid()
    return row


def register(cursor, uid):
    cursor.execute(
        'INSERT INTO user_rating_state (user_id,newcomer_enabled,completed_games,remaining_bonus) VALUES (%s,1,0,1500)',
        (uid,),
    )


def start(cursor, game, users):
    if not enabled(game):
        if game['rated']:
            raise GameError(
                'Legacy waiting Rated games cannot start; create a new game',
                409,
                'legacy_rating_start_disabled',
            )
        return
    from . import rating_events

    for uid in sorted(users):
        user = users[uid]
        current = state(cursor, uid)
        rating_events.current(cursor, user)
        snap = rules(game).Snapshot(
            user['rating'],
            current['remaining_bonus'],
            current['completed_games'],
            bool(current['newcomer_enabled']),
            game['difficulty_snapshot'],
            game['multiplier_snapshot'],
        )
        if game['rated']:
            # INSERT, not a FOR SHARE probe of an empty unique range (gap deadlocks).
            try:
                cursor.execute(
                    'INSERT INTO rated_occupancy (user_id,game_id) VALUES (%s,%s)',
                    (uid, game['id']),
                )
            except IntegrityError as error:
                if error.args[0] == 1062:
                    raise GameError(
                        'A participant already has a running Rated game', 409, 'rated_game_running'
                    ) from None
                raise
        cursor.execute(
            'INSERT INTO game_rating_snapshot (game_id,user_id,public_rating,remaining_bonus,completed_games,newcomer_enabled,difficulty,multiplier,internal_rating,streak_protection,rating_protection,speed_up,speed_down,event_id,recorded_at,rule_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (
                game['id'],
                uid,
                user['rating'],
                snap.remaining_bonus,
                snap.completed_games,
                int(snap.newcomer_enabled),
                snap.difficulty,
                snap.multiplier,
                snap.internal_rating,
                snap.streak_protection,
                snap.rating_protection,
                *snap.speed_factors,
                user['rating_event_id'],
                datetime.utcnow(),
                rules(game).RATING_VERSION,
            ),
        )


def score_fields(score, snapshot):
    return dict(
        draw=score.answer.draw,
        self_before=score.self_before,
        global_before=score.answer.global_before,
        raw_point_delta=score.raw_point_delta,
        weight_delta=score.weight_delta,
        effective_multiplier=score.effective_multiplier,
        correct_before=score.before.correct_weight,
        wrong_before=score.before.wrong_weight,
        correct_after=score.after.correct_weight,
        wrong_after=score.after.wrong_weight,
        perf_before=score.before.perf
        if score.before.perf is not None
        else float(snapshot.internal_rating),
    )


def core_fields(score, game=None):
    return dict(
        usercombo=score.self_after,
        globalcombo=score.global_after,
        perf_delta=score.perf_delta,
        perf=score.after.perf,
        rating_version=rules(game or {}).PERF_VERSION,
    )


def validate_answers(game, snapshots, rows):
    if not enabled(game):
        if snapshots or rows:
            raise invalid()
        return
    if game['status'] in (-1, 2):
        if snapshots or rows or game['result']:
            raise invalid()
        return
    by_id = {row['user_id']: row for row in snapshots}
    if len(by_id) != len(snapshots) or set(by_id) != set(game['users']):
        raise invalid()
    states = {uid: _snapshot(game, row) for uid, row in by_id.items()}
    previous = {uid: [] for uid in states}
    if len(rows) != len(game['result']):
        raise invalid()
    global_before = 0
    for position, (entry, row) in enumerate(zip(game['result'], rows, strict=True)):
        uid = entry['uid']
        if (
            row['game_id'] != game['id']
            or row['position'] != position
            or row['user_id'] != uid
            or entry['rating_version'] != rules(game).PERF_VERSION
        ):
            raise invalid()
        try:
            answer = engine.AnswerInput(entry['result'], row['draw'], global_before)
            score = rules(game).score_answer(states[uid], previous[uid], answer)
        except (ValueError, KeyError, TypeError):
            raise invalid() from None
        if any(entry.get(k) != v for k, v in core_fields(score, game).items()) or any(
            row.get(k) != v for k, v in score_fields(score, states[uid]).items()
        ):
            raise invalid()
        global_before = score.global_after
        previous[uid].append(answer)
    game['_weighted_snapshots'] = states
    game['_weighted_rows'] = by_id
    game['_weighted_inputs'] = previous
    game['_weighted_public_answers'] = [
        dict(
            position=row['position'],
            user_id=row['user_id'],
            draw=row['draw'],
            raw_point_delta=row['raw_point_delta'],
            perf_delta=entry['perf_delta'],
            self_before=row['self_before'],
            global_before=row['global_before'],
            effective_multiplier=row['effective_multiplier'],
        )
        for entry, row in zip(game['result'], rows, strict=True)
    ]


def load(cursor, game):
    if not enabled(game):
        return
    cursor.execute(
        'SELECT * FROM game_rating_snapshot WHERE game_id=%s ORDER BY user_id', (game['id'],)
    )
    snapshots = list(cursor.fetchall())
    cursor.execute(
        'SELECT * FROM weighted_answer WHERE game_id=%s ORDER BY position', (game['id'],)
    )
    validate_answers(game, snapshots, list(cursor.fetchall()))


def answer(cursor, game, uid, correct):
    snapshot = game['_weighted_snapshots'][uid]
    previous = game['_weighted_inputs'][uid]
    global_before = game['result'][-1]['globalcombo'] if game['result'] else 0
    # Only called after game/user locks, active-actor checks and turn validation.
    fact = engine.AnswerInput(correct, random.SystemRandom().randint(5, 15), global_before)
    score = rules(game).score_answer(snapshot, previous, fact)
    return score


def save_answer(cursor, game, uid, score):
    fields = dict(
        game_id=game['id'],
        position=len(game['result']) - 1,
        user_id=uid,
        **score_fields(score, game['_weighted_snapshots'][uid]),
    )
    columns = ','.join(fields)
    cursor.execute(
        'INSERT INTO weighted_answer ('
        + columns
        + ') VALUES ('
        + ','.join(['%s'] * len(fields))
        + ')',
        tuple(fields.values()),
    )
    game['_weighted_inputs'][uid].append(score.answer)


def check_current(cursor, game, users):
    for uid, snapshot in game['_weighted_snapshots'].items():
        if game['rated']:
            row = state(cursor, uid)
            frozen = game['_weighted_rows'][uid]
            if (
                row['remaining_bonus'] != snapshot.remaining_bonus
                or row['completed_games'] != snapshot.completed_games
                or bool(row['newcomer_enabled']) != snapshot.newcomer_enabled
                or users[uid]['rating'] != snapshot.public_rating
                or users[uid]['rating_event_id'] != frozen['event_id']
            ):
                raise GameError(
                    'Rating snapshot changed; review the game', 409, 'stale_rating_snapshot'
                )
            cursor.execute('SELECT game_id FROM rated_occupancy WHERE user_id=%s FOR SHARE', (uid,))
            occupied = cursor.fetchone()
            if occupied is None or occupied['game_id'] != game['id']:
                raise invalid()


def proposals(cursor, game, users):
    check_current(cursor, game, users)
    result = {}
    for uid, snapshot in game['_weighted_snapshots'].items():
        try:
            proposal = rules(game).settlement_proposal(
                snapshot, game['_weighted_inputs'][uid], rated=bool(game['rated']), finished=True
            )
        except ValueError:
            raise GameError(
                'Weighted settlement exceeds supported range', 409, 'rating_out_of_range'
            ) from None
        if proposal.eligible:
            result[uid] = proposal
    return result


def calculation(proposal):
    return exact(dict(evidence=asdict(proposal.evidence), competitive=asdict(proposal.competitive)))


def record(cursor, game, uid, rating_id, proposal, now):
    cursor.execute(
        'INSERT INTO weighted_result (game_id,user_id,rating_id,competitive_delta,newcomer_bonus,completed_after,remaining_after,internal_after,calculation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (
            game['id'],
            uid,
            rating_id,
            proposal.competitive.delta,
            proposal.bonus,
            proposal.completed_after,
            proposal.remaining_after,
            proposal.internal_after,
            json.dumps(calculation(proposal), allow_nan=False),
        ),
    )
    if proposal.bonus:
        cursor.execute(
            'INSERT INTO newcomer_award (user_id,ordinal,game_id,amount,rule_version,recorded_at) VALUES (%s,%s,%s,%s,%s,%s)',
            (uid, proposal.completed_after, game['id'], proposal.bonus, engine.BONUS_VERSION, now),
        )
    cursor.execute(
        'UPDATE user_rating_state SET completed_games=%s,remaining_bonus=%s WHERE user_id=%s',
        (proposal.completed_after, proposal.remaining_after, uid),
    )


def release(cursor, game):
    cursor.execute('DELETE FROM rated_occupancy WHERE game_id=%s', (game['id'],))


def validate_results(game, sources, results, awards):
    if not enabled(game):
        if results or awards:
            raise invalid()
        return
    expected = {}
    if game['status'] == 1 and game['rated']:
        for uid, snapshot in game['_weighted_snapshots'].items():
            try:
                p = rules(game).settlement_proposal(
                    snapshot, game['_weighted_inputs'][uid], rated=True, finished=True
                )
            except ValueError:
                raise invalid() from None
            if p.eligible:
                expected[uid] = p
    source_map = {r['user_id']: r for r in sources}
    if len(results) != len(expected) or len(source_map) != len(expected):
        raise invalid()
    seen = set()
    for row in results:
        uid = row['user_id']
        if uid in seen or uid not in expected or uid not in source_map:
            raise invalid()
        seen.add(uid)
        p, src, snap = expected[uid], source_map[uid], game['_weighted_snapshots'][uid]
        if (
            row['game_id'] != game['id']
            or row['rating_id'] != src['id']
            or src.get('rule_version') != rules(game).RATING_VERSION
            or src['rating_before'] != snap.public_rating
            or src['rating_after'] != p.public_after
            or src['delta'] != p.competitive.delta + p.bonus
            or src['perf'] != p.evidence.perf
            or any(
                row[k] != v
                for k, v in dict(
                    competitive_delta=p.competitive.delta,
                    newcomer_bonus=p.bonus,
                    completed_after=p.completed_after,
                    remaining_after=p.remaining_after,
                    internal_after=p.internal_after,
                ).items()
            )
            or decoded(row['calculation']) != decoded(calculation(p))
        ):
            raise invalid()
    bonuses = {uid: p for uid, p in expected.items() if p.bonus}
    if len(awards) != len(bonuses) or {r['user_id'] for r in awards} != set(bonuses):
        raise invalid()
    for row in awards:
        p = bonuses[row['user_id']]
        if (
            row['game_id'] != game['id']
            or row['ordinal'] != p.completed_after
            or row['amount'] != p.bonus
            or row['rule_version'] != engine.BONUS_VERSION
            or not isinstance(row['recorded_at'], datetime)
        ):
            raise invalid()

    game['_weighted_public_results'] = {
        row['user_id']: dict(
            competitive_delta=row['competitive_delta'],
            newcomer_bonus=row['newcomer_bonus'],
            total_delta=source_map[row['user_id']]['delta'],
            public_after=source_map[row['user_id']]['rating_after'],
            internal_after=row['internal_after'],
            remaining_after=row['remaining_after'],
            completed_after=row['completed_after'],
        )
        for row in results
    }


def public_game(game):
    if not enabled(game):
        return None
    players = []
    for uid, snap in game.get('_weighted_snapshots', {}).items():
        ev = rules(game).evidence(snap, game['_weighted_inputs'][uid])
        players.append(
            dict(
                user_id=uid,
                public_before=snap.public_rating,
                internal_before=snap.internal_rating,
                remaining_before=snap.remaining_bonus,
                completed_before=snap.completed_games,
                newcomer_enabled=snap.newcomer_enabled,
                streak_protection=snap.streak_protection,
                rating_protection=snap.rating_protection,
                speed_up=snap.speed_factors[0],
                speed_down=snap.speed_factors[1],
                **(
                    dict(
                        difficulty_up=snap.difficulty_factors[0],
                        difficulty_down=snap.difficulty_factors[1],
                        global_protection=snap.global_protection,
                    )
                    if game['rating_model'] == 2
                    else {}
                ),
                answered_count=ev.answered_count,
                raw_points=10 * (ev.correct_weight - ev.wrong_weight)
                if ev.answered_count
                else None,
                perf=ev.perf,
                settlement=game.get('_weighted_public_results', {}).get(uid),
            )
        )
    return dict(
        model='weighted-v2' if game['rating_model'] == 2 else 'weighted-v1',
        perf_version=rules(game).PERF_VERSION,
        rating_version=rules(game).RATING_VERSION,
        difficulty=game['difficulty_snapshot'],
        players=players,
        answers=game.get('_weighted_public_answers', []),
    )


def public_account(cursor, user):
    # Ordinary consistent reads: public/management reviews must not take locks or
    # mix current locking reads with an older balance snapshot.
    cursor.execute('SELECT * FROM user_rating_state WHERE user_id=%s', (user['id'],))
    row = cursor.fetchone()
    try:
        if (
            row is None
            or type(row['newcomer_enabled']) is not int
            or row['newcomer_enabled'] not in (0, 1)
        ):
            raise invalid()
        snap = engine.Snapshot(
            user['rating'],
            row['remaining_bonus'],
            row['completed_games'],
            bool(row['newcomer_enabled']),
        )
        if snap.completed_games:
            cursor.execute(
                'SELECT remaining_after FROM weighted_result WHERE user_id=%s AND completed_after=%s',
                (user['id'], snap.completed_games),
            )
            head = cursor.fetchone()
            if head is None or head['remaining_after'] != snap.remaining_bonus:
                raise invalid()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise invalid() from None
    return dict(
        model='weighted-v1',
        public_rating=snap.public_rating,
        internal_rating=snap.internal_rating,
        remaining_bonus=snap.remaining_bonus,
        completed_games=snap.completed_games,
        newcomer_enabled=snap.newcomer_enabled,
        next_bonus=snap.bonus,
    )


def unpack(value):
    if isinstance(value, dict):
        if set(value) == {'binary64'}:
            try:
                return engine.finite(float.fromhex(value['binary64']))
            except (ValueError, TypeError):
                raise invalid() from None
        return {key: unpack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unpack(item) for item in value]
    return value


def validate_source(source, snapshot_row, result, award):
    """Validate immutable weighted ledger facts without taking another game's lock.

    Full room answer reconstruction is checked by game/Perf reads and audit.
    The hot ledger path stays bounded to this one source and its frozen snapshot.
    """
    try:
        if not snapshot_row or not result:
            raise invalid()
        if source.get('rule_version') not in RATING_VERSIONS:
            raise invalid()
        pseudo_game = dict(
            rating_model=1 if source['rule_version'] == engine.RATING_VERSION else 2,
            difficulty_snapshot=snapshot_row['difficulty'],
            multiplier_snapshot=snapshot_row['multiplier'],
        )
        snap = _snapshot(pseudo_game, snapshot_row)
        data = result['calculation']
        data = unpack(json.loads(data) if isinstance(data, str) else data)
        ev = engine.Evidence(**data['evidence'])
        engine.integer(ev.answered_count, 1, engine.MAX_RATING)
        engine.integer(ev.self_streak, 0, ev.answered_count)
        selected = rules(pseudo_game)
        expected_perf = selected.performance(snap, ev.correct_weight, ev.wrong_weight)
        if ev.correct_weight + ev.wrong_weight <= 0 or ev.perf != expected_perf:
            raise invalid()
        change = selected.competitive_change(
            snap, expected_perf, ev.correct_weight, ev.wrong_weight
        )
        p = engine.SettlementProposal(
            True,
            ev,
            change,
            snap.bonus,
            snap.public_rating + change.delta + snap.bonus,
            snap.remaining_bonus - snap.bonus,
            snap.internal_rating + change.delta,
            snap.completed_games + 1,
        )
        if (
            result['game_id'] != source['game_id']
            or result['user_id'] != source['user_id']
            or result['rating_id'] != source['id']
            or snapshot_row['game_id'] != source['game_id']
            or snapshot_row['user_id'] != source['user_id']
            or source['rating_before'] != snap.public_rating
            or source['rating_after'] != p.public_after
            or source['delta'] != change.delta + snap.bonus
            or source['perf'] != expected_perf
            or result['competitive_delta'] != change.delta
            or result['newcomer_bonus'] != snap.bonus
            or result['completed_after'] != p.completed_after
            or result['remaining_after'] != p.remaining_after
            or result['internal_after'] != p.internal_after
            or decoded(result['calculation']) != decoded(calculation(p))
        ):
            raise invalid()
        if snap.bonus:
            if (
                not award
                or award['game_id'] != source['game_id']
                or award['user_id'] != source['user_id']
                or award['ordinal'] != p.completed_after
                or award['amount'] != snap.bonus
                or award['rule_version'] != engine.BONUS_VERSION
                or not isinstance(award['recorded_at'], datetime)
            ):
                raise invalid()
        elif award:
            raise invalid()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise invalid() from None


def check_sources(cursor, sources, *, current=False):
    sources = [s for s in sources if s is not None and s.get('rule_version') in RATING_VERSIONS]
    if not sources:
        return
    if current:
        for source in sources:
            parts = []
            for table in ('game_rating_snapshot', 'weighted_result'):
                cursor.execute(
                    'SELECT * FROM ' + table + ' WHERE game_id=%s AND user_id=%s FOR SHARE',
                    (source['game_id'], source['user_id']),
                )
                parts.append(cursor.fetchone())
            award = None
            if parts[1] and parts[1]['newcomer_bonus']:
                cursor.execute(
                    'SELECT * FROM newcomer_award WHERE user_id=%s AND ordinal=%s FOR SHARE',
                    (source['user_id'], parts[1]['completed_after']),
                )
                award = cursor.fetchone()
            validate_source(source, *parts, award)
        return
    ids = sorted({s['game_id'] for s in sources})
    grouped = []
    for table in ('game_rating_snapshot', 'weighted_result', 'newcomer_award'):
        cursor.execute(
            'SELECT * FROM ' + table + ' WHERE game_id IN (' + ','.join(['%s'] * len(ids)) + ')',
            ids,
        )
        grouped.append({(r['game_id'], r['user_id']): r for r in cursor.fetchall()})
    for source in sources:
        key = (source['game_id'], source['user_id'])
        validate_source(source, *(rows.get(key) for rows in grouped))


def load_results(cursor, game, sources):
    if not enabled(game):
        return
    cursor.execute('SELECT * FROM weighted_result WHERE game_id=%s ORDER BY user_id', (game['id'],))
    results = list(cursor.fetchall())
    cursor.execute('SELECT * FROM newcomer_award WHERE game_id=%s ORDER BY user_id', (game['id'],))
    validate_results(game, sources, results, list(cursor.fetchall()))
