"""Frozen 0018 extension of the delivered 0017 schema; no runtime DDL."""

import sqlalchemy as sa

from . import weighted_v1 as v1

MODEL_CHECK = v1.MODEL_CHECK.replace('rating_model=1', 'rating_model IN (1,2)')
SETTLEMENT_CHECK = v1.SETTLEMENT_CHECK.replace(
    "'weighted-rating-v1'", "'weighted-rating-v1','weighted-rating-v2'"
)
EVENT_CHECK = v1.EVENT_CHECK.replace(
    "'weighted-rating-v1'", "'weighted-rating-v1','weighted-rating-v2'"
)
RULE_CHECK = "rule_version IN ('legacy-v1','weighted-rating-v1','weighted-rating-v2')"
SNAPSHOT_CHECK = "rule_version IN ('weighted-rating-v1','weighted-rating-v2')"
ANSWER_CHECK = 'draw BETWEEN 5 AND 15 AND self_before>=0 AND global_before>=0 AND weight_delta>0 AND effective_multiplier BETWEEN 1 AND 3 AND correct_before>=0 AND wrong_before>=0 AND correct_after>=correct_before AND wrong_after>=wrong_before'
REPLACEMENTS = (
    ('game', 'ck_game_rating_model', 'ck_game_rating_model_v2', MODEL_CHECK),
    (
        'game_settlement',
        'ck_settlement_rating_policy',
        'ck_settlement_rating_policy_v2',
        SETTLEMENT_CHECK,
    ),
    ('rating_event', 'ck_event_source', 'ck_event_source_v2', EVENT_CHECK),
    ('game_rating', 'ck_rating_rule', 'ck_rating_rule_v2', RULE_CHECK),
    ('weighted_answer', 'ck_weighted_answer_values', 'ck_weighted_answer_values_v2', ANSWER_CHECK),
)


def tables(metadata):
    result = v1.tables(metadata)
    snapshot = metadata.tables['game_rating_snapshot']
    snapshot.append_column(
        sa.Column(
            'rule_version',
            sa.String(32, collation='ascii_bin'),
            nullable=False,
            server_default='weighted-rating-v1',
        )
    )
    snapshot.append_constraint(
        sa.CheckConstraint(SNAPSHOT_CHECK, name='ck_weighted_snapshot_rule_v2')
    )
    answers = metadata.tables['weighted_answer']
    old = next(c for c in answers.constraints if c.name == 'ck_weighted_answer_values')
    answers.constraints.remove(old)
    answers.append_constraint(sa.CheckConstraint(ANSWER_CHECK, name='ck_weighted_answer_values_v2'))
    return result
