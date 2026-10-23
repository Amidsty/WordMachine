"""Normalized participation for new games; legacy JSON conversion is explicit."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, INTEGER

revision = '0005_game_participants'
down_revision = '0004_game_questions'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'].lower(): column for column in inspector.get_columns('game')}
    # Column/index names are case-insensitive in MySQL; differently cased custom
    # objects must also be rejected BEFORE an earlier ALTER can commit.
    if (
        'game_participant' in {name.lower() for name in inspector.get_table_names()}
        or {'participant_mode', 'participant_count'} & columns.keys()
        or any(
            check['name'].lower() == 'ck_game_participants'
            for check in inspector.get_check_constraints('game')
        )
        or any(
            index['name'].lower() == 'ix_game_participant_status'
            for index in inspector.get_indexes('game')
        )
    ):
        raise RuntimeError(
            'Partial/custom participant schema detected; inspect or restore before retrying migration'
        )
    if not columns['users']['nullable']:
        raise RuntimeError('Expected nullable game.users before moving new membership to relations')
    for table in ('game', 'user'):
        fields = {column['name']: column for column in inspector.get_columns(table)}
        id_type = fields['id']['type']
        if (
            type(id_type) is not INTEGER
            or getattr(id_type, 'unsigned', False)
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
        ):
            raise RuntimeError(
                'Expected signed INT game/user primary keys before adding participant foreign keys'
            )
    engines = dict(
        bind.execute(
            sa.text("""SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('game', 'user')""")
        ).all()
    )
    if engines != {'game': 'InnoDB', 'user': 'InnoDB'}:
        raise RuntimeError('Participation transactions require InnoDB game and user tables')
    # MySQL DDL can commit partially. Do all checks before the first change.
    op.add_column(
        'game',
        sa.Column('participant_mode', sa.Integer, nullable=False, server_default=sa.text('0')),
    )
    op.add_column('game', sa.Column('participant_count', sa.Integer, nullable=True))
    op.create_check_constraint(
        'ck_game_participants',
        'game',
        '(participant_mode = 0 AND participant_count IS NULL) OR '
        '(participant_mode = 1 AND participant_count IS NOT NULL AND participant_count > 0)',
    )
    op.create_index('ix_game_participant_status', 'game', ['participant_mode', 'status', 'id'])
    op.create_table(
        'game_participant',
        sa.Column(
            'game_id',
            sa.Integer,
            sa.ForeignKey('game.id', name='fk_participant_game', ondelete='RESTRICT'),
            primary_key=True,
        ),
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_participant_user', ondelete='RESTRICT'),
            primary_key=True,
        ),
        sa.Column('position', sa.Integer, nullable=False),
        # Unknown historical join times stay NULL; recorded_at is not a fabricated join time.
        sa.Column('joined_at', DATETIME(fsp=6), nullable=True),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint('game_id', 'position', name='uq_participant_position'),
        sa.CheckConstraint('position >= 0', name='ck_participant_position'),
        sa.CheckConstraint('user_id > 0', name='ck_participant_user_id'),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_participant_user_game', 'game_participant', ['user_id', 'game_id'])


def downgrade():
    raise RuntimeError(
        'Dropping participation loses current membership/order. Restore a verified backup with its matching application version.'
    )
