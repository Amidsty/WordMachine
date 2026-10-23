"""Compare compatible local reports: python -m tests.performance.compare BEFORE AFTER."""

import argparse
import json
from pathlib import Path


def compare(before, after, *, expected_revisions=None):
    if before.get('format_version') != 1 or after.get('format_version') != 1:
        raise ValueError('Unsupported report format')
    for field in (
        'scope',
        'profile',
        'generated_rows',
        'warmups_per_case',
        'measured_runs_per_case',
    ):
        if before[field] != after[field]:
            raise ValueError(f'Incompatible benchmark method/dataset: {field}')
    # Legacy reports lacked these fields. Never compare an unspecified distribution
    # with a specified one, or silently allow generator changes between samples.
    for field in ('distribution', 'dataset_sha256'):
        if (field in before) != (field in after) or before.get(field) != after.get(field):
            raise ValueError(f'Incompatible benchmark method/dataset: {field}')
    # Application source hashes should change; the measured environment must not.
    before_env = {
        key: value for key, value in before['environment'].items() if key != 'source_sha256'
    }
    after_env = {
        key: value for key, value in after['environment'].items() if key != 'source_sha256'
    }
    if expected_revisions is not None:
        if len(expected_revisions) != 2 or any(
            environment.get('schema_revision') != [revision]
            for environment, revision in zip(
                (before_env, after_env), expected_revisions, strict=True
            )
        ):
            raise ValueError('Schema revisions do not match the explicitly reviewed pair')
        before_env.pop('schema_revision')
        after_env.pop('schema_revision')
    if before_env != after_env:
        raise ValueError('Incompatible benchmark environment/row counts')
    if before['cases'].keys() != after['cases'].keys():
        raise ValueError('Benchmark cases differ')
    rows = []
    for name, old in before['cases'].items():
        new = after['cases'][name]
        for field in ('result_sha256', 'pagination', 'item_ids', 'active_game_id'):
            if old[field] != new[field]:
                raise ValueError(f'Result changed: {name} / {field}')
        rows.append(
            (
                name,
                old['service_ms']['median'],
                new['service_ms']['median'],
                len(old['statements']),
                len(new['statements']),
            )
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument(
        '--revisions',
        nargs=2,
        metavar=('BEFORE', 'AFTER'),
        help='Explicitly reviewed revision pair; all other environment checks remain strict',
    )
    args = parser.parse_args()
    try:
        rows = compare(
            json.loads(args.before.read_text()),
            json.loads(args.after.read_text()),
            expected_revisions=args.revisions,
        )
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print('Matching result digests; synthetic medians only, not a production SLA.')
    print(f'{"case":30} {"before ms":>10} {"after ms":>10} {"SQL count":>12}')
    for name, before, after, old_queries, new_queries in rows:
        print(f'{name:30} {before:10.2f} {after:10.2f} {old_queries:5} -> {new_queries}')


if __name__ == '__main__':
    main()
