"""Legacy MySQL adapter. No schema creation or migration during startup."""

from contextlib import contextmanager

import pymysql
from flask import current_app


def get_db_connection():
    config = current_app.config
    return pymysql.connect(
        host=config['DB_HOST'],
        port=config['DB_PORT'],
        user=config['DB_USER'],
        password=config['DB_PASSWORD'],
        database=config['DB_NAME'],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        # Consistent state/audit reads and question capture must not inherit a
        # server's READ UNCOMMITTED setting. Locking reads remain current reads.
        init_command='SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ',
        connect_timeout=config['DB_CONNECT_TIMEOUT'],
        read_timeout=config['DB_READ_TIMEOUT'],
        write_timeout=config['DB_WRITE_TIMEOUT'],
    )


@contextmanager
def transaction():
    """Commit once; rollback on every failure; always release the connection."""
    conn = get_db_connection()
    try:
        conn.begin()
        with conn.cursor() as cursor:
            yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def reading():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.close()
