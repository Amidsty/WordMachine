import hashlib
import hmac
import re
from functools import lru_cache

from werkzeug.security import check_password_hash, generate_password_hash

SCRYPT_METHOD = 'scrypt:32768:8:1'
LEGACY_HASH = re.compile(r'^[0-9a-f]{64}$')


def hash_password(password):
    return generate_password_hash(password, method=SCRYPT_METHOD)


def is_legacy_hash(stored):
    return isinstance(stored, str) and LEGACY_HASH.fullmatch(stored) is not None


def verify_password(stored, password):
    if not isinstance(stored, str) or not isinstance(password, str):
        return False
    if is_legacy_hash(stored):
        # Compatibility with the old registration/login normalization only.
        candidate = hashlib.sha256(password.strip().encode('utf-8')).hexdigest()
        return hmac.compare_digest(candidate, stored)
    if not stored.startswith(SCRYPT_METHOD + '$'):
        return False
    try:
        return check_password_hash(stored, password)
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def dummy_hash():
    return hash_password('dummy-password-not-an-account')
