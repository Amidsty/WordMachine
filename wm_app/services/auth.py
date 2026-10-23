import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from flask import current_app
from pymysql import IntegrityError

from ..db import reading, transaction
from ..security.passwords import dummy_hash, hash_password, is_legacy_hash, verify_password
from ..security.permissions import admin_level as level_of
from ..security.permissions import (
    lock_actor,
    lock_users,
    require_manage_user,
    require_reset_password,
    require_root,
    require_set_admin_level,
)
from .admin_policy import (
    MASTER_NAME,
    audit,
    capabilities,
    master_password,
    next_version,
    validate_level,
)
from .errors import ApiError
from .pagination import ListQuery, page_offset
from .validation import password as validate_password
from .validation import string
from .validation import username as validate_username

TOKEN_PATTERN = re.compile(r'^[0-9a-f]{64}$')
PUBLIC_FIELDS = ('id', 'username', 'introduction', 'rating', 'type', 'admin_level')


@dataclass(frozen=True)
class Identity:
    token_hash: str
    csrf_token: str
    user: dict
    expires_at: datetime


def public_user(row):
    result = {key: row.get(key) for key in PUBLIC_FIELDS}
    result['admin_level'] = level_of(row)
    result['type'] = 'root' if result['admin_level'] else 'normal'
    return result


def public_person(row):
    """Name/colour metadata only; absent or inactive ratings remain unknown."""
    if row is None:
        return None
    return {
        'id': row['id'],
        'username': row['username'],
        'rating': row.get('rating') if row.get('deleted') == 0 else None,
    }


