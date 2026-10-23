from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from wm_app.security.permissions import can_manage_dictionary
from wm_app.services import dictionary
from wm_app.services.errors import ApiError


def parse(content, **kwargs):
    return dictionary.parse_csv(
        content,
        max_bytes=kwargs.get('max_bytes', 512 * 1024),
        max_rows=kwargs.get('max_rows', 5000),
    )


def test_standard_csv_round_trip_with_quotes_commas_newlines_and_bom():
    words = [
        {'english': 'say "hi", please', 'chinese': '说“你好”\n第二行'},
        {'english': 'apple', 'chinese': '苹果'},
    ]
    content = '\ufeff' + dictionary.csv_content(words)
    assert parse(content) == [(word['english'], word['chinese']) for word in words]


@pytest.mark.parametrize(
    'content,line',
    [
        ('apple,苹果\nbad', 2),
        ('apple,苹果\nbanana,', 2),
        ('a,b,c', 1),
        ('"unclosed,b', 1),
        ('a' * 256 + ',b', 1),
    ],
)
def test_csv_line_errors_reject_entire_import(content, line):
    with pytest.raises(ApiError) as exc:
        parse(content)
    assert exc.value.code == 'invalid_csv'
    assert exc.value.details['errors'][0]['line'] == line


def test_csv_blank_lines_and_empty_file():
    assert parse('\n   \napple,苹果\n') == [('apple', '苹果')]
    with pytest.raises(ApiError):
        parse('\n')


def test_csv_limits_use_bytes_and_records():
    with pytest.raises(ApiError) as exc:
        parse('猫,狗', max_bytes=4)
    assert exc.value.status == 413
    with pytest.raises(ApiError) as exc:
        parse('a,b\nc,d', max_rows=1)
    assert exc.value.code == 'csv_too_many_rows'


def test_permissions_include_owner_admin_and_system_dictionary():
    normal, root = (
        {'id': 1, 'type': 'normal', 'admin_level': 0},
        {'id': 9, 'type': 'root', 'admin_level': 5},
    )
    assert can_manage_dictionary(normal, {'ownerid': 1})
    assert not can_manage_dictionary(normal, {'ownerid': 2})
    assert not can_manage_dictionary(normal, {'ownerid': None})
    assert can_manage_dictionary(root, {'ownerid': None})


def test_invalid_csv_does_not_open_transaction(app, monkeypatch):
    transaction = MagicMock()
    monkeypatch.setattr(dictionary, 'transaction', transaction)
    with app.app_context(), pytest.raises(ApiError):
        dictionary.import_csv(1, 1, 'apple,苹果\nbad')
    transaction.assert_not_called()


def test_foreign_dictionary_write_never_updates_database(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {'id': 1, 'type': 'normal', 'deleted': 0},
        {'id': 2, 'dictname': 'other', 'ownerid': 9},
    ]

    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr(dictionary, 'transaction', transaction)
    with pytest.raises(ApiError) as exc:
        dictionary.update_dictionary(1, 2, 'new')
    assert exc.value.status == 403
    assert not any(call.args[0].startswith('UPDATE') for call in cursor.execute.call_args_list)
