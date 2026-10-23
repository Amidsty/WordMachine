from .errors import ApiError


def string(value, name, *, minimum=0, maximum=255, strip=True):
    if not isinstance(value, str):
        raise ApiError(f'{name} must be a string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise ApiError(f'{name} contains invalid Unicode') from None
    if strip:
        value = value.strip()
    if not minimum <= len(value) <= maximum or '\x00' in value:
        raise ApiError(f'{name} must contain {minimum}–{maximum} characters')
    return value


def username(value, *, new=True):
    value = string(value, 'Username', minimum=3 if new else 1)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ApiError('Username contains control characters')
    return value


def password(value, *, new=True):
    # New passwords are never silently stripped, unlike the old SHA-256 path.
    return string(
        value, 'Password', minimum=6 if new else 1, maximum=128 if new else 4096, strip=False
    )
