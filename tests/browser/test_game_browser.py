"""Independent SQL evidence for the real Chromium game scenarios."""

import pytest

from tests.integration.test_game_mysql import query

pytestmark = pytest.mark.mysql


def test_real_browser_game_transports(mysql_app, run_browser):
    run_browser('game.spec.ts')
    games = query(
        mysql_app, 'SELECT id, status, answer_count, version FROM game WHERE id > 1 ORDER BY id'
    )
    assert len(games) == 2 and all(row['status'] == 1 for row in games)
    assert [row['answer_count'] for row in games] == [3, 1]
    assert [row['version'] for row in games] == [
        5,
        4,
    ]  # join/start + answers/end; replay adds nothing
    assert len(query(mysql_app, 'SELECT * FROM game_settlement')) == 2
    assert len(query(mysql_app, 'SELECT * FROM game_answer')) == 4
    assert len(query(mysql_app, 'SELECT * FROM game_rating')) == 3
    assert len(query(mysql_app, "SELECT * FROM game_request WHERE action = 'answer'")) == 4
    rows = query(
        mysql_app,
        'SELECT r.rating_after, u.rating, u.rating_ledger_id, r.id FROM user u JOIN game_rating r ON r.id = u.rating_ledger_id',
    )
    assert len(rows) == 2 and all(row['rating_after'] == row['rating'] for row in rows)
