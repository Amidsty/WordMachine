"""Server-side sessions, shared auth limits, dictionary ownership and unique usernames."""

from alembic import op
import sqlalchemy as sa

revision = '0002_sessions_dict'
down_revision = '0001_legacy'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    # MySQL DDL implicitly commits: perform all data checks BEFORE altering tables.
    if bind.execute(
        sa.text('SELECT id FROM user WHERE username IS NULL OR TRIM(username) = :empty LIMIT 1'),
        {'empty': ''},
    ).first():
        raise RuntimeError('Null/empty usernames require manual review before migration')
    if bind.execute(
        sa.text('SELECT COUNT(*) FROM user GROUP BY username HAVING COUNT(*) > 1 LIMIT 1')
    ).first():
        raise RuntimeError(
            'Duplicate usernames under the current MySQL collation; resolve explicitly before migration'
        )
    inspector = sa.inspect(bind)
    if {'auth_session', 'auth_rate_limit'} & set(inspector.get_table_names()) or any(
        c['name'] == 'ownerid' for c in inspector.get_columns('dict')
    ):
        raise RuntimeError(
            'Partial/custom auth schema detected; inspect or restore before retrying migration'
        )
    columns = {column['name']: column for column in inspector.get_columns('user')}
    if (
        not isinstance(columns['username']['type'], sa.String)
        or columns['username']['type'].length != 255
    ):
        raise RuntimeError('Expected legacy username VARCHAR(255); review custom schema manually')
    if (
        not isinstance(columns['pwhash']['type'], sa.String)
        or columns['pwhash']['type'].length != 255
    ):
        raise RuntimeError('Expected password storage VARCHAR(255) for scrypt hashes')
    id_type = columns['id']['type']
    if (
        not isinstance(id_type, sa.Integer)
        or isinstance(id_type, (sa.BigInteger, sa.SmallInteger))
        or getattr(id_type, 'unsigned', False)
        or inspector.get_pk_constraint('user').get('constrained_columns') != ['id']
    ):
        raise RuntimeError(
            'Expected a signed INT user.id primary key; review custom schema before adding foreign keys'
        )
    if any(index['name'] == 'uq_user_username' for index in inspector.get_indexes('user')):
        raise RuntimeError(
            'Partial/custom username index detected; inspect before retrying migration'
        )
    # Preserve existing column collation; do not merge or normalize legacy accounts.
    username_type = columns['username']['type']
    op.alter_column('user', 'username', existing_type=username_type, nullable=False)
    op.create_index('uq_user_username', 'user', ['username'], unique=True)
    op.add_column('dict', sa.Column('ownerid', sa.Integer, nullable=True))
    op.create_index('ix_dict_ownerid', 'dict', ['ownerid'])
    op.create_foreign_key('fk_dict_owner', 'dict', 'user', ['ownerid'], ['id'], ondelete='RESTRICT')
    # All existing dictionaries deliberately retain NULL owner (administrator-managed).
    op.create_table(
        'auth_session',
        sa.Column('token_hash', sa.String(64, collation='ascii_bin'), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('user.id', name='fk_session_user', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('csrf_token', sa.String(64, collation='ascii_bin'), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_session_user', 'auth_session', ['user_id'])
    op.create_index('ix_session_expiry', 'auth_session', ['expires_at'])
    op.create_table(
        'auth_rate_limit',
        sa.Column('key_hash', sa.String(64, collation='ascii_bin'), primary_key=True),
        sa.Column('window_started', sa.DateTime, nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False),
        mysql_engine='InnoDB',
    )
    op.create_index('ix_rate_window', 'auth_rate_limit', ['window_started'])


def downgrade():
    raise RuntimeError(
        'scrypt passwords cannot be converted back to SHA-256. Restore a verified backup with its matching application version.'
    )
