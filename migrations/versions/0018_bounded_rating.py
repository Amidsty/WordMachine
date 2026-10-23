"""Versioned bounded Perf/Rating; preserve all prior answers and award sequences.

Stop all writers. Any partial new column/CHECK is a review-required failure,
not a reason to retry with a new report path. MySQL DDL implicitly commits.
"""

import sqlalchemy as sa
from alembic import op

from wm_app.models import weighted_v2 as schema

revision = '0018_bounded_rating'
down_revision = '0017_weighted_rating'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name != 'mysql' or bind.dialect.is_mariadb:
        raise RuntimeError('Bounded rating requires MySQL 8.0.16+')
    constraints = {
        (r['TABLE_NAME'], r['CONSTRAINT_NAME']): r['ENFORCED']
        for r in bind.execute(
            sa.text(
                "SELECT TABLE_NAME,CONSTRAINT_NAME,ENFORCED FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='CHECK'"
            )
        ).mappings()
    }
    columns = {c['name'] for c in inspector.get_columns('game_rating_snapshot')}
    new_names = {new for _, _, new, _ in schema.REPLACEMENTS}
    new_names.add('ck_weighted_snapshot_rule_v2')
    if 'rule_version' in columns or new_names.intersection(name.lower() for _, name in constraints):
        raise RuntimeError('Partial bounded schema; inspect before retrying')
    for table, old, _, _ in schema.REPLACEMENTS:
        if constraints.get((table, old)) != 'YES':
            raise RuntimeError('Missing or unenforced prior scoring CHECK; review schema')
    for table in {'game_rating_snapshot', *(r[0] for r in schema.REPLACEMENTS)}:
        if inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb':
            raise RuntimeError('Bounded rating requires InnoDB')
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout=:wait'), {'wait': min(wait, 30)})
    op.add_column(
        'game_rating_snapshot',
        sa.Column(
            'rule_version',
            sa.String(32, collation='ascii_bin'),
            nullable=False,
            server_default='weighted-rating-v1',
        ),
    )
    op.create_check_constraint(
        'ck_weighted_snapshot_rule_v2', 'game_rating_snapshot', schema.SNAPSHOT_CHECK
    )
    for table, old, new, expression in schema.REPLACEMENTS:
        # One atomic ALTER never leaves this table without its scoring constraint.
        op.execute(
            f'ALTER TABLE `{table}` DROP CHECK `{old}`, ADD CONSTRAINT `{new}` CHECK ({expression})'
        )
    # No status change, account reinitialization, quota refill, receipt or score rewrite.


def downgrade():
    raise RuntimeError(
        'Bounded rating facts must be preserved; restore a verified backup with matching code'
    )
