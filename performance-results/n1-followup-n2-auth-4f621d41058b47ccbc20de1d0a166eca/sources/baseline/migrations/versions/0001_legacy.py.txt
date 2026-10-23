"""Adopt a complete legacy schema, or explicitly initialize an empty database."""

from alembic import op
import sqlalchemy as sa

revision = '0001_legacy'
down_revision = None
branch_labels = depends_on = None

REQUIRED = {
    'user': {
        'id',
        'username',
        'pwhash',
        'introduction',
        'rating',
        'type',
        'deleted',
        'gamehistory',
        'ratinghistory',
    },
    'dict': {'id', 'dictname', 'deleted'},
    'word': {'id', 'dictid', 'english', 'chinese', 'deleted'},
    'game': {
        'id',
        'ownerid',
        'dictid',
        'users',
        'wordlist',
        'result',
        'perf',
        'ratingdelta',
        'status',
    },
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    existing = tables & REQUIRED.keys()
    if existing:
        if existing != REQUIRED.keys():
            raise RuntimeError('Incomplete legacy schema; repair manually before migrating')
        for table, required in REQUIRED.items():
            columns = {column['name'] for column in inspector.get_columns(table)}
            if not required <= columns:
                raise RuntimeError(f'Missing columns in {table}; inspect the legacy schema')
            if inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb':
                raise RuntimeError(
                    f'{table} must use InnoDB; migration will not convert it automatically'
                )
        return  # Existing data is adopted, never copied or overwritten.
    if tables - {'alembic_version'}:
        raise RuntimeError(
            'Database is not empty and has no legacy schema; choose a dedicated database'
        )
    op.create_table(
        'user',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        *[sa.Column(name, sa.String(255)) for name in ('username', 'pwhash', 'introduction')],
        sa.Column('rating', sa.Integer),
        sa.Column('type', sa.String(255)),
        sa.Column('deleted', sa.Boolean),
        sa.Column('gamehistory', sa.Text),
        sa.Column('ratinghistory', sa.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'dict',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('dictname', sa.String(255)),
        sa.Column('deleted', sa.Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'word',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('dictid', sa.Integer),
        sa.Column('english', sa.String(255)),
        sa.Column('chinese', sa.String(255)),
        sa.Column('deleted', sa.Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'game',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ownerid', sa.Integer),
        sa.Column('dictid', sa.Integer),
        *[
            sa.Column(name, sa.Text)
            for name in ('users', 'wordlist', 'result', 'perf', 'ratingdelta')
        ],
        sa.Column('status', sa.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )


def downgrade():
    raise RuntimeError(
        'Refusing to drop adopted business tables. Restore a verified backup instead.'
    )
