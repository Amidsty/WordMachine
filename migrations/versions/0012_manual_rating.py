"""Explicit manual Rating sources and receipts; never rewrite prior events."""

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, LONGTEXT

revision = '0012_manual_rating'
down_revision = '0011_dictionary_multipliers'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}
    columns = {column['name']: column for column in inspector.get_columns('rating_event')}
    checks = {
        item['name']: item['sqltext'] for item in inspector.get_check_constraints('rating_event')
    }
    source_column = columns.get('game_rating_id', {})
    source_kind = source_column.get('type')
    source_fk = next(
        (
            fk
            for fk in inspector.get_foreign_keys('rating_event')
            if fk['name'] == 'fk_event_game_rating'
        ),
        {},
    )
    old_kind = re.sub(r"_[a-zA-Z0-9]+(?=')", '', checks.get('ck_event_kind', ''))
    old_kind = re.sub(r'[\s`()]+', '', old_kind).lower()
    if (
        tables & {'rating_adjustment_request', 'manual_rating'}
        or 'manual_rating_id' in columns
        or source_column.get('nullable', True)
        or type(source_kind) is not BIGINT
        or getattr(source_kind, 'unsigned', False)
        or source_fk.get('constrained_columns') != ['game_rating_id']
        or source_fk.get('referred_table') != 'game_rating'
        or source_fk.get('referred_columns') != ['id']
        or source_fk.get('options', {}).get('ondelete', 'RESTRICT') != 'RESTRICT'
        or old_kind != "kind='game'andrule_version='legacy-v1'"
    ):
        raise RuntimeError(
            'Partial/custom manual-rating schema detected; inspect or restore before retrying'
        )
    for table, expected in [('user', INTEGER), ('rating_event', BIGINT), ('game_rating', BIGINT)]:
        kind = next(c['type'] for c in inspector.get_columns(table) if c['name'] == 'id')
        if (
            inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb'
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
            or type(kind) is not expected
            or getattr(kind, 'unsigned', False)
        ):
            raise RuntimeError('Manual ratings require existing InnoDB signed primary keys')
    names = {
        'fk_manual_user',
        'fk_manual_actor',
        'fk_manual_last_game',
        'fk_manual_request',
        'uq_manual_request',
        'uq_manual_user_id',
        'ck_manual_actor_level',
        'ck_manual_arithmetic',
        'ck_manual_reason',
        'fk_event_manual_rating',
        'uq_event_manual_rating',
        'ck_event_source',
    }
    existing = set(
        bind.execute(
            sa.text(
                'SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE()'
            )
        ).scalars()
    )
    if names & existing:
        raise RuntimeError(
            'Partial/custom manual-rating constraints detected; inspect before retrying'
        )
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout = :seconds'), {'seconds': min(wait, 30)})
    # Deliberately no actor FK on reservations: reserve BEFORE ascending user locks.
    op.create_table(
        'rating_adjustment_request',
        sa.Column('actor_id', sa.Integer, primary_key=True),
        sa.Column('request_id', sa.String(36, collation='ascii_bin'), primary_key=True),
        sa.Column('payload_hash', sa.String(64, collation='ascii_bin'), nullable=False),
        sa.Column('response', LONGTEXT, nullable=True),
        sa.Column('created_at', DATETIME(fsp=6), nullable=False),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'manual_rating',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_manual_user', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'actor_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_manual_actor', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('actor_level', sa.Integer, nullable=False),
        sa.Column('request_id', sa.String(36, collation='ascii_bin'), nullable=False),
        sa.Column(
            'last_game_rating_id',
            sa.BigInteger,
            sa.ForeignKey('game_rating.id', name='fk_manual_last_game', ondelete='RESTRICT'),
        ),
        sa.Column('rating_before', sa.Integer, nullable=False),
        sa.Column('delta', sa.BigInteger, nullable=False),
        sa.Column('rating_after', sa.Integer, nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint('actor_id', 'request_id', name='uq_manual_request'),
        sa.UniqueConstraint('user_id', 'id', name='uq_manual_user_id'),
        sa.ForeignKeyConstraint(
            ['actor_id', 'request_id'],
            ['rating_adjustment_request.actor_id', 'rating_adjustment_request.request_id'],
            name='fk_manual_request',
            ondelete='RESTRICT',
        ),
        sa.CheckConstraint('actor_level IN (4, 5)', name='ck_manual_actor_level'),
        sa.CheckConstraint(
            'rating_after = CAST(rating_before AS DECIMAL(20, 0)) + delta AND delta <> 0',
            name='ck_manual_arithmetic',
        ),
        sa.CheckConstraint('CHAR_LENGTH(TRIM(reason)) BETWEEN 1 AND 500', name='ck_manual_reason'),
        mysql_engine='InnoDB',
    )
    # One ALTER for the source discriminator. Existing values/IDs/timestamps stay untouched.
    op.execute("""ALTER TABLE rating_event
        DROP CHECK ck_event_kind,
        MODIFY game_rating_id BIGINT NULL,
        ADD COLUMN manual_rating_id BIGINT NULL,
        ADD CONSTRAINT uq_event_manual_rating UNIQUE (manual_rating_id),
        ADD CONSTRAINT fk_event_manual_rating FOREIGN KEY (user_id, manual_rating_id) REFERENCES manual_rating(user_id, id) ON DELETE RESTRICT,
        ADD CONSTRAINT ck_event_source CHECK (
            (kind = 'game' AND rule_version = 'legacy-v1' AND game_rating_id IS NOT NULL AND manual_rating_id IS NULL)
            OR (kind = 'manual' AND rule_version = 'manual-v1' AND game_rating_id IS NULL AND manual_rating_id IS NOT NULL)
        )""")


def downgrade():
    raise RuntimeError(
        'Manual ratings are accounting history. Restore a verified backup and matching application; do not discard sources or receipts.'
    )
