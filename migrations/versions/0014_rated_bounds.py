"""System dictionary Rated admission bounds; no historical game changes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME, INTEGER

revision = '0014_rated_bounds'
down_revision = '0013_game_rated'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = {
        'ck_dict_rated_bounds',
        'fk_rated_bounds_dict',
        'fk_rated_bounds_actor',
        'ck_rated_bounds_actor',
        'ck_rated_bounds_before',
        'ck_rated_bounds_after',
        'ck_rated_bounds_version',
        'ck_rated_bounds_reason',
    }
    existing = {
        name.lower()
        for name in bind.execute(
            sa.text(
                'SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()'
            )
        ).scalars()
    }
    if (
        'dictionary_rated_audit'
        in {name.lower() for name in inspector.get_table_names() + inspector.get_view_names()}
        or {'rated_min', 'rated_max'}
        & {column['name'].lower() for column in inspector.get_columns('dict')}
        or names & existing
    ):
        raise RuntimeError(
            'Partial/custom Rated bounds schema detected; inspect or restore before retrying'
        )
    for table in ('dict', 'user'):
        fields = {item['name']: item for item in inspector.get_columns(table)}
        kind = fields['id']['type']
        if (
            inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb'
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
            or type(kind) is not INTEGER
            or getattr(kind, 'unsigned', False)
        ):
            raise RuntimeError('Rated bounds require InnoDB signed INT primary keys')
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout = :seconds'), {'seconds': min(wait, 30)})
    op.execute(
        'ALTER TABLE dict ADD COLUMN rated_min INT NOT NULL DEFAULT -2147483648, ADD COLUMN rated_max INT NOT NULL DEFAULT 2147483647, ADD CONSTRAINT ck_dict_rated_bounds CHECK (rated_min <= rated_max)'
    )
    op.create_table(
        'dictionary_rated_audit',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            'dict_id',
            sa.Integer,
            sa.ForeignKey('dict.id', name='fk_rated_bounds_dict', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'actor_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_rated_bounds_actor', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('actor_level', sa.Integer, nullable=False),
        sa.Column('min_before', sa.Integer, nullable=False),
        sa.Column('max_before', sa.Integer, nullable=False),
        sa.Column('min_after', sa.Integer, nullable=False),
        sa.Column('max_after', sa.Integer, nullable=False),
        sa.Column('config_version', sa.Integer, nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint('actor_level BETWEEN 3 AND 5', name='ck_rated_bounds_actor'),
        sa.CheckConstraint('min_before <= max_before', name='ck_rated_bounds_before'),
        sa.CheckConstraint('min_after <= max_after', name='ck_rated_bounds_after'),
        sa.CheckConstraint('config_version > 0', name='ck_rated_bounds_version'),
        sa.CheckConstraint('CHAR_LENGTH(reason) BETWEEN 1 AND 500', name='ck_rated_bounds_reason'),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_rated_bounds_dict_id', 'dictionary_rated_audit', ['dict_id', 'id'])


def downgrade():
    raise RuntimeError(
        'Rated admission policy and audit must not be discarded; restore a verified backup with matching code'
    )
