"""Optional room display names; IDs and all historical game facts remain intact."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import INTEGER, VARCHAR

revision = '0016_game_names'
down_revision = '0015_dictionary_promotions'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'].lower(): column for column in inspector.get_columns('game')}
    constraints = set(
        bind.execute(
            sa.text(
                'SELECT LOWER(CONSTRAINT_NAME) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()'
            )
        ).scalars()
    )
    if 'name' in columns or 'ck_game_name' in constraints:
        raise RuntimeError('Partial/custom game name schema; inspect or restore before retrying')
    if (
        inspector.get_table_options('game').get('mysql_engine', '').lower() != 'innodb'
        or inspector.get_pk_constraint('game').get('constrained_columns') != ['id']
        or type(columns['id']['type']) is not INTEGER
        or columns['id']['type'].unsigned
    ):
        raise RuntimeError('Game names require an InnoDB signed INT primary key')
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout=:seconds'), {'seconds': min(wait, 30)})
    op.add_column(
        'game',
        sa.Column('name', VARCHAR(100, charset='utf8mb4', collation='utf8mb4_bin'), nullable=True),
    )
    op.create_check_constraint(
        'ck_game_name', 'game', 'name IS NULL OR CHAR_LENGTH(TRIM(name)) BETWEEN 1 AND 100'
    )


def downgrade():
    raise RuntimeError(
        'Game names and their receipts must be preserved; restore a verified backup with matching code'
    )
