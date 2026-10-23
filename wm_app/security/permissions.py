from ..services.errors import ApiError

MAX_ADMIN_LEVEL = 5
SYSTEM_DICTIONARY_MIN_LEVEL = 3
RATING_EDIT_MIN_LEVEL = 4
ADMIN_LEVEL_EDIT_MIN_LEVEL = 4
GAME_END_MIN_LEVEL = 2


def admin_level(user):
    value = user.get('admin_level')
    return value if type(value) is int and 0 <= value <= MAX_ADMIN_LEVEL else 0


def can_end_game(user, owner_id):
    return user.get('id') == owner_id or admin_level(user) >= GAME_END_MIN_LEVEL


def require_root(user):
    if admin_level(user) == 0:
        raise ApiError('Administrator permission required', 403, 'forbidden')


def require_manage_user(actor, target, *, allow_self=False):
    if actor['deleted'] != 0:
        raise ApiError('Authentication required', 401, 'unauthenticated')
    require_root(actor)
    if type(target.get('admin_level')) is not int or not 0 <= target['admin_level'] <= 5:
        raise ApiError('User permissions require review', 409, 'invalid_admin_level')
    if actor['id'] == target['id']:
        if allow_self:
            return
    elif admin_level(target) < admin_level(actor):
        return
    raise ApiError('Only lower-level users may be managed', 403, 'forbidden')


def require_reset_password(actor, target):
    require_manage_user(actor, target)
    if admin_level(actor) != MAX_ADMIN_LEVEL:
        raise ApiError('Resetting another user password requires level 5', 403, 'forbidden')


def require_set_admin_level(actor, target):
    require_manage_user(actor, target)
    if admin_level(actor) < ADMIN_LEVEL_EDIT_MIN_LEVEL:
        raise ApiError('Changing administrator levels requires level 4 or higher', 403, 'forbidden')


def can_manage_dictionary(user, dictionary):
    owner = dictionary.get('ownerid')
    if owner is None:
        return admin_level(user) >= SYSTEM_DICTIONARY_MIN_LEVEL
    return owner == user['id'] or admin_level(user) == MAX_ADMIN_LEVEL


def require_dictionary_owner(user, dictionary):
    if not can_manage_dictionary(user, dictionary):
        raise ApiError(
            'Personal dictionaries require their owner or level 5; system dictionaries require level 3 or higher',
            403,
            'forbidden',
        )


def lock_users(cursor, ids):
    """Lock user rows in ID order so admin operations cannot deadlock each other."""
    users = {}
    for uid in sorted(set(ids)):
        cursor.execute('SELECT * FROM user WHERE id = %s FOR UPDATE', (uid,))
        user = cursor.fetchone()
        if user is None:
            raise ApiError('User not found', 404, 'not_found')
        users[uid] = user
    return users


def lock_actor(cursor, uid):
    user = lock_users(cursor, [uid])[uid]
    if user['deleted'] != 0:
        raise ApiError('Authentication required', 401, 'unauthenticated')
    return user
