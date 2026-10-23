"""Current admission policy for Rated games, not a scoring or historical rewrite."""

from .errors import ApiError, GameError

MIN_RATING, MAX_RATING = -2147483648, 2147483647


def bounds(lower, upper):
    if (
        type(lower) is not int
        or type(upper) is not int
        or not MIN_RATING <= lower <= upper <= MAX_RATING
    ):
        raise ApiError(
            'Rated bounds must be signed INTs with lower <= upper', 400, 'invalid_rated_bounds'
        )
    return lower, upper


def stored(dictionary):
    try:
        return bounds(dictionary.get('rated_min'), dictionary.get('rated_max'))
    except ApiError:
        raise GameError(
            'Rated dictionary bounds require review', 409, 'invalid_rated_bounds'
        ) from None


def can_create(actor, dictionary):
    lower, upper = stored(dictionary)
    return (
        dictionary['ownerid'] is None
        and type(actor.get('rating')) is int
        and lower <= actor['rating'] <= upper
    )


def require_eligible(cursor, dict_id, users):
    """Caller holds game and ALL affected user locks before this dictionary lock.

    FOR SHARE is a current read, independent of an older question/read snapshot.
    Dictionary writers lock actor -> dictionary and never lock games, so there is
    no dictionary -> user/game inversion. Hold admission policy through commit.
    """
    cursor.execute(
        'SELECT id, ownerid, deleted, rated_min, rated_max, config_version FROM dict WHERE id=%s FOR SHARE',
        (dict_id,),
    )
    dictionary = cursor.fetchone()
    if not dictionary or dictionary['deleted'] != 0 or dictionary['ownerid'] is not None:
        raise GameError(
            'Rated games require an active system dictionary',
            409,
            'rated_system_dictionary_required',
        )
    lower, upper = stored(dictionary)
    if any(
        type(user.get('rating')) is not int or not lower <= user['rating'] <= upper
        for user in users.values()
    ):
        raise GameError(
            f'All participants must have Rating within [{lower}, {upper}]',
            409,
            'rated_rating_out_of_range',
        )
