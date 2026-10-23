from dataclasses import FrozenInstanceError, asdict

import pytest

from tests.performance.compare import compare
from tests.performance.dataset import DISTRIBUTIONS, SIZES, Distribution, label, seed
from tests.performance.test_lists import cases


def test_standard_distribution_keeps_original_fixture_values():
    profile = DISTRIBUTIONS['standard']
    counts = SIZES['smoke']
    for i in range(counts['words']):
        expected_dict = 10 if i < 500 else 11 + (i - 500) % 39
        assert profile.dictionary_id(i, counts) == expected_dict
        assert profile.deleted(i) == (None if i % 17 == 0 else int(i % 10 == 0))
        old_label = (
            f'entry-{i}' + (' needle' if i % 97 == 0 else '') + (' %_!' if i % 193 == 0 else '')
        )
        assert profile.word_text(i) == (old_label, f'词{i}')
    with pytest.raises(FrozenInstanceError):
        profile.hot_percent = 99


@pytest.mark.parametrize('name', DISTRIBUTIONS)
def test_distribution_is_deterministic_bounded_and_has_exact_hot_quota(name):
    counts = SIZES['smoke']
    profile = DISTRIBUTIONS[name]
    ids = [profile.dictionary_id(i, counts) for i in range(counts['words'])]
    assert ids.count(10) == counts['words'] * profile.hot_percent // 100
    assert all(10 <= value < 10 + counts['dictionaries'] for value in ids)
    assert ids == [profile.dictionary_id(i, counts) for i in range(counts['words'])]
    assert set(profile.deleted(i) for i in range(counts['words'])) == {None, 0, 1}
    assert Distribution(**asdict(profile)) == profile
    for i in range(counts['words']):
        assert all(value is None or 1 <= len(value) <= 255 for value in profile.word_text(i))
    if profile.spread:
        hot = [i for i, value in enumerate(ids) if value == 10]
        assert max(hot) - min(hot) > counts['words'] // 2


def test_wide_fixture_includes_nullable_text_and_frequent_literal_search_matches():
    profile = DISTRIBUTIONS['wide']
    assert profile.word_text(0) == (None, None)
    assert all(len(value) == 255 for value in profile.word_text(2))
    assert 'needle' in profile.word_text(2)[0]
    assert 'needle' not in profile.word_text(1)[0]
    assert '%_!' in profile.word_text(193)[0]
    assert label('person', 2, profile.needle_every) == 'person-2 needle'
    assert profile.word_text(37)[0] is None
    assert profile.word_text(41)[1] is None


def test_deleted_fixture_keeps_both_inactive_and_unknown_states():
    profile = DISTRIBUTIONS['deleted']
    assert profile.deleted(0) is None
    assert profile.deleted(1) == 1
    assert profile.deleted(20) == 0
    assert profile.deleted(140) is None


@pytest.mark.parametrize('size,distribution', [('unknown', 'standard'), ('smoke', 'unknown')])
def test_unknown_fixture_options_fail_before_a_connection_is_opened(size, distribution):
    with pytest.raises(KeyError):
        seed(None, size, distribution)


def test_expanded_workloads_keep_original_cases_and_have_unique_names():
    names = [name for name, _ in cases()]
    assert len(names) == len(set(names)) == 34
    assert names[0] == 'dictionaries.first'
    assert names[21] == 'lobby.active_member'
    assert {
        'small_words.contains',
        'words.chinese',
        'words.contains_last',
        'users.second',
        'users.filtered',
        'users.literal',
        'users.all',
    } <= set(names)


@pytest.mark.parametrize(
    'field,value', [('distribution', {'name': 'wide'}), ('dataset_sha256', 'changed')]
)
def test_comparison_rejects_generator_or_distribution_changes_even_before_results(field, value):
    # No environment/cases needed: method differences must be rejected first.
    before = {
        'format_version': 1,
        'scope': '',
        'profile': '',
        'generated_rows': {},
        'warmups_per_case': 1,
        'measured_runs_per_case': 3,
    }
    for left, right in (
        (before, {**before, field: value}),
        ({**before, field: value}, {**before, field: None}),
        (before, {**before, field: None}),
        ({**before, field: None}, before),
    ):
        with pytest.raises(ValueError, match=field):
            compare(left, right)
