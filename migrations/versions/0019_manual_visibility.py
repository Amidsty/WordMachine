"""Opt-in public manual-adjustment metadata; all existing records stay private.

Stop all writers before applying. MySQL DDL commits independently; partial or
custom schemas require review, never adoption or a blind rerun.
"""

import sqlalchemy as sa
from alembic import op

revision = '0019_manual_visibility'
down_revision = '0018_bounded_rating'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'mysql' or bind.dialect.is_mariadb:
        raise RuntimeError('Manual visibility requires MySQL 8.0.16+')
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('manual_rating')}
    constraints = {
        (row['TABLE_NAME'], row['CONSTRAINT_NAME']): row['ENFORCED']
        for row in bind.execute(
            sa.text(
                "SELECT TABLE_NAME,CONSTRAINT_NAME,ENFORCED FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='CHECK'"
            )
        ).mappings()
    }
    if {'publish_reason', 'publish_actor'} & columns or any(
        name.lower() == 'ck_manual_visibility' for _, name in constraints
    ):
        raise RuntimeError('Partial manual visibility schema; inspect before retrying')
    if inspector.get_table_options('manual_rating').get('mysql_engine', '').lower() != 'innodb':
        raise RuntimeError('Manual visibility requires InnoDB')
    if any(
        constraints.get(('manual_rating', name)) != 'YES'
        for name in ('ck_manual_actor_level', 'ck_manual_arithmetic', 'ck_manual_reason')
    ):
        raise RuntimeError('Missing or unenforced manual rating CHECK; review schema')
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout=:wait'), {'wait': min(wait, 30)})
    # One ALTER; never rewrite reasons, actors, receipts, event chains or scores.
    op.execute("""ALTER TABLE manual_rating
        ADD COLUMN publish_reason INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN publish_actor INTEGER NOT NULL DEFAULT 0,
        ADD CONSTRAINT ck_manual_visibility CHECK (
            publish_reason IN (0, 1) AND publish_actor IN (0, 1)
        )""")


def downgrade():
    raise RuntimeError(
        'Manual visibility decisions must be preserved; restore a verified backup with matching code'
    )
