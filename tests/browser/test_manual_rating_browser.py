"""Real Chromium + isolated MySQL; source/event/audit verified independently."""

import json

import pytest

from tests.integration.test_game_mysql import query

pytestmark = pytest.mark.mysql


def test_manual_rating_review_and_lost_confirmation(mysql_app, run_browser):
    before = query(
        mysql_app, 'SELECT id, ratinghistory, gamehistory, rating_ledger_id FROM user ORDER BY id'
    )
    run_browser('rating.spec.ts')
    assert (
        query(
            mysql_app,
            'SELECT id, ratinghistory, gamehistory, rating_ledger_id FROM user ORDER BY id',
        )
        == before
    )
    assert query(mysql_app, 'SELECT rating FROM user ORDER BY id') == [
        {'rating': 1800},
        {'rating': 1500},
        {'rating': 1500},
    ]
    events = query(mysql_app, 'SELECT * FROM rating_event ORDER BY sequence')
    sources = query(mysql_app, 'SELECT * FROM manual_rating ORDER BY id')
    receipts = query(mysql_app, 'SELECT * FROM rating_adjustment_request ORDER BY created_at')
    audits = query(
        mysql_app, "SELECT * FROM admin_audit WHERE action = 'adjust-rating' ORDER BY id"
    )
    assert len(events) == len(sources) == len(receipts) == len(audits) == 2
    assert [event['delta'] for event in events] == [200, 100]
    assert events[1]['previous_id'] == events[0]['id']
    assert all(event['kind'] == 'manual' and event['game_rating_id'] is None for event in events)
    for event, source, receipt in zip(events, sources, receipts, strict=True):
        assert event['manual_rating_id'] == source['id']
        assert source['actor_id'] == 3 and source['actor_level'] == 5 and source['user_id'] == 1
        assert json.loads(receipt['response'])['rating_event_id'] == str(event['id'])
    assert not query(mysql_app, 'SELECT * FROM game_rating')
    assert not query(mysql_app, 'SELECT * FROM auth_session')
    assert mysql_app.test_cli_runner().invoke(args=['audit-legacy']).exit_code == 0
