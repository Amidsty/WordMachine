"""Atomic game command receipts and monotonic game versions (no JSON conversion)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = '0003_game_requests'
down_revision = '0002_sessions_dict'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name']: column for column in inspector.get_columns('game')}
    if 'game_request' in inspector.get_table_names() or 'version' in columns:
        raise RuntimeError(
            'Partial/custom game request schema detected; inspect or restore before retrying migration'
        )
    id_type = columns['id']['type']
    if (
        not isinstance(id_type, sa.Integer)
        or isinstance(id_type, (sa.BigInteger, sa.SmallInteger))
        or getattr(id_type, 'unsigned', False)
        or inspector.get_pk_constraint('game').get('constrained_columns') != ['id']
    ):
        raise RuntimeError(
            'Expected a signed INT game.id primary key before adding receipt foreign keys'
        )
    engine = bind.execute(
        sa.text(
            'SELECT ENGINE FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :name'
        ),
        {'name': 'game'},
    ).scalar_one()
    if engine != 'InnoDB':
        raise RuntimeError('Game command transactions require InnoDB')
    # MySQL DDL commits implicitly. All preflight checks above precede any DDL.
    # Zero is a new observation baseline, not an invented historical change count.
    op.add_column(
        'game', sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('0'))
    )
    op.create_check_constraint('ck_game_version', 'game', 'version >= 0')
    op.create_table(
        'game_request',
        # No actor FK: reservation must not acquire a user shared lock before the
        # game's ordered exclusive user locks. See services/game_requests.py.
        sa.Column('actor_id', sa.Integer, primary_key=True),
        sa.Column('request_id', sa.String(36, collation='ascii_bin'), primary_key=True),
        sa.Column('action', sa.String(16, collation='ascii_bin'), nullable=False),
        sa.Column('payload_hash', sa.String(64, collation='ascii_bin'), nullable=False),
        sa.Column(
            'game_id',
            sa.Integer,
            sa.ForeignKey('game.id', name='fk_request_game', ondelete='RESTRICT'),
            nullable=True,
        ),
        sa.Column('response', LONGTEXT, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_request_game', 'game_request', ['game_id'])


def downgrade():
    raise RuntimeError(
        'Dropping receipts would lose replay protection. Restore a verified backup with its matching application version.'
    )
