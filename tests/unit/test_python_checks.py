"""Exercise the installed, pinned checker and Make entry points, not mocked tools."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mako.template import Template

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ['app.py', 'wm_app', 'migrations', 'scripts', 'tests']


def ruff(*args, source=None):
    return subprocess.run(
        [sys.executable, '-m', 'ruff', *args, '--config', str(ROOT / 'ruff.toml'), '--no-cache'],
        input=source,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def lint_stdin(filename, source):
    result = ruff(
        'check',
        '--no-fix',
        '--output-format',
        'json',
        '--stdin-filename',
        filename,
        '-',
        source=source,
    )
    assert result.returncode in (0, 1), result.stderr
    return {error['code'] for error in json.loads(result.stdout)}


def test_checker_discovers_application_migrations_scripts_and_all_tests():
    result = ruff('check', '--show-files', *SOURCES)
    assert result.returncode == 0, result.stderr
    discovered = {Path(line).resolve() for line in result.stdout.splitlines()}
    expected = {ROOT / 'app.py'} | {
        path for name in SOURCES[1:] for path in (ROOT / name).rglob('*.py')
    }
    assert discovered == expected


@pytest.mark.parametrize(
    'filename',
    [
        'app.py',
        'wm_app/services/new_service.py',
        'migrations/env.py',
        'migrations/versions/0008_new_revision.py',
        'scripts/new_script.py',
        'tests/unit/new_test.py',
        'tests/integration/new_test.py',
        'tests/browser/new_test.py',
    ],
)
def test_all_source_groups_reject_undefined_names_mutable_defaults_and_unsorted_imports(filename):
    source = 'import sys\nimport os\n\n\ndef broken(items=[]):\n    return unknown, os.name, sys.version\n'
    assert {'F821', 'B006', 'I001'} <= lint_stdin(filename, source)


def test_historical_migrations_only_exempt_import_sorting():
    source = 'from alembic import op\nimport sqlalchemy as sa\n\ndef broken(items=[]):\n    return missing, op, sa\n'
    for revision in range(1, 8):
        codes = lint_stdin(f'migrations/versions/{revision:04}_historical.py', source)
        assert {'F821', 'B006'} <= codes
        assert 'I001' not in codes
    assert 'I001' in lint_stdin('migrations/versions/0008_future.py', source)


def test_only_the_qualified_immutable_query_constructor_is_exempt():
    template = (
        'from {module} import ListQuery\n\n\ndef read(query=ListQuery()):\n    return query\n'
    )
    assert 'B008' not in lint_stdin(
        'wm_app/services/example.py', template.format(module='wm_app.services.pagination')
    )
    assert 'B008' in lint_stdin(
        'wm_app/services/example.py', template.format(module='some_other_module')
    )


@pytest.mark.parametrize(
    'source,expected_message',
    [('def example():\n    return missing\n', 'F821'), ('answer=42\n', 'Would reformat')],
)
def test_make_static_check_fails_without_rewriting_source(tmp_path, source, expected_message):
    path = tmp_path / 'example.py'
    path.write_text(source)
    result = subprocess.run(
        ['make', 'check-python-static', f'PYTHON={sys.executable}', f'PYTHON_SOURCES={path}'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert expected_message in result.stdout + result.stderr
    assert path.read_text() == source


def test_formatter_is_explicit_ast_preserving_and_idempotent(tmp_path):
    path = tmp_path / 'example.py'
    source = (
        "QUERY='''SELECT id, name\n    FROM example WHERE name = %s'''\nvalues={ 'a':1,'b':2 }\n"
    )
    path.write_text(source)
    result = ruff('format', '--check', str(path))
    assert result.returncode == 1 and path.read_text() == source
    assert ruff('format', str(path)).returncode == 0
    formatted = path.read_text()
    assert formatted != source
    assert ast.dump(ast.parse(formatted)) == ast.dump(ast.parse(source))
    assert ruff('format', str(path)).returncode == 0
    assert path.read_text() == formatted
    assert ruff('format', '--check', str(path)).returncode == 0


def test_mismatched_tool_version_is_rejected():
    result = ruff('check', '--config', 'required-version = "==0.0.0"', '-', source='answer = 42\n')
    assert result.returncode == 2
    assert 'required version' in result.stderr.lower()


def test_migration_template_renders_checkable_python_without_running_ddl(tmp_path):
    source = Template(filename=str(ROOT / 'migrations/script.py.mako')).render(
        message='Synthetic template test, never an applied migration.',
        up_revision='test_only',
        down_revision='0007_game_settlements',
        branch_labels=None,
        depends_on=None,
        upgrades="op.create_table('example', sa.Column('id', sa.Integer, primary_key=True))",
        downgrades="op.drop_table('example')",
    )
    path = tmp_path / 'template_example.py'
    path.write_text(source)
    assert ruff('format', '--check', str(path)).returncode == 0
    result = ruff('check', '--no-fix', str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    ast.parse(source)  # Do not import/execute the rendered migration.