def token_digest(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def resolve_digest(digest):
    if not isinstance(digest, str) or not TOKEN_PATTERN.fullmatch(digest):
        return None
    with reading() as cursor:
        cursor.execute(
            """SELECT s.token_hash, s.csrf_token, s.expires_at,
                          u.id, u.username, u.introduction, u.rating, u.type, u.admin_level
                          FROM auth_session s JOIN user u ON u.id = s.user_id
                          WHERE s.token_hash = %s AND s.expires_at > %s AND u.deleted = 0""",
            (digest, datetime.utcnow()),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return Identity(row['token_hash'], row['csrf_token'], public_user(row), row['expires_at'])


def resolve_session(token):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        return None
    return resolve_digest(token_digest(token))


def create_user(username, password, introduction='', *, role='normal', level=None):
    username = validate_username(username)
    password = validate_password(password)
    introduction = string(introduction, 'Introduction')
    if role not in ('normal', 'root'):
        raise ValueError('Unsupported role')
    level = validate_level((1 if role == 'root' else 0) if level is None else level)
    if (role == 'normal') != (level == 0):
        raise ValueError('Role and administrator level disagree')
    if username.casefold() == 'master' and (level != 5 or username != MASTER_NAME):
        raise ApiError('MASTER is reserved for explicit highest-level initialization')
    if level == 5:
        if username != MASTER_NAME:
            raise ApiError('New level 5 accounts must be named MASTER')
        password = master_password(password)
    encoded = hash_password(password)
    try:
        with transaction() as cursor:
            cursor.execute(
                'INSERT INTO user (username, pwhash, introduction, rating, type, deleted, admin_level) VALUES (%s, %s, %s, 0, %s, 0, %s)',
                (username, encoded, introduction, role, level),
            )
            uid = cursor.lastrowid
            from .weighted_games import register

            register(cursor, uid)
            if level:
                audit(cursor, None, uid, 'create-admin', {}, {'admin_level': level}, source='cli')
    except IntegrityError as error:
        if error.args[0] == 1062:
            raise ApiError('Username already exists', 409, 'username_exists') from None
        raise
    return {
        'id': uid,
        'username': username,
        'introduction': introduction,
        'rating': 0,
        'type': role,
        'admin_level': level,
    }


def login(username, password, old_token=None):
    username = validate_username(username, new=False)
    password = validate_password(password, new=False)
    token, csrf = secrets.token_hex(32), secrets.token_hex(32)
    now = datetime.utcnow()
    expiry = now + timedelta(seconds=current_app.config['AUTH_SESSION_SECONDS'])
    with transaction() as cursor:
        # Serialize password checks/upgrades/session issuance with resets and bans.
        cursor.execute('SELECT * FROM user WHERE username = %s FOR UPDATE', (username,))
        row = cursor.fetchone()
        stored = row['pwhash'] if row and row['deleted'] == 0 else dummy_hash()
        valid = verify_password(stored, password)
        if not row or row['deleted'] != 0 or not valid:
            raise ApiError('Invalid username or password', 401, 'invalid_credentials')
        if is_legacy_hash(stored):
            cursor.execute(
                'UPDATE user SET pwhash = %s WHERE id = %s',
                (hash_password(password.strip()), row['id']),
            )
        if isinstance(old_token, str) and TOKEN_PATTERN.fullmatch(old_token):
            cursor.execute(
                'DELETE FROM auth_session WHERE token_hash = %s', (token_digest(old_token),)
            )
        cursor.execute(
            'INSERT INTO auth_session (token_hash, user_id, csrf_token, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)',
            (token_digest(token), row['id'], csrf, now, expiry),
        )
    return token, Identity(token_digest(token), csrf, public_user(row), expiry)


def logout(identity):
    with transaction() as cursor:
        cursor.execute('DELETE FROM auth_session WHERE token_hash = %s', (identity.token_hash,))


def update_user(actor_id, target_id, data):
    if actor_id != target_id:
        raise ApiError('Cannot update another user', 403, 'forbidden')
    introduction = data.get('introduction')
    new_password = data.get('new_password')
    if introduction is not None:
        introduction = string(introduction, 'Introduction')
    changed_password = new_password not in (None, '')
    if changed_password:
        new_password = validate_password(new_password)
        current_password = validate_password(data.get('current_password'), new=False)
    if introduction is None and not changed_password:
        raise ApiError('No updates provided')
    with transaction() as cursor:
        user = lock_actor(cursor, actor_id)
        if changed_password:
            if level_of(user) == 5:
                master_password(new_password)
            if not verify_password(user['pwhash'], current_password):
                raise ApiError('Current password incorrect', 401, 'invalid_credentials')
            cursor.execute(
                'UPDATE user SET pwhash = %s WHERE id = %s', (hash_password(new_password), actor_id)
            )
            cursor.execute('DELETE FROM auth_session WHERE user_id = %s', (actor_id,))
        if introduction is not None:
            cursor.execute(
                'UPDATE user SET introduction = %s WHERE id = %s', (introduction, actor_id)
            )
            user['introduction'] = introduction
    return {
        'reauthenticate': changed_password,
        'user': public_user(user),
        'message': 'User updated successfully',
    }


def get_user(uid):
    with reading() as cursor:
        cursor.execute(
            'SELECT id, username, introduction, rating, type, admin_level FROM user WHERE id = %s AND deleted = 0',
            (uid,),
        )
        user = cursor.fetchone()
    if not user:
        raise ApiError('User not found', 404, 'not_found')
    return public_user(user)


def managed_user(actor_id, target_id):
    """Read one management card without exposing password/session/history fields."""
    with reading() as cursor:
        cursor.execute(
            'SELECT id, username, introduction, rating, type, deleted, admin_level, admin_version '
            'FROM user WHERE id IN (%s, %s)',
            (actor_id, target_id),
        )
        users = {row['id']: row for row in cursor.fetchall()}
        actor = users.get(actor_id)
        if actor is None or actor['deleted'] != 0:
            raise ApiError('Authentication required', 401, 'unauthenticated')
        require_root(actor)
        target = users.get(target_id)
        if target is None:
            raise ApiError('User not found', 404, 'not_found')
        return {
            **public_user(target),
            'deleted': target['deleted'],
            'admin_version': target['admin_version'],
            'capabilities': capabilities(actor, target),
        }


def list_users(actor, include_deleted=False, query=ListQuery()):
    require_root(actor)
    where, params = ('1 = 1' if include_deleted else 'deleted = 0'), []
    if query.q:
        where += " AND username LIKE %s ESCAPE '!'"
        params.append(query.like)
    with reading() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM user WHERE ' + where, params)
        pagination = query.metadata(cursor.fetchone()['total'])
        if pagination['total'] == 0:
            return {'users': [], 'pagination': pagination}
        offset = page_offset(pagination)
        if offset == 0 and not query.q:
            # Nothing is skipped on the unfiltered first page. A covering ID-only
            # subquery can make MySQL sort every active user via the rating index.
            # Search already needs username rows; retain its existing ID strategy.
            page_sql = 'FROM user u WHERE ' + where + ' ORDER BY u.id DESC LIMIT %s OFFSET %s'
        else:
            # Retain ID paging for a deep OFFSET: fetch public fields only for the
            # accepted page, not every skipped profile through a secondary index.
            page_sql = (
                'FROM user u JOIN (SELECT id FROM user WHERE '
                + where
                + ' ORDER BY id DESC LIMIT %s OFFSET %s) page ON page.id = u.id ORDER BY u.id DESC'
            )
        cursor.execute(
            'SELECT u.id, u.username, u.introduction, u.rating, u.type, u.deleted, u.admin_level, u.admin_version '
            + page_sql,
            [*params, query.per_page, offset],
        )
        users = cursor.fetchall()
        return {
            'users': [
                {
                    **user,
                    'type': 'root' if level_of(user) else 'normal',
                    'capabilities': capabilities(actor, user),
                }
                for user in users
            ],
            'pagination': pagination,
        }


def admin_update_user(actor_id, target_id, data):
    """Edit self or strictly lower-level profiles; preserve scores and history."""
    if not data or set(data) - {'username', 'introduction'}:
        raise ApiError('Only username and introduction may be updated')
    values = {}
    if 'username' in data:
        values['username'] = validate_username(data['username'], new=False)
    if 'introduction' in data:
        values['introduction'] = string(data['introduction'], 'Introduction')
    try:
        with transaction() as cursor:
            users = lock_users(cursor, [actor_id, target_id])
            actor, target = users[actor_id], users[target_id]
            require_manage_user(actor, target, allow_self=True)
            if target['deleted'] not in (0, 1):
                raise ApiError('Account state requires review', 409, 'invalid_account_state')
            if 'username' in values:
                # Existing short names can be retained, but newly chosen names use current rules.
                validate_username(values['username'], new=values['username'] != target['username'])
                if (
                    values['username'].casefold() == 'master'
                    and values['username'] != target['username']
                ):
                    raise ApiError('MASTER is reserved for explicit initialization')
                if (
                    level_of(target) == 5
                    and target['username'] == MASTER_NAME
                    and values['username'] != MASTER_NAME
                ):
                    raise ApiError('The MASTER account name cannot be changed')
            assignments = ', '.join(f'{field} = %s' for field in values)
            cursor.execute(
                'UPDATE user SET ' + assignments + ' WHERE id = %s',
                [*values.values(), target_id],
            )
            cursor.execute('DELETE FROM auth_session WHERE user_id = %s', (target_id,))
            audit(
                cursor,
                actor,
                target_id,
                'update-profile',
                {key: target[key] for key in values},
                values,
            )
    except IntegrityError as error:
        if error.args[0] == 1062:
            raise ApiError('Username already exists', 409, 'username_exists') from None
        raise
    return {'message': 'User profile updated successfully'}


def set_admin_level(actor_id, target_id, data):
    if set(data) != {'admin_level', 'expected_version', 'reason'}:
        raise ApiError('admin_level, expected_version and reason are required')
    level = validate_level(data['admin_level'])
    expected = data['expected_version']
    if type(expected) is not int or not 0 <= expected <= 2147483647:
        raise ApiError('expected_version must be a nonnegative INT')
    reason = string(data['reason'], 'Reason', minimum=1, maximum=500)
    with transaction() as cursor:
        users = lock_users(cursor, [actor_id, target_id])
        actor, target = users[actor_id], users[target_id]
        require_set_admin_level(actor, target)
        if level >= level_of(actor):
            raise ApiError('Assigned level must be lower than your own', 403, 'forbidden')
        if target['deleted'] != 0:
            raise ApiError(
                'Restore and review this account before changing its level',
                409,
                'invalid_account_state',
            )
        if target['admin_version'] != expected:
            raise ApiError(
                'User permissions changed; refresh before retrying', 409, 'stale_admin_version'
            )
        if target['username'].casefold() == 'master':
            raise ApiError('Existing MASTER accounts cannot be adopted or promoted')
        if level == level_of(target):
            raise ApiError('Administrator level is unchanged')
        version = next_version(target)
        cursor.execute(
            'UPDATE user SET admin_level = %s, type = %s, admin_version = %s WHERE id = %s',
            (level, 'root' if level else 'normal', version, target_id),
        )
        cursor.execute('DELETE FROM auth_session WHERE user_id = %s', (target_id,))
        audit(
            cursor,
            actor,
            target_id,
            'set-level',
            {'admin_level': level_of(target), 'admin_version': expected},
            {'admin_level': level, 'admin_version': version},
            reason=reason,
        )
    return {
        'message': 'Administrator level updated',
        'admin_level': level,
        'admin_version': version,
    }


def admin_user_action(actor_id, target_id, action, new_password=None):
    if actor_id == target_id:
        raise ApiError('Use your profile to modify your own account')
    if action not in ('delete', 'restore', 'reset-password'):
        raise ValueError('Unsupported admin action')
    encoded = hash_password(validate_password(new_password)) if action == 'reset-password' else None
    with transaction() as cursor:
        users = lock_users(cursor, [actor_id, target_id])
        actor, target = users[actor_id], users[target_id]
        if action == 'reset-password':
            require_reset_password(actor, target)
        else:
            require_manage_user(actor, target)
        if target['deleted'] not in (0, 1):
            raise ApiError('Account state requires review', 409, 'invalid_account_state')
        version = next_version(target)
        if action == 'reset-password':
            cursor.execute('UPDATE user SET pwhash = %s WHERE id = %s', (encoded, target_id))
        else:
            cursor.execute(
                'UPDATE user SET deleted = %s WHERE id = %s', (action == 'delete', target_id)
            )
        cursor.execute('UPDATE user SET admin_version = %s WHERE id = %s', (version, target_id))
        # Restoring an account must not revive any old session either.
        cursor.execute('DELETE FROM auth_session WHERE user_id = %s', (target_id,))
        before = {'admin_level': level_of(target), 'deleted': target['deleted']}
        after = {**before, 'deleted': action == 'delete'} if action != 'reset-password' else before
        audit(cursor, actor, target_id, action, before, after)
    return {'message': 'User updated successfully'}
