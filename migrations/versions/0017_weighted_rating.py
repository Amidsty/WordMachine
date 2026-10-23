"""Versioned weighted scoring; no old score, receipt or account balance is rewritten.

Writers must be stopped. Partial DDL is not retryable; inspect/restore explicitly.
Running legacy Rated games reserve their existing members; conflicting old rooms
must be resolved BEFORE this migration, never silently cancelled or adopted.
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BIGINT, INTEGER

from wm_app.models import weighted_v1 as schema

revision = '0017_weighted_rating'
down_revision = '0016_game_names'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    additions = {
        'dict': {'difficulty'},
        'game': {'rating_model', 'difficulty_snapshot', 'rating_parameters'},
        'game_rating': {'rule_version'},
    }
    names = set(inspector.get_table_names())
    if names.intersection(schema.TABLE_NAMES):
        raise RuntimeError('Partial weighted schema; inspect before retrying')
    for table, columns in additions.items():
        if columns.intersection(c['name'] for c in inspector.get_columns(table)):
            raise RuntimeError('Partial weighted columns; inspect before retrying')
    constraints = set(
        bind.execute(
            sa.text(
                'SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()'
            )
        ).scalars()
    )
    if constraints.intersection(
        {
            'ck_dict_difficulty',
            'ck_game_rating_model',
            'ck_rating_rule',
            'uq_answer_weighted_identity',
            'uq_rating_weighted_identity',
        }
    ):
        raise RuntimeError('Partial weighted constraints; inspect before retrying')
    for name in (
        'user',
        'dict',
        'game',
        'game_answer',
        'game_rating',
        'game_settlement',
        'rating_event',
        'game_participant',
    ):
        if inspector.get_table_options(name).get('mysql_engine', '').lower() != 'innodb':
            raise RuntimeError('Weighted rating requires InnoDB')
    for name, key, kind in (
        ('user', 'id', INTEGER),
        ('dict', 'id', INTEGER),
        ('game', 'id', INTEGER),
        ('rating_event', 'id', BIGINT),
        ('game_rating', 'id', BIGINT),
        ('game_answer', 'game_id', INTEGER),
        ('game_answer', 'position', INTEGER),
        ('game_answer', 'user_id', INTEGER),
        ('game_participant', 'game_id', INTEGER),
        ('game_participant', 'user_id', INTEGER),
    ):
        column = next(c for c in inspector.get_columns(name) if c['name'] == key)
        if type(column['type']) is not kind or column['type'].unsigned:
            raise RuntimeError('Weighted foreign-key source types require review')
    if not {'ck_event_source', 'ck_settlement_rating_policy'} <= constraints:
        raise RuntimeError('Missing prior rating constraints; review schema')
    occupied = {}
    valid_users = set(bind.execute(sa.text('SELECT id FROM user')).scalars())
    for game in bind.execute(
        sa.text(
            'SELECT id,users,participant_mode,participant_count,ownerid FROM game WHERE status=0 AND rated=1'
        )
    ).mappings():
        if game['participant_mode'] == 1:
            members = list(
                bind.execute(
                    sa.text(
                        'SELECT user_id,position FROM game_participant WHERE game_id=:gid ORDER BY position'
                    ),
                    {'gid': game['id']},
                ).mappings()
            )
            ids = [r['user_id'] for r in members]
            if len(ids) != game['participant_count'] or [r['position'] for r in members] != list(
                range(len(ids))
            ):
                raise RuntimeError('Running membership requires review')
        elif game['participant_mode'] == 0:
            try:
                ids = json.loads(game['users'])
            except (TypeError, ValueError):
                raise RuntimeError('Running legacy membership requires review') from None
        else:
            raise RuntimeError('Unknown running membership mode')
        if (
            not isinstance(ids, list)
            or not ids
            or any(type(uid) is not int or uid not in valid_users for uid in ids)
            or len(set(ids)) != len(ids)
            or game['ownerid'] not in ids
        ):
            raise RuntimeError('Running membership requires review')
        for uid in ids:
            if uid in occupied:
                raise RuntimeError(
                    'Concurrent legacy Rated rooms require explicit resolution before migration'
                )
            occupied[uid] = game['id']
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout=:wait'), {'wait': min(wait, 30)})
    op.add_column(
        'dict', sa.Column('difficulty', sa.Integer(), nullable=False, server_default='1500')
    )
    op.create_check_constraint('ck_dict_difficulty', 'dict', 'difficulty BETWEEN 0 AND 4000')
    op.add_column(
        'game', sa.Column('rating_model', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column('game', sa.Column('difficulty_snapshot', sa.Integer()))
    op.add_column('game', sa.Column('rating_parameters', sa.JSON()))
    op.create_check_constraint('ck_game_rating_model', 'game', schema.MODEL_CHECK)
    op.add_column(
        'game_rating',
        sa.Column(
            'rule_version',
            sa.String(32, collation='ascii_bin'),
            nullable=False,
            server_default='legacy-v1',
        ),
    )
    op.create_check_constraint(
        'ck_rating_rule', 'game_rating', "rule_version IN ('legacy-v1','weighted-rating-v1')"
    )
    op.create_unique_constraint(
        'uq_answer_weighted_identity', 'game_answer', ['game_id', 'position', 'user_id']
    )
    op.create_unique_constraint(
        'uq_rating_weighted_identity', 'game_rating', ['id', 'game_id', 'user_id']
    )
    # A single ALTER per existing CHECK avoids an unconstrained intermediate table.
    op.execute(
        'ALTER TABLE game_settlement DROP CHECK ck_settlement_rating_policy, ADD CONSTRAINT ck_settlement_rating_policy CHECK ('
        + schema.SETTLEMENT_CHECK
        + ')'
    )
    op.execute(
        'ALTER TABLE rating_event DROP CHECK ck_event_source, ADD CONSTRAINT ck_event_source CHECK ('
        + schema.EVENT_CHECK
        + ')'
    )
    metadata = sa.MetaData()
    for name in (
        'user',
        'dict',
        'game',
        'game_participant',
        'game_answer',
        'game_rating',
        'rating_event',
    ):
        sa.Table(name, metadata, autoload_with=bind)
    for table in schema.tables(metadata):
        table.create(bind)
    op.execute(
        'INSERT INTO user_rating_state (user_id,newcomer_enabled,completed_games,remaining_bonus) SELECT id,0,0,0 FROM user'
    )
    if occupied:
        bind.execute(
            sa.text('INSERT INTO rated_occupancy (user_id,game_id) VALUES (:uid,:gid)'),
            [{'uid': uid, 'gid': gid} for uid, gid in occupied.items()],
        )


def downgrade():
    raise RuntimeError(
        'Weighted scores and bonus receipts must be preserved; restore a verified backup with matching code'
    )
