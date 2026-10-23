"""Measured list indexes only; never rewrite business rows or adopt partial DDL."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import INTEGER, TINYINT

revision = '0008_list_indexes'
down_revision = '0007_game_settlements'
branch_labels = depends_on = None

# Frozen migration definitions, intentionally independent of evolving application metadata.
INDEXES = (
    ('word', 'ix_word_dict_deleted_id', (('dictid', 'A'), ('deleted', 'A'), ('id', 'A'))),
    ('user', 'ix_user_deleted_rating_id', (('deleted', 'A'), ('rating', 'D'), ('id', 'A'))),
)


def _preflight(*, upgrading):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Check BOTH tables before the first implicit-commit ALTER.
    for table, name, parts in INDEXES:
        if inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb':
            raise RuntimeError('List indexes require InnoDB word and user tables')
        columns = {column['name'].lower(): column for column in inspector.get_columns(table)}
        if inspector.get_pk_constraint(table).get('constrained_columns') != ['id']:
            raise RuntimeError('Expected signed INT word/user primary keys before list indexes')
        for column, _ in parts:
            field = columns.get(column, {})
            kind = field.get('type')
            expected = TINYINT if column == 'deleted' else INTEGER
            if type(kind) is not expected or getattr(kind, 'unsigned', False):
                raise RuntimeError('Unexpected list-index column type; inspect the schema')
        rows = (
            bind.execute(
                sa.text(
                    'SELECT COLUMN_NAME, COLLATION, SEQ_IN_INDEX, NON_UNIQUE, SUB_PART, '
                    'INDEX_TYPE, IS_VISIBLE, EXPRESSION FROM information_schema.STATISTICS '
                    'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :name '
                    'ORDER BY SEQ_IN_INDEX'
                ),
                {'table': table, 'name': name},
            )
            .mappings()
            .all()
        )
        if upgrading:
            if rows:
                raise RuntimeError(
                    'Partial/custom list index detected; inspect or restore before retrying migration'
                )
        else:
            actual = tuple(
                (
                    row['COLUMN_NAME'].lower() if isinstance(row['COLUMN_NAME'], str) else None,
                    row['COLLATION'],
                )
                for row in rows
            )
            if actual != parts or any(
                row['NON_UNIQUE'] != 1
                or row['SUB_PART'] is not None
                or row['INDEX_TYPE'] != 'BTREE'
                or row['IS_VISIBLE'] != 'YES'
                or row['EXPRESSION'] is not None
                or row['SEQ_IN_INDEX'] != index
                for index, row in enumerate(rows, 1)
            ):
                raise RuntimeError(
                    'Missing/custom list index; refusing to drop an unverified index'
                )
            # Do not remove an index on which later/custom foreign keys may depend.
            keys = [column for column, _ in parts]
            if any(
                [column.lower() for column in foreign['constrained_columns']]
                == keys[: len(foreign['constrained_columns'])]
                for foreign in inspector.get_foreign_keys(table)
            ):
                raise RuntimeError(
                    'A foreign key may depend on a list index; inspect before downgrade'
                )
            # MySQL may report NULL UNIQUE_CONSTRAINT_NAME for a nonunique
            # referenced index. Compare ordered referenced columns instead.
            referenced = {}
            rows = bind.execute(
                sa.text(
                    'SELECT CONSTRAINT_SCHEMA, TABLE_NAME, CONSTRAINT_NAME, REFERENCED_COLUMN_NAME '
                    'FROM information_schema.KEY_COLUMN_USAGE '
                    'WHERE REFERENCED_TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME = :table '
                    'ORDER BY CONSTRAINT_SCHEMA, TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION'
                ),
                {'table': table},
            ).mappings()
            for row in rows:
                key = (row['CONSTRAINT_SCHEMA'], row['TABLE_NAME'], row['CONSTRAINT_NAME'])
                referenced.setdefault(key, []).append(row['REFERENCED_COLUMN_NAME'].lower())
            if any(columns == keys[: len(columns)] for columns in referenced.values()):
                raise RuntimeError(
                    'A foreign key may depend on a list index; inspect before downgrade'
                )


@contextmanager
def _metadata_lock_limit():
    bind = op.get_bind()
    previous = bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one()
    bind.execute(
        sa.text('SET SESSION lock_wait_timeout = :seconds'), {'seconds': min(previous, 30)}
    )
    try:
        yield
    finally:
        # A lost connection cannot be restored. Do not reconnect just to reset it.
        if not bind.invalidated:
            bind.execute(sa.text('SET SESSION lock_wait_timeout = :seconds'), {'seconds': previous})


def upgrade():
    with _metadata_lock_limit():
        _preflight(upgrading=True)
        for table, name, parts in INDEXES:
            columns = ', '.join(
                f'`{column}`' + (' DESC' if direction == 'D' else '') for column, direction in parts
            )
            # No implicit COPY or stronger-lock fallback. LOCK=NONE still needs
            # metadata locks; the session cap limits each wait, not total build time.
            op.execute(
                f'ALTER TABLE `{table}` ADD INDEX `{name}` ({columns}), ALGORITHM=INPLACE, LOCK=NONE'
            )


def downgrade():
    with _metadata_lock_limit():
        _preflight(upgrading=False)
        # Only these two verified, nonunique indexes. Earlier migrations stay irreversible.
        for table, name, _ in reversed(INDEXES):
            op.execute(f'ALTER TABLE `{table}` DROP INDEX `{name}`, ALGORITHM=INPLACE, LOCK=NONE')
