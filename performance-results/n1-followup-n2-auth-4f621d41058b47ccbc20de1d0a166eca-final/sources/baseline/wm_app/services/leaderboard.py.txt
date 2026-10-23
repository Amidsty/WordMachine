"""Public top-100 leaderboard. Preserve rating order and ID tie breaking."""

from ..db import reading
from .errors import ApiError
from .pagination import ListQuery, page_offset


def list_leaders(query=ListQuery()):
    if query.q:
        raise ApiError('Leaderboard search is not supported')
    with reading() as cursor:
        # The public universe is at most 100 rows. Obtain its exact size and page
        # from one ordered, bounded read instead of counting every active account.
        cursor.execute(
            'SELECT id, username, introduction, rating FROM user WHERE deleted = 0 '
            'ORDER BY rating DESC, id ASC LIMIT 100'
        )
        leaders = cursor.fetchall()
    pagination = query.metadata(len(leaders))
    offset = page_offset(pagination)
    users = leaders[offset : offset + query.per_page]
    return {
        'users': [{**user, 'rank': offset + index + 1} for index, user in enumerate(users)],
        'pagination': pagination,
    }
