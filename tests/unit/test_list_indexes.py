"""Migration graph and connection-local metadata-lock limits, without running DDL."""

from contextlib import nullcontext
from importlib import import_module
from unittest.mock import MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

migration = import_module('migrations.versions.0008_list_indexes')


def test_list_index_revision_remains_in_the_single_current_chain():
    script = ScriptDirectory.from_config(Config('alembic.ini'))
    assert script.get_heads() == ['0012_manual_rating']
    assert script.get_revision('0008_list_indexes').down_revision == '0007_game_settlements'
    assert len(list(script.walk_revisions())) == 12
    assert len(migration.INDEXES) == 2


@pytest.mark.parametrize('previous', [1, 30, 300])
@pytest.mark.parametrize('fail', [False, True])
def test_metadata_wait_is_capped_without_relaxing_stricter_limits_and_is_restored(
    monkeypatch, previous, fail
):
    connection = MagicMock(invalidated=False)
    connection.execute.return_value.scalar_one.return_value = previous
    monkeypatch.setattr(migration.op, 'get_bind', lambda: connection)
    with (
        pytest.raises(RuntimeError, match='body failed') if fail else nullcontext(),
        migration._metadata_lock_limit(),
    ):
        assert connection.execute.call_args.args[1] == {'seconds': min(previous, 30)}
        if fail:
            raise RuntimeError('body failed')
    assert connection.execute.call_count == 3
    assert connection.execute.call_args.args[1] == {'seconds': previous}
    assert all('SESSION' in str(call.args[0]) for call in connection.execute.call_args_list[1:])


def test_lost_migration_connection_is_not_reconnected_to_reset_a_session(monkeypatch):
    connection = MagicMock(invalidated=False)
    connection.execute.return_value.scalar_one.return_value = 100
    getter = MagicMock(return_value=connection)
    monkeypatch.setattr(migration.op, 'get_bind', getter)
    with pytest.raises(RuntimeError, match='lost'), migration._metadata_lock_limit():
        connection.invalidated = True
        raise RuntimeError('lost')
    getter.assert_called_once()
    assert connection.execute.call_count == 2
