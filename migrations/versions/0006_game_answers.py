"""Relational answers for new games; do not convert or rescore legacy JSON."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, DOUBLE, INTEGER

revision = '0006_game_answers'
down_revision = '0005_game_participants'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'].lower(): column for column in inspector.get_columns('game')}
    names = {
        'ck_game_answers',
        'fk_answer_question',
        'fk_answer_participant',
        'ck_answer_position',
        'ck_answer_correct',
        'ck_answer_combos',
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
        'game_answer' in {name.lower() for name in inspector.get_table_names()}
        or {'answer_mode', 'answer_count'} & columns.keys()
        or names & constraints
    ):
        raise RuntimeError(
            'Partial/custom answer schema detected; inspect or restore before retrying migration'
        )
    if not columns['result']['nullable']:
        raise RuntimeError('Expected nullable game.result before moving new answers to relations')
    for field in ('question_mode', 'participant_mode'):
        if type(columns[field]['type']) is not INTEGER or columns[field]['nullable']:
            raise RuntimeError(
                'Expected nonnullable INT question/participant modes before adding answer metadata'
            )
    for table, keys in (
        ('game', ['id']),
        ('game_question', ['game_id', 'position']),
        ('game_participant', ['game_id', 'user_id']),
    ):
        fields = {column['name']: column for column in inspector.get_columns(table)}
        if inspector.get_pk_constraint(table).get('constrained_columns') != keys or any(
            type(fields[key]['type']) is not INTEGER
            or getattr(fields[key]['type'], 'unsigned', False)
            for key in keys
        ):
            raise RuntimeError(
                'Expected signed INT parent primary keys before adding answer foreign keys'
            )
    engines = dict(
        bind.execute(
            sa.text("""SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('game', 'game_question', 'game_participant')""")
        ).all()
    )
    if engines != {table: 'InnoDB' for table in ('game', 'game_question', 'game_participant')}:
        raise RuntimeError('Answer transactions require InnoDB parent tables')
    # All preflights precede the first potentially auto-committing MySQL DDL.
    op.add_column(
        'game', sa.Column('answer_mode', sa.Integer, nullable=False, server_default=sa.text('0'))
    )
    op.add_column('game', sa.Column('answer_count', sa.Integer, nullable=True))
    op.create_check_constraint(
        'ck_game_answers',
        'game',
        '(answer_mode = 0 AND answer_count IS NULL) OR '
        '(answer_mode = 1 AND answer_count IS NOT NULL AND answer_count >= 0 '
        'AND question_mode = 1 AND participant_mode = 1)',
    )
    op.create_table(
        'game_answer',
        sa.Column('game_id', sa.Integer, primary_key=True),
        sa.Column('position', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, nullable=False),
        # Unicode lowercasing can expand a 255-character submission. No truncation.
        sa.Column('answer', sa.Text, nullable=False),
        sa.Column('correct', sa.Boolean, nullable=False),
        sa.Column('usercombo', sa.Integer, nullable=False),
        sa.Column('globalcombo', sa.Integer, nullable=False),
        # Preserve Python binary64 scoring, not FLOAT/rounded DECIMAL.
        sa.Column('perf_delta', DOUBLE(asdecimal=False), nullable=False),
        sa.Column('perf', DOUBLE(asdecimal=False), nullable=False),
        sa.Column('rating_version', sa.String(32, collation='ascii_bin'), nullable=False),
        sa.Column('answered_at', DATETIME(fsp=6), nullable=True),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ['game_id', 'position'],
            ['game_question.game_id', 'game_question.position'],
            name='fk_answer_question',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['game_id', 'user_id'],
            ['game_participant.game_id', 'game_participant.user_id'],
            name='fk_answer_participant',
            ondelete='RESTRICT',
        ),
        sa.CheckConstraint('position >= 0', name='ck_answer_position'),
        sa.CheckConstraint('correct IN (0, 1)', name='ck_answer_correct'),
        sa.CheckConstraint('usercombo >= 0 AND globalcombo >= 0', name='ck_answer_combos'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_bin',
    )
    op.create_index('ix_answer_participant', 'game_answer', ['game_id', 'user_id', 'position'])


def downgrade():
    raise RuntimeError(
        'Dropping answers loses recorded outcomes and scores. Restore a verified backup with its matching application version.'
    )
