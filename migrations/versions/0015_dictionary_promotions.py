"""Owner applications and level-four review; existing dictionaries unchanged."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME, INTEGER

revision = '0015_dictionary_promotions'
down_revision = '0014_rated_bounds'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = {
        'fk_promotion_dict',
        'fk_promotion_applicant',
        'fk_promotion_reviewer',
        'ck_promotion_state',
        'ck_promotion_reason',
        'ck_promotion_decision',
        'uq_promotion_pending',
        'uq_promotion_version',
    }
    existing = set(
        bind.execute(
            sa.text(
                'SELECT LOWER(CONSTRAINT_NAME) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()'
            )
        ).scalars()
    )
    if (
        'dictionary_promotion'
        in {name.lower() for name in inspector.get_table_names() + inspector.get_view_names()}
        or names & existing
    ):
        raise RuntimeError('Partial/custom promotion schema; inspect or restore before retrying')
    for table in ('dict', 'user'):
        kind = {column['name']: column for column in inspector.get_columns(table)}['id']['type']
        if (
            inspector.get_table_options(table).get('mysql_engine', '').lower() != 'innodb'
            or inspector.get_pk_constraint(table).get('constrained_columns') != ['id']
            or type(kind) is not INTEGER
            or kind.unsigned
        ):
            raise RuntimeError('Promotion requires InnoDB signed INT primary keys')
    wait = int(bind.execute(sa.text('SELECT @@session.lock_wait_timeout')).scalar_one())
    bind.execute(sa.text('SET SESSION lock_wait_timeout=:seconds'), {'seconds': min(wait, 30)})
    op.create_table(
        'dictionary_promotion',
        sa.Column('request_id', sa.String(36, collation='ascii_bin'), primary_key=True),
        sa.Column(
            'dict_id',
            sa.Integer,
            sa.ForeignKey('dict.id', name='fk_promotion_dict', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'applicant_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_promotion_applicant', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('submit_hash', sa.String(64), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('submitted_at', DATETIME(fsp=6), nullable=False),
        sa.Column('state', sa.Integer, nullable=False, server_default='0'),
        sa.Column(
            'pending_dict_id',
            sa.Integer,
            sa.Computed('CASE WHEN state = 0 THEN dict_id ELSE NULL END', persisted=True),
        ),
        sa.Column(
            'reviewer_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_promotion_reviewer', ondelete='RESTRICT'),
        ),
        sa.Column('reviewer_level', sa.Integer),
        sa.Column('review_reason', sa.String(500)),
        sa.Column('reviewed_at', DATETIME(fsp=6)),
        sa.Column('review_hash', sa.String(64)),
        sa.Column('reviewed_fingerprint', sa.String(64)),
        sa.Column('rated_min', sa.Integer),
        sa.Column('rated_max', sa.Integer),
        sa.Column('result_version', sa.Integer),
        sa.UniqueConstraint('pending_dict_id', name='uq_promotion_pending'),
        sa.UniqueConstraint('dict_id', 'result_version', name='uq_promotion_version'),
        sa.CheckConstraint('state IN (0,1,2)', name='ck_promotion_state'),
        sa.CheckConstraint('CHAR_LENGTH(reason) BETWEEN 1 AND 500', name='ck_promotion_reason'),
        sa.CheckConstraint(
            '(state = 0 AND reviewer_id IS NULL AND reviewer_level IS NULL AND review_reason IS NULL AND reviewed_at IS NULL AND review_hash IS NULL AND reviewed_fingerprint IS NULL AND rated_min IS NULL AND rated_max IS NULL AND result_version IS NULL) OR (state IN (1,2) AND reviewer_id IS NOT NULL AND reviewer_level IS NOT NULL AND reviewer_level IN (4,5) AND review_reason IS NOT NULL AND CHAR_LENGTH(review_reason) BETWEEN 1 AND 500 AND reviewed_at IS NOT NULL AND review_hash IS NOT NULL AND ((state = 1 AND reviewed_fingerprint IS NOT NULL AND rated_min IS NOT NULL AND rated_max IS NOT NULL AND rated_min <= rated_max AND result_version IS NOT NULL AND result_version > 0) OR (state = 2 AND reviewed_fingerprint IS NULL AND rated_min IS NULL AND rated_max IS NULL AND result_version IS NULL)))',
            name='ck_promotion_decision',
        ),
        mysql_engine='InnoDB',
    )
    op.create_index(
        'ix_promotion_applicant',
        'dictionary_promotion',
        ['applicant_id', 'submitted_at', 'request_id'],
    )
    op.create_index(
        'ix_promotion_state', 'dictionary_promotion', ['state', 'submitted_at', 'request_id']
    )


def downgrade():
    raise RuntimeError(
        'Promotion decisions must be retained; restore a verified backup with matching code'
    )
