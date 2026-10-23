"""Explicitly reviewed administrator levels and administrative audit records."""

import json

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.mysql import DATETIME

revision = '0009_admin_levels'
down_revision = '0008_list_indexes'
branch_labels = depends_on = None


def _unique_mapping(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError('Duplicate administrator mapping key')
        result[key] = value
    return result


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'].lower() for column in inspector.get_columns('user')}
    if {'admin_level', 'admin_version'} & columns or 'admin_audit' in {
        name.lower() for name in inspector.get_table_names()
    }:
        raise RuntimeError(
            'Partial/custom admin schema detected; inspect or restore, do not retry blindly'
        )
    users = bind.execute(sa.text('SELECT id, type FROM user')).mappings().all()
    if any(row['type'] not in ('normal', 'root') for row in users):
        raise RuntimeError(
            'Unknown legacy roles require manual review before administrator migration'
        )
    roots = {row['id'] for row in users if row['type'] == 'root'}
    mapping = context.config.attributes.get('admin_levels')
    if mapping is None:
        mapping = json.loads(
            context.get_x_argument(as_dictionary=True).get('admin_levels', '{}'),
            object_pairs_hook=_unique_mapping,
        )
    if (
        not isinstance(mapping, dict)
        or any(
            not isinstance(key, str)
            or not key.isascii()
            or not key.isdigit()
            or str(int(key)) != key
            or int(key) <= 0
            or type(value) is not int
            or not 1 <= value <= 5
            for key, value in mapping.items()
        )
        or {int(key) for key in mapping} != roots
    ):
        raise RuntimeError(
            'Provide an exact reviewed mapping for ALL existing root IDs: -x admin_levels=\'{"ID":LEVEL}\' (levels 1-5); no accounts are automatically promoted'
        )
    # All preflight checks precede the first DDL. MySQL DDL is not transactional.
    op.add_column('user', sa.Column('admin_level', sa.Integer, nullable=False, server_default='0'))
    op.add_column(
        'user', sa.Column('admin_version', sa.Integer, nullable=False, server_default='0')
    )
    op.execute("ALTER TABLE user ALTER COLUMN type SET DEFAULT 'normal'")
    for key, level in sorted(mapping.items(), key=lambda pair: int(pair[0])):
        result = bind.execute(
            sa.text("UPDATE user SET admin_level = :level WHERE id = :id AND type = 'root'"),
            {'level': level, 'id': int(key)},
        )
        if result.rowcount != 1:
            raise RuntimeError(
                'Administrator mapping changed during migration; stop all writers and inspect'
            )
    op.create_check_constraint('ck_user_admin_level', 'user', 'admin_level BETWEEN 0 AND 5')
    op.create_check_constraint(
        'ck_user_admin_version', 'user', 'admin_version BETWEEN 0 AND 2147483647'
    )
    op.create_check_constraint(
        'ck_user_admin_type',
        'user',
        "type IS NOT NULL AND ((admin_level = 0 AND type = 'normal') OR (admin_level > 0 AND type = 'root'))",
    )
    op.create_table(
        'admin_audit',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            'actor_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_admin_audit_actor', ondelete='RESTRICT'),
            nullable=True,
        ),
        sa.Column('actor_level', sa.Integer, nullable=True),
        sa.Column(
            'target_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_admin_audit_target', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('before_data', sa.JSON, nullable=False),
        sa.Column('after_data', sa.JSON, nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('recorded_at', DATETIME(fsp=6), nullable=False),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_admin_audit_target_id', 'admin_audit', ['target_id', 'id'])
    for key, level in mapping.items():
        bind.execute(
            sa.text(
                "INSERT INTO admin_audit (actor_id, actor_level, target_id, action, before_data, after_data, reason, source, recorded_at) VALUES (NULL, NULL, :id, 'migrate-level', :before, :after, 'Explicit reviewed legacy administrator mapping', 'migration', UTC_TIMESTAMP(6))"
            ),
            {
                'id': int(key),
                'before': json.dumps({'type': 'root'}),
                'after': json.dumps({'admin_level': level}),
            },
        )
        bind.execute(sa.text('DELETE FROM auth_session WHERE user_id = :id'), {'id': int(key)})


def downgrade():
    raise RuntimeError(
        'Dropping administrator levels can restore broader permissions and lose audit history. Restore a verified backup with its matching application, never downgrade automatically.'
    )
