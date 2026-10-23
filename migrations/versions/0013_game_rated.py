"""Freeze Rated/Unrated at creation; preserve existing games as Rated."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import INTEGER

revision = '0013_game_rated'
down_revision = '0012_manual_rating'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item['name'].lower(): item for item in inspector.get_columns('game')}
    names = {'ck_game_rated', 'ck_settlement_rating_policy'}
    existing = {
        name.lower()
        for name in bind.execute(
            sa.text(
                'SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE()'
            )
        ).scalars()
    }
    if 'rated' in columns or names & existing:
        raise RuntimeError(
            'Partial/custom Rated schema detected; inspect or restore before retrying'
        )
    for table, key in [('game', 'id'), ('game_settlement', 'game_id')]:
        fields = {item['name']: item for item in inspector.get_columns(table)}
        kind = fields[key]['type']
        if (
            inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb'
            or inspector.get_pk_constraint(table).get('constrained_columns') != [key]
            or type(kind) is not INTEGER
            or getattr(kind, 'unsigned', False)
        ):
            raise RuntimeError('Rated games require existing InnoDB signed INT primary keys')
    settlement = {item['name']: item for item in inspector.get_columns('game_settlement')}
    count_type = settlement['rated_count']['type']
    rule_type = settlement['rating_version']['type']
    if (
        type(count_type) is not INTEGER
        or getattr(count_type, 'unsigned', False)
        or settlement['rated_count']['nullable']
        or settlement['rating_version']['nullable']
        or not isinstance(rule_type, sa.String)
        or rule_type.length != 32
    ):
        raise RuntimeError('Partial/custom settlement column shapes require review')
    if bind.execute(
        sa.text(
            "SELECT game_id FROM game_settlement WHERE rating_version <> 'legacy-v1' OR rated_count < 0 LIMIT 1"
        )
    ).first():
        raise RuntimeError('Existing settlement rules require review before Rated migration')
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout = :seconds'), {'seconds': min(wait, 30)})
    # MySQL DDL implicitly commits. All preflights precede the first ALTER.
    op.execute(
        'ALTER TABLE game ADD COLUMN rated INT NOT NULL DEFAULT 1, ADD CONSTRAINT ck_game_rated CHECK (rated IN (0, 1))'
    )
    op.create_check_constraint(
        'ck_settlement_rating_policy',
        'game_settlement',
        "rating_version = 'legacy-v1' OR (rating_version = 'unrated-v1' AND rated_count = 0)",
    )


def downgrade():
    raise RuntimeError(
        'Unrated results must not become Rated. Restore a verified backup and matching application; do not discard rating policy.'
    )
