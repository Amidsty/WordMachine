from uuid import uuid4

import pytest

from wm_app.services.admin_policy import capabilities
from wm_app.services.errors import ApiError
from wm_app.services.rating_adjustments import _permit, parameters


def valid():
    return {
        'request_id': str(uuid4()),
        'expected_rating': 1500,
        'expected_event_id': None,
        'new_rating': -100,
        'reason': '  approved  ',
        'current_password': ' Keep spaces! ',
    }


@pytest.mark.parametrize(
    'field,value',
    [
        ('new_rating', True),
        ('new_rating', '1700'),
        ('new_rating', 1.25),
        ('new_rating', None),
        ('new_rating', 2147483648),
        ('new_rating', -2147483649),
        ('expected_rating', False),
        ('expected_rating', '1500'),
        ('expected_rating', None),
        ('expected_event_id', 1),
        ('expected_event_id', True),
        ('expected_event_id', '0'),
        ('expected_event_id', '-1'),
        ('expected_event_id', '01'),
        ('expected_event_id', '1e3'),
        ('expected_event_id', '１'),
        ('expected_event_id', '9223372036854775808'),
        ('reason', ''),
        ('reason', '   '),
        ('reason', None),
        ('reason', 'x' * 501),
        ('reason', '\ud800'),
        ('reason', '\0'),
        ('current_password', ''),
        ('current_password', None),
        ('current_password', 'x' * 4097),
        ('request_id', None),
        ('request_id', 'not-a-uuid'),
        ('request_id', True),
    ],
)
def test_strict_review_parameters(field, value):
    with pytest.raises(ApiError):
        parameters({**valid(), field: value})


def test_parameters_preserve_password_and_omit_secrets_from_intent():
    data = valid()
    intent, password = parameters(data)
    assert password == data['current_password'] and 'current_password' not in intent
    assert intent['reason'] == 'approved'
    for field in data:
        with pytest.raises(ApiError):
            parameters({key: value for key, value in data.items() if key != field})
    with pytest.raises(ApiError):
        parameters({**data, 'actor_id': 5})
    assert (
        parameters({**data, 'expected_event_id': '9223372036854775807'})[0]['expected_event_id']
        == '9223372036854775807'
    )


@pytest.mark.parametrize('actor_level', range(6))
@pytest.mark.parametrize('target_level', range(6))
def test_manual_scope_does_not_compare_balances(actor_level, target_level):
    actor = {'id': 1, 'admin_level': actor_level, 'deleted': 0, 'rating': -99999}
    target = {'id': 2, 'admin_level': target_level, 'deleted': 0, 'rating': 99999}
    allowed = actor_level >= 4 and target_level < actor_level
    assert capabilities(actor, target)['can_adjust_rating'] == allowed
    if allowed:
        _permit(actor, target)
    else:
        with pytest.raises(ApiError):
            _permit(actor, target)


@pytest.mark.parametrize('level', range(6))
def test_self_adjustment_scope(level):
    user = {'id': 1, 'admin_level': level, 'deleted': 0}
    assert capabilities(user, user)['can_adjust_rating'] == (level >= 4)
    if level >= 4:
        _permit(user, user)
    else:
        with pytest.raises(ApiError):
            _permit(user, user)
