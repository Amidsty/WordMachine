"""Immutable questions for new games; never reconstruct old text from live words."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import VARCHAR

revision = '0004_game_questions'
down_revision = '0003_game_requests'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name']: column for column in inspector.get_columns('game')}
    if (
        'game_question' in inspector.get_table_names()
        or {'question_mode', 'dictname_snapshot'} & columns.keys()
        or any(
            check['name'] == 'ck_game_question_mode'
            for check in inspector.get_check_constraints('game')
        )
    ):
        raise RuntimeError(
            'Partial/custom question snapshot schema detected; inspect or restore before retrying migration'
        )
    id_type = columns['id']['type']
    if (
        not isinstance(id_type, sa.Integer)
        or isinstance(id_type, (sa.BigInteger, sa.SmallInteger))
        or getattr(id_type, 'unsigned', False)
        or inspector.get_pk_constraint('game').get('constrained_columns') != ['id']
    ):
        raise RuntimeError(
            'Expected a signed INT game.id primary key before adding question foreign keys'
        )
    engines = dict(
        bind.execute(
            sa.text("""SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('game', 'dict', 'word')""")
        ).all()
    )
    if engines != {'game': 'InnoDB', 'dict': 'InnoDB', 'word': 'InnoDB'}:
        raise RuntimeError('Consistent question capture requires InnoDB game, dict and word tables')
    # All preflight checks precede DDL, which MySQL may implicitly commit.
    # 0 explicitly means live legacy references, NOT recovered historical text.
    op.add_column(
        'game', sa.Column('question_mode', sa.Integer, nullable=False, server_default=sa.text('0'))
    )
    op.add_column(
        'game',
        sa.Column('dictname_snapshot', VARCHAR(255, charset='utf8mb4', collation='utf8mb4_bin')),
    )
    op.create_check_constraint('ck_game_question_mode', 'game', 'question_mode IN (0, 1)')
    op.create_table(
        'game_question',
        sa.Column(
            'game_id',
            sa.Integer,
            sa.ForeignKey('game.id', name='fk_question_game', ondelete='RESTRICT'),
            primary_key=True,
        ),
        sa.Column('position', sa.Integer, primary_key=True),
        # Provenance only: no FK to mutable/deletable source words.
        sa.Column('word_id', sa.Integer, nullable=False),
        sa.Column('english', sa.String(255), nullable=False),
        sa.Column('chinese', sa.String(255), nullable=False),
        sa.UniqueConstraint('game_id', 'word_id', name='uq_question_word'),
        sa.CheckConstraint('position >= 0', name='ck_question_position'),
        sa.CheckConstraint('word_id > 0', name='ck_question_word_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_bin',
    )


def downgrade():
    raise RuntimeError(
        'Dropping snapshots loses original questions. Restore a verified backup with its matching application version.'
    )
