from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL

from wm_app.config import load_config
from wm_app.models import Base


def database_url(config):
    return URL.create(
        'mysql+pymysql',
        username=config['DB_USER'],
        password=config['DB_PASSWORD'],
        host=config['DB_HOST'],
        port=config['DB_PORT'],
        database=config['DB_NAME'],
        query={'charset': 'utf8mb4'},
    )


def migrate(connection):
    if connection.dialect.name != 'mysql':
        raise RuntimeError('Migrations require MySQL; SQLite is not supported')
    if connection.dialect.is_mariadb or connection.dialect.server_version_info < (8, 0, 16):
        raise RuntimeError(
            'MySQL 8.0.16+ is required for enforced CHECK constraints and FOR SHARE; MariaDB is not supported'
        )
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        'Online schema/data preflight is required; offline SQL generation is not supported'
    )
elif context.config.attributes.get('connection') is not None:
    migrate(context.config.attributes['connection'])
else:
    engine = create_engine(database_url(load_config()), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()
