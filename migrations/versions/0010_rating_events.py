"""Future rating event chain; existing game ledgers remain an untouched prefix.

This stage admits game events only. Manual adjustments require a later explicit
revision and their own authorization/idempotency/concurrency path.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER

revision = '0010_rating_events'
down_revision = '0009_admin_levels'
branch_labels = depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'rating_event' in {
        name.lower() for name in inspector.get_table_names()
    } or 'rating_event_id' in {column['name'].lower() for column in inspector.get_columns('user')}:
        raise RuntimeError(
            'Partial/custom rating-event schema detected; inspect or restore before retrying'
        )
    for table, expected in [('user', INTEGER), ('game_rating', BIGINT)]:
        columns = {column['name']: column for column in inspector.get_columns(table)}
        kind = columns['id']['type']
        if (
            inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb'
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
            or type(kind) is not expected
            or getattr(kind, 'unsigned', False)
        ):
            raise RuntimeError(
                'Rating events require existing InnoDB signed user/game-rating primary keys'
            )
    # No backfill, recalculation, guessed timestamps, or legacy pointer updates.
    op.create_table(
        'rating_event',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_event_user', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('sequence', sa.Integer, nullable=False),
        sa.Column('previous_id', sa.BigInteger, nullable=True),
        sa.Column(
            'legacy_rating_id',
            sa.BigInteger,
            sa.ForeignKey('game_rating.id', name='fk_event_legacy_rating', ondelete='RESTRICT'),
            nullable=True,
        ),
        sa.Column(
            'game_rating_id',
            sa.BigInteger,
            sa.ForeignKey('game_rating.id', name='fk_event_game_rating', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('kind', sa.String(16, collation='ascii_bin'), nullable=False),
        sa.Column('rule_version', sa.String(32, collation='ascii_bin'), nullable=False),
        sa.Column('rating_before', sa.Integer, nullable=False),
        sa.Column('delta', sa.BigInteger, nullable=False),
        sa.Column('rating_after', sa.Integer, nullable=False),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint('user_id', 'id', name='uq_event_user_id'),
        sa.UniqueConstraint('user_id', 'sequence', name='uq_event_user_sequence'),
        sa.UniqueConstraint('user_id', 'previous_id', name='uq_event_user_previous'),
        sa.UniqueConstraint('game_rating_id', name='uq_event_game_rating'),
        sa.ForeignKeyConstraint(
            ['user_id', 'previous_id'],
            ['rating_event.user_id', 'rating_event.id'],
            name='fk_event_previous_user',
            ondelete='RESTRICT',
        ),
        sa.CheckConstraint('sequence >= 1', name='ck_event_sequence'),
        sa.CheckConstraint("kind = 'game' AND rule_version = 'legacy-v1'", name='ck_event_kind'),
        sa.CheckConstraint(
            '(sequence = 1 AND previous_id IS NULL) OR (sequence > 1 AND previous_id IS NOT NULL AND legacy_rating_id IS NULL)',
            name='ck_event_origin',
        ),
        sa.CheckConstraint(
            'rating_after = CAST(rating_before AS DECIMAL(20, 0)) + delta',
            name='ck_event_arithmetic',
        ),
        mysql_engine='InnoDB',
    )
    op.add_column('user', sa.Column('rating_event_id', sa.BigInteger, nullable=True))
    op.create_index('ix_user_rating_event', 'user', ['rating_event_id'])
    op.create_foreign_key(
        'fk_user_rating_event',
        'user',
        'rating_event',
        ['rating_event_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade():
    raise RuntimeError(
        'Rating events are append-only accounting history. Restore a verified backup and matching application; do not discard the event chain.'
    )
