"""Dictionary configuration and future-game Perf multiplier snapshots only."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME, DOUBLE, INTEGER

revision = '0011_dictionary_multipliers'
down_revision = '0010_rating_events'
branch_labels = depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    additions = {
        'dict': {'multiplier', 'config_version'},
        'game': {'perf_mode', 'multiplier_snapshot'},
        'game_answer': {'raw_perf_delta'},
    }
    if 'dictionary_audit' in {name.lower() for name in inspector.get_table_names()} or any(
        names & {column['name'].lower() for column in inspector.get_columns(table)}
        for table, names in additions.items()
    ):
        raise RuntimeError(
            'Partial/custom multiplier schema detected; inspect or restore before retrying'
        )
    for table in (*additions, 'user'):
        if inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb':
            raise RuntimeError('Dictionary multipliers require InnoDB tables')
    for table in ('dict', 'user'):
        columns = {column['name'].lower(): column for column in inspector.get_columns(table)}
        kind = columns.get('id', {}).get('type')
        if (
            type(kind) is not INTEGER
            or getattr(kind, 'unsigned', False)
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
        ):
            raise RuntimeError('Multiplier audit requires signed INT dictionary/user primary keys')
    for table, names in [
        ('dict', {'ck_dict_multiplier', 'ck_dict_config_version'}),
        ('game', {'ck_game_multiplier'}),
    ]:
        if names & {
            constraint['name'].lower() for constraint in inspector.get_check_constraints(table)
        }:
            raise RuntimeError(
                'Partial/custom multiplier constraint detected; inspect before retrying'
            )
    # No old game/answer backfill: missing provenance stays NULL and legacy mode.
    op.add_column(
        'dict', sa.Column('multiplier', sa.Numeric(5, 2), nullable=False, server_default='1.00')
    )
    op.add_column(
        'dict', sa.Column('config_version', sa.Integer, nullable=False, server_default='0')
    )
    op.create_check_constraint('ck_dict_multiplier', 'dict', 'multiplier BETWEEN 0.10 AND 5.00')
    op.create_check_constraint('ck_dict_config_version', 'dict', 'config_version >= 0')
    op.add_column('game', sa.Column('perf_mode', sa.Integer, nullable=False, server_default='0'))
    op.add_column('game', sa.Column('multiplier_snapshot', sa.Numeric(5, 2), nullable=True))
    op.create_check_constraint(
        'ck_game_multiplier',
        'game',
        '(perf_mode = 0 AND multiplier_snapshot IS NULL) OR (perf_mode = 1 AND multiplier_snapshot IS NOT NULL AND multiplier_snapshot BETWEEN 0.10 AND 5.00 AND question_mode = 1 AND answer_mode = 1)',
    )
    op.add_column(
        'game_answer', sa.Column('raw_perf_delta', DOUBLE(asdecimal=False), nullable=True)
    )
    op.create_table(
        'dictionary_audit',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            'dict_id',
            sa.Integer,
            sa.ForeignKey('dict.id', name='fk_dict_audit_dict', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'actor_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_dict_audit_actor', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('actor_level', sa.Integer, nullable=False),
        sa.Column('multiplier_before', sa.Numeric(5, 2), nullable=True),
        sa.Column('multiplier_after', sa.Numeric(5, 2), nullable=False),
        sa.Column('config_version', sa.Integer, nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_dict_audit_dict_id', 'dictionary_audit', ['dict_id', 'id'])


def downgrade():
    raise RuntimeError(
        'Multiplier snapshots and audit history must not be discarded. Restore a verified backup with its matching application.'
    )
