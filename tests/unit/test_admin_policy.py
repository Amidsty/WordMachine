import pytest

from wm_app.security.permissions import require_manage_user, require_root
from wm_app.services.admin_policy import capabilities, generate_master_password, master_password
from wm_app.services.errors import ApiError


@pytest.mark.parametrize('actor_level', range(6))
@pytest.mark.parametrize('target_level', range(6))
def test_complete_hierarchy_matrix(actor_level, target_level):
    actor = {'id': 1, 'deleted': 0, 'admin_level': actor_level, 'rating': -1000}
    target = {'id': 2, 'deleted': 0, 'admin_level': target_level, 'rating': 9999}
    allowed = actor_level > target_level
    if allowed:
        require_manage_user(actor, target)
    else:
        with pytest.raises(ApiError):
            require_manage_user(actor, target)
    flags = capabilities(actor, target)
    assert flags['can_edit_profile'] is allowed
    assert flags['can_set_level'] is allowed
    assert flags['meets_rating_threshold'] == (allowed and actor_level >= 4)
    assert flags['can_adjust_rating'] == (allowed and actor_level >= 4)


@pytest.mark.parametrize('level', [None, True, '5', -1, 6])
def test_old_type_or_invalid_level_cannot_grant_administrative_access(level):
    with pytest.raises(ApiError):
        require_root({'type': 'root', 'admin_level': level})


@pytest.mark.parametrize(
    'password',
    ['short', 'abcdefghijklmnop', 'Abcdefghijk12345', 'ABCDEF123456789!', 'abcdef123456789!'],
)
def test_master_password_requires_length_and_each_character_group(password):
    with pytest.raises(ApiError):
        master_password(password)


def test_generated_master_password_is_valid_and_no_whitespace_is_silently_removed():
    value = generate_master_password()
    assert len(value) == 24 and master_password(value) == value
    assert master_password(' ' + value + ' ') == ' ' + value + ' '
