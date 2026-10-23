"""Frozen 0017 schema definitions. Do not edit after delivery: use a new migration.

Shared by explicit migration and metadata only; never creates tables at runtime.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, DOUBLE

TABLE_NAMES = (
    'user_rating_state',
    'rated_occupancy',
    'game_rating_snapshot',
    'weighted_answer',
    'weighted_result',
    'newcomer_award',
    'dictionary_difficulty_audit',
)
STATE_CHECK = 'newcomer_enabled IN (0,1) AND completed_games BETWEEN 0 AND 2147483647 AND remaining_bonus = CASE WHEN newcomer_enabled=0 THEN 0 WHEN completed_games=0 THEN 1500 WHEN completed_games=1 THEN 900 WHEN completed_games=2 THEN 550 WHEN completed_games=3 THEN 300 WHEN completed_games=4 THEN 150 WHEN completed_games=5 THEN 50 ELSE 0 END'
SETTLEMENT_CHECK = "rating_version IN ('legacy-v1','weighted-rating-v1') OR (rating_version='unrated-v1' AND rated_count=0)"
EVENT_CHECK = "(kind='game' AND rule_version IN ('legacy-v1','weighted-rating-v1') AND game_rating_id IS NOT NULL AND manual_rating_id IS NULL) OR (kind='manual' AND rule_version='manual-v1' AND game_rating_id IS NULL AND manual_rating_id IS NOT NULL)"
MODEL_CHECK = '(rating_model=0 AND difficulty_snapshot IS NULL AND rating_parameters IS NULL) OR (rating_model=1 AND difficulty_snapshot IS NOT NULL AND difficulty_snapshot BETWEEN 0 AND 4000 AND rating_parameters IS NOT NULL AND question_mode=1 AND participant_mode=1 AND answer_mode=1 AND settlement_mode=1 AND perf_mode=1)'


def tables(metadata):
    def col(name, kind=sa.Integer, **kw):
        return sa.Column(name, kind, nullable=False, **kw)

    def fk(local, remote, name):
        return sa.ForeignKeyConstraint(local, remote, name=name, ondelete='RESTRICT')

    def table(name, *items):
        return sa.Table(name, metadata, *items, mysql_engine='InnoDB')

    state = table(
        'user_rating_state',
        col('user_id', primary_key=True),
        col('newcomer_enabled'),
        col('completed_games'),
        col('remaining_bonus'),
        fk(['user_id'], ['user.id'], 'fk_weighted_state_user'),
        sa.CheckConstraint(STATE_CHECK, name='ck_weighted_state'),
    )
    occupancy = table(
        'rated_occupancy',
        col('user_id', primary_key=True),
        col('game_id'),
        fk(['user_id'], ['user.id'], 'fk_rated_occupancy_user'),
        fk(['game_id'], ['game.id'], 'fk_rated_occupancy_game'),
        sa.Index('ix_rated_occupancy_game', 'game_id', 'user_id'),
    )
    snapshot = table(
        'game_rating_snapshot',
        col('game_id', primary_key=True),
        col('user_id', primary_key=True),
        col('public_rating'),
        col('remaining_bonus'),
        col('completed_games'),
        col('newcomer_enabled'),
        col('difficulty'),
        col('multiplier', sa.Numeric(5, 2)),
        col('internal_rating', sa.BigInteger),
        col('streak_protection', DOUBLE),
        col('rating_protection', DOUBLE),
        col('speed_up', DOUBLE),
        col('speed_down', DOUBLE),
        sa.Column('event_id', sa.BigInteger),
        col('recorded_at', DATETIME(fsp=6)),
        fk(
            ['game_id', 'user_id'],
            ['game_participant.game_id', 'game_participant.user_id'],
            'fk_weighted_snapshot_member',
        ),
        fk(
            ['user_id', 'event_id'],
            ['rating_event.user_id', 'rating_event.id'],
            'fk_weighted_snapshot_event',
        ),
        sa.CheckConstraint(STATE_CHECK, name='ck_weighted_snapshot_state'),
        sa.CheckConstraint(
            'difficulty BETWEEN 0 AND 4000 AND multiplier BETWEEN 0.10 AND 5.00 AND internal_rating=CAST(public_rating AS DECIMAL(20,0))+remaining_bonus AND streak_protection BETWEEN 0 AND 1 AND rating_protection BETWEEN 0.2 AND 1 AND speed_up BETWEEN 0.25 AND 1 AND speed_down BETWEEN 1 AND 2',
            name='ck_weighted_snapshot_math',
        ),
    )
    answer = table(
        'weighted_answer',
        col('game_id', primary_key=True),
        col('position', primary_key=True),
        col('user_id'),
        col('draw'),
        col('self_before'),
        col('global_before'),
        col('raw_point_delta', DOUBLE),
        col('weight_delta', DOUBLE),
        col('effective_multiplier', DOUBLE),
        col('correct_before', DOUBLE),
        col('wrong_before', DOUBLE),
        col('correct_after', DOUBLE),
        col('wrong_after', DOUBLE),
        col('perf_before', DOUBLE),
        fk(
            ['game_id', 'position', 'user_id'],
            ['game_answer.game_id', 'game_answer.position', 'game_answer.user_id'],
            'fk_weighted_answer_core',
        ),
        fk(
            ['game_id', 'user_id'],
            ['game_rating_snapshot.game_id', 'game_rating_snapshot.user_id'],
            'fk_weighted_answer_snapshot',
        ),
        sa.CheckConstraint(
            'draw BETWEEN 5 AND 15 AND self_before>=0 AND global_before>=0 AND weight_delta>0 AND effective_multiplier BETWEEN 1 AND 1.4 AND correct_before>=0 AND wrong_before>=0 AND correct_after>=correct_before AND wrong_after>=wrong_before',
            name='ck_weighted_answer_values',
        ),
    )
    result = table(
        'weighted_result',
        col('game_id', primary_key=True),
        col('user_id', primary_key=True),
        col('rating_id', sa.BigInteger),
        col('competitive_delta'),
        col('newcomer_bonus'),
        col('completed_after'),
        col('remaining_after'),
        col('internal_after', sa.BigInteger),
        col('calculation', sa.JSON),
        fk(
            ['game_id', 'user_id'],
            ['game_rating_snapshot.game_id', 'game_rating_snapshot.user_id'],
            'fk_weighted_result_snapshot',
        ),
        fk(
            ['rating_id', 'game_id', 'user_id'],
            ['game_rating.id', 'game_rating.game_id', 'game_rating.user_id'],
            'fk_weighted_result_source',
        ),
        sa.UniqueConstraint('rating_id', name='uq_weighted_result_rating'),
        sa.UniqueConstraint('user_id', 'completed_after', name='uq_weighted_result_sequence'),
        sa.CheckConstraint(
            'competitive_delta BETWEEN -200 AND 200 AND newcomer_bonus IN (0,50,100,150,250,350,600) AND completed_after>0 AND remaining_after BETWEEN 0 AND 1500',
            name='ck_weighted_result_values',
        ),
    )
    award = table(
        'newcomer_award',
        col('user_id', primary_key=True),
        col('ordinal', primary_key=True),
        col('game_id'),
        col('amount'),
        col('rule_version', sa.String(32, collation='ascii_bin')),
        col('recorded_at', DATETIME(fsp=6)),
        fk(
            ['game_id', 'user_id'],
            ['weighted_result.game_id', 'weighted_result.user_id'],
            'fk_newcomer_result',
        ),
        sa.UniqueConstraint('game_id', 'user_id', name='uq_newcomer_game_user'),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 6 AND amount=CASE ordinal WHEN 1 THEN 600 WHEN 2 THEN 350 WHEN 3 THEN 250 WHEN 4 THEN 150 WHEN 5 THEN 100 WHEN 6 THEN 50 END AND rule_version='newcomer-bonus-v1'",
            name='ck_newcomer_award',
        ),
    )
    difficulty_audit = table(
        'dictionary_difficulty_audit',
        col('id', sa.BigInteger, primary_key=True, autoincrement=True),
        col('dict_id'),
        col('actor_id'),
        col('actor_level'),
        col('difficulty_before'),
        col('difficulty_after'),
        col('config_version'),
        col('reason', sa.String(500)),
        col('recorded_at', DATETIME(fsp=6)),
        fk(['dict_id'], ['dict.id'], 'fk_difficulty_audit_dict'),
        fk(['actor_id'], ['user.id'], 'fk_difficulty_audit_actor'),
        sa.UniqueConstraint('dict_id', 'config_version', name='uq_difficulty_audit_version'),
        sa.CheckConstraint(
            'actor_level BETWEEN 0 AND 5 AND difficulty_before BETWEEN 0 AND 4000 AND difficulty_after BETWEEN 0 AND 4000 AND difficulty_before<>difficulty_after AND config_version>0 AND CHAR_LENGTH(TRIM(reason)) BETWEEN 1 AND 500',
            name='ck_difficulty_audit_values',
        ),
    )
    return state, occupancy, snapshot, answer, result, award, difficulty_audit
