"""Future settlement ledger; preserve historical JSON and balances verbatim."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, DOUBLE, INTEGER

revision = '0007_game_settlements'
down_revision = '0006_game_answers'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'].lower(): column for column in inspector.get_columns('game')}
    user_columns = {column['name'].lower(): column for column in inspector.get_columns('user')}
    names = {
        'fk_user_rating_ledger',
        'ck_game_settlement_mode',
        'fk_settlement_game',
        'ck_settlement_count',
        'uq_rating_game_user',
        'fk_rating_settlement',
        'fk_rating_user',
        'ck_rating_arithmetic',
    }
    constraints = {
        row[0].lower()
        for row in bind.execute(
            sa.text("""
        SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE()
    """)
        )
    }
    if (
        {'game_settlement', 'game_rating'} & {name.lower() for name in inspector.get_table_names()}
        or 'settlement_mode' in columns
        or 'rating_ledger_id' in user_columns
        or names & constraints
        or any(
            index['name'].lower() == 'ix_user_rating_ledger'
            for index in inspector.get_indexes('user')
        )
    ):
        raise RuntimeError(
            'Partial/custom settlement schema detected; inspect or restore before retrying migration'
        )
    for table in ('game', 'user'):
        fields = {column['name']: column for column in inspector.get_columns(table)}
        id_type = fields['id']['type']
        if (
            type(id_type) is not INTEGER
            or getattr(id_type, 'unsigned', False)
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
        ):
            raise RuntimeError(
                'Expected signed INT game/user primary keys before adding settlement foreign keys'
            )
        if table == 'user':
            rating_type = fields['rating']['type']
            if type(rating_type) is not INTEGER or getattr(rating_type, 'unsigned', False):
                raise RuntimeError(
                    'Expected signed INT user.rating before adding the rating ledger'
                )
    if any(not columns[field]['nullable'] for field in ('perf', 'ratingdelta')):
        raise RuntimeError('Expected nullable legacy game score columns before adding settlements')
    engines = dict(
        bind.execute(
            sa.text("""SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('game', 'user')""")
        ).all()
    )
    if engines != {'game': 'InnoDB', 'user': 'InnoDB'}:
        raise RuntimeError('Settlement transactions require InnoDB game and user tables')
    # MySQL DDL may partially commit: all preflights must precede the first ALTER.
    op.add_column('user', sa.Column('rating_ledger_id', sa.BigInteger, nullable=True))
    op.add_column(
        'game',
        sa.Column('settlement_mode', sa.Integer, nullable=False, server_default=sa.text('0')),
    )
    op.create_check_constraint('ck_game_settlement_mode', 'game', 'settlement_mode IN (0, 1)')
    op.create_table(
        'game_settlement',
        sa.Column(
            'game_id',
            sa.Integer,
            sa.ForeignKey('game.id', name='fk_settlement_game', ondelete='RESTRICT'),
            primary_key=True,
        ),
        sa.Column('rated_count', sa.Integer, nullable=False),
        sa.Column('rating_version', sa.String(32, collation='ascii_bin'), nullable=False),
        sa.Column('settled_at', DATETIME(fsp=6), nullable=True),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint('rated_count >= 0', name='ck_settlement_count'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'game_rating',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            'game_id',
            sa.Integer,
            sa.ForeignKey(
                'game_settlement.game_id', name='fk_rating_settlement', ondelete='RESTRICT'
            ),
            nullable=False,
        ),
        # Inserted only AFTER ordered user X locks; unlike request reservations.
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_rating_user', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('perf', DOUBLE(asdecimal=False), nullable=False),
        sa.Column('rating_before', sa.Integer, nullable=False),
        sa.Column('delta', sa.BigInteger, nullable=False),
        sa.Column('rating_after', sa.Integer, nullable=False),
        sa.UniqueConstraint('game_id', 'user_id', name='uq_rating_game_user'),
        # DECIMAL only for exact integer arithmetic, never for rounding Perf.
        sa.CheckConstraint(
            'rating_after = CAST(rating_before AS DECIMAL(20, 0)) + delta',
            name='ck_rating_arithmetic',
        ),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_rating_user_id', 'game_rating', ['user_id', 'id'])
    op.create_index('ix_user_rating_ledger', 'user', ['rating_ledger_id'])
    op.create_foreign_key(
        'fk_user_rating_ledger',
        'user',
        'game_rating',
        ['rating_ledger_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade():
    raise RuntimeError(
        'Dropping settlements loses rating history and once-only evidence. Restore a verified backup with its matching application version.'
    )
