from __future__ import annotations

import random

from flip7.cards import CardKind, full_deck, number_card
from flip7.probability import (
    DeckCounts,
    _lookahead_ev_actions,
    _lookahead_ev_uncached,
    _LookaheadCache,
    clear_lookahead_cache,
    counts_from_cards,
    full_counts,
    lookahead_cache_info,
    lookahead_ev,
    one_step_ev,
    p_bust,
    p_flip7_this_hit,
    p_modifier,
    p_new_number,
    subtract_visible,
)
from flip7.scoring import score_line
from flip7.state import PlayerLine


def test_probabilities_partition_remaining() -> None:
    remaining = full_counts()
    held = [12, 11]
    parts = (
        p_bust(held, remaining),
        p_new_number(held, remaining),
        p_modifier(remaining),
    )
    assert abs(sum(parts) - 1.0) < 1e-12


def test_p_bust_matches_copy_counts() -> None:
    remaining = full_counts()
    assert p_bust([12], remaining) == 12 / remaining.total
    remaining.numbers[12] = 0
    assert p_bust([12], remaining) == 0.0


def test_one_step_ev_matches_enumeration() -> None:
    line = PlayerLine()
    line.apply(number_card(10))
    line.apply(number_card(5))
    visible = list(line.cards)
    remaining = subtract_visible(visible)
    held_keys = {(c.kind, c.number, c.plus, c.double) for c in visible}
    consumed = {k: 1 for k in held_keys}
    n = remaining.total
    expected = 0.0
    held = set(line.numbers)
    for card in full_deck():
        key = (card.kind, card.number, card.plus, card.double)
        if consumed.get(key, 0) > 0:
            consumed[key] -= 1
            continue
        if card.kind is CardKind.NUMBER and card.number in held:
            contrib = 0.0
        elif card.kind is CardKind.NUMBER:
            nums = [*line.numbers, card.number]
            contrib = score_line(nums, line.plus, line.has_x2, len(nums) >= 7)
        elif card.double:
            contrib = score_line(line.numbers, line.plus, True, False)
        else:
            contrib = score_line(line.numbers, line.plus + int(card.plus or 0), line.has_x2, False)
        expected += contrib / n
    got = one_step_ev(line.numbers, line.plus, line.has_x2, remaining)
    assert abs(got - expected) < 1e-9


def test_flip7_only_with_six_uniques() -> None:
    remaining = full_counts()
    assert p_flip7_this_hit([1, 2, 3], remaining) == 0.0
    six = [0, 1, 2, 3, 4, 5]
    assert p_flip7_this_hit(six, remaining) == p_new_number(six, remaining)


def test_counts_from_cards_roundtrip() -> None:
    deck = full_deck()
    assert counts_from_cards(deck).total == full_counts().total


def _slow_lookahead_ev(
    numbers: list[int],
    plus: int,
    has_x2: bool,
    remaining: DeckCounts,
) -> float:
    """Independent, unmemoized reference: full DeckCounts copies at each step.

    Deliberately does not share any code with ``lookahead_ev``'s delta-based
    memoization, so agreement between the two is real evidence of correctness
    rather than a shared bug. Only usable on small remaining decks (no memo).
    """
    n = remaining.total
    stay = float(score_line(numbers, plus, has_x2, len(numbers) >= 7))
    if len(numbers) >= 7 or n <= 0:
        return stay

    held = set(numbers)
    hit_value = 0.0
    for k, count in remaining.numbers.items():
        if count <= 0:
            continue
        p = count / n
        if k in held:
            continue  # bust, contributes 0
        new_remaining = DeckCounts(
            numbers={kk: (vv - 1 if kk == k else vv) for kk, vv in remaining.numbers.items()},
            plus=dict(remaining.plus),
            x2=remaining.x2,
        )
        new_numbers = [*numbers, k]
        if len(new_numbers) >= 7:
            contrib = float(score_line(new_numbers, plus, has_x2, True))
        else:
            contrib = _slow_lookahead_ev(new_numbers, plus, has_x2, new_remaining)
        hit_value += p * contrib
    for v, count in remaining.plus.items():
        if count <= 0:
            continue
        p = count / n
        new_remaining = DeckCounts(
            numbers=dict(remaining.numbers),
            plus={vv: (cc - 1 if vv == v else cc) for vv, cc in remaining.plus.items()},
            x2=remaining.x2,
        )
        hit_value += p * _slow_lookahead_ev(numbers, plus + v, has_x2, new_remaining)
    if remaining.x2 > 0:
        p = remaining.x2 / n
        new_remaining = DeckCounts(
            numbers=dict(remaining.numbers),
            plus=dict(remaining.plus),
            x2=remaining.x2 - 1,
        )
        hit_value += p * _slow_lookahead_ev(numbers, plus, True, new_remaining)
    return max(stay, hit_value)


def test_lookahead_ev_matches_slow_recursive_reference() -> None:
    remaining = DeckCounts(numbers={5: 1, 9: 2, 3: 1, 1: 1}, plus={2: 1, 4: 1}, x2=1)
    expected = _slow_lookahead_ev([10, 7], 0, False, remaining)
    got = lookahead_ev([10, 7], 0, False, remaining)
    assert abs(got - expected) < 1e-9


def test_lookahead_ev_matches_slow_reference_with_bust_risk() -> None:
    # Held numbers include 9, and 9 still has a copy in the remaining deck:
    # exercises the "duplicate draw busts" branch during recursion.
    remaining = DeckCounts(numbers={9: 1, 6: 1, 2: 2}, plus={6: 1}, x2=0)
    expected = _slow_lookahead_ev([9, 4], 0, True, remaining)
    got = lookahead_ev([9, 4], 0, True, remaining)
    assert abs(got - expected) < 1e-9


def test_lookahead_ev_at_least_one_step_ev() -> None:
    """DP is strictly more informed than one-card lookahead, so DP >= one-step."""
    cases: list[tuple[list[int], int, bool, DeckCounts]] = [
        ([10, 7], 0, False, DeckCounts(numbers={5: 1, 9: 2, 3: 1, 1: 1}, plus={2: 1, 4: 1}, x2=1)),
        ([1, 2, 3], 4, False, DeckCounts(numbers={4: 2, 5: 1, 6: 1}, plus={8: 1}, x2=1)),
        ([0, 1, 2, 3, 4], 0, True, DeckCounts(numbers={5: 1, 6: 1, 7: 1}, plus={}, x2=0)),
        ([], 0, False, DeckCounts(numbers={1: 1, 2: 1}, plus={2: 1}, x2=1)),
    ]
    for numbers, plus, has_x2, remaining in cases:
        dp = lookahead_ev(numbers, plus, has_x2, remaining)
        one_step = one_step_ev(numbers, plus, has_x2, remaining)
        assert dp >= one_step - 1e-9


def test_lookahead_ev_busted_is_zero() -> None:
    assert lookahead_ev([1, 2], 0, False, full_counts(), busted=True) == 0.0


def test_lookahead_ev_empty_remaining_is_stay_score() -> None:
    remaining = DeckCounts(numbers={}, plus={}, x2=0)
    assert lookahead_ev([3, 4], 5, True, remaining) == score_line([3, 4], 5, True, False)


def test_lookahead_ev_prefers_hitting_a_safe_low_bust_deck() -> None:
    # Only one card left and it cannot bust or hurt: hitting must be optimal.
    remaining = DeckCounts(numbers={11: 1}, plus={}, x2=0)
    stay = score_line([1, 2], 0, False, False)
    ev = lookahead_ev([1, 2], 0, False, remaining)
    assert ev > stay


def _random_state(rng: random.Random) -> tuple[list[int], int, bool, DeckCounts]:
    numbers = rng.sample(range(13), rng.randint(0, 6))
    remaining = full_counts()
    for k in numbers:
        remaining.numbers[k] = max(0, remaining.numbers[k] - 1)
    for k in list(remaining.numbers):
        if rng.random() < 0.3:
            remaining.numbers[k] = rng.randint(0, remaining.numbers[k])
    plus_cards = [v for v in remaining.plus if rng.random() < 0.3]
    for v in plus_cards:
        remaining.plus[v] = 0
    has_x2 = rng.random() < 0.3
    if has_x2:
        remaining.x2 = 0
    return numbers, sum(plus_cards), has_x2, remaining


def test_cached_lookahead_matches_uncached_on_random_states() -> None:
    clear_lookahead_cache()
    rng = random.Random(7)
    for _ in range(150):
        numbers, plus, has_x2, remaining = _random_state(rng)
        expected = _lookahead_ev_uncached(numbers, plus, has_x2, remaining)
        assert lookahead_ev(numbers, plus, has_x2, remaining) == expected
        assert lookahead_ev(numbers, plus, has_x2, remaining) == expected


def test_lookahead_cache_hits_clear_and_snapshot() -> None:
    clear_lookahead_cache()
    remaining = full_counts()
    first = lookahead_ev([5, 9], 0, False, remaining)
    assert lookahead_cache_info()["misses"] == 1
    remaining.numbers[12] = 0  # mutating the caller's deck must not poison the cache
    assert lookahead_ev([5, 9], 0, False, full_counts()) == first
    assert lookahead_cache_info()["hits"] == 1
    clear_lookahead_cache()
    assert lookahead_cache_info()["size"] == 0


def test_lookahead_cache_busted_and_flip7_shortcuts() -> None:
    clear_lookahead_cache()
    assert lookahead_ev([1], 0, False, full_counts(), busted=True) == 0.0
    assert lookahead_ev([0, 1, 2, 3, 4, 5, 6], 0, False, full_counts()) == float(
        score_line([0, 1, 2, 3, 4, 5, 6], 0, False, True)
    )


def test_lookahead_cache_evicts_least_recently_used() -> None:
    cache = _LookaheadCache(maxsize=2)
    keys = [(frozenset({i}), 0, False, ()) for i in range(3)]
    cache.put(keys[0], 1.0)
    cache.put(keys[1], 2.0)
    assert cache.get(keys[0]) == 1.0  # refresh key 0
    cache.put(keys[2], 3.0)  # evicts key 1
    assert len(cache) == 2
    assert cache.get(keys[1]) is None
    assert cache.get(keys[0]) == 1.0


def test_deckcounts_total_includes_action_cards() -> None:
    counts = counts_from_cards(full_deck(include_action_cards=True))
    assert (counts.freeze, counts.flip_three, counts.second_chance) == (3, 3, 3)
    assert counts.total == 94
    assert counts_from_cards(full_deck()).total == 85


def test_action_dp_matches_phase1_dp_when_no_action_cards() -> None:
    rng = random.Random(11)
    for _ in range(15):
        numbers, plus, has_x2, remaining = _random_state(rng)
        assert (
            abs(
                _lookahead_ev_actions(numbers, plus, has_x2, remaining)
                - _lookahead_ev_uncached(numbers, plus, has_x2, remaining)
            )
            < 1e-9
        )


def test_second_chance_flips_a_stay_into_a_hit() -> None:
    # {12, 11} vs a deck of mostly 12s and 11s: hitting busts ~always, so stay.
    remaining = DeckCounts(numbers={12: 11, 11: 10, 1: 1}, plus={}, x2=0, second_chance=1)
    stay = score_line([12, 11], 0, False, False)
    assert lookahead_ev([12, 11], 0, False, remaining) <= stay
    # Holding a Second Chance, the first duplicate is forgiven: hit becomes right.
    assert lookahead_ev([12, 11], 0, False, remaining, second_chances=1) > stay


def test_freeze_on_self_banks_and_flip_three_on_self_forces_draws() -> None:
    held = [5, 6]
    base = score_line(held, 0, False, False)
    # Only a Freeze left, no one else active: drawing it banks the current line.
    freeze_only = DeckCounts(numbers={}, plus={}, x2=0, freeze=1)
    assert lookahead_ev(held, 0, False, freeze_only, others_active=False) == base
    # Only a Flip Three plus a single safe number: forced draws take the number.
    f3 = DeckCounts(numbers={7: 1}, plus={}, x2=0, flip_three=1)
    ev = lookahead_ev(held, 0, False, f3, others_active=False)
    assert ev >= base


def test_neutral_action_cards_leave_a_phase1_decision_unchanged() -> None:
    plain = DeckCounts(numbers={3: 3, 8: 8}, plus={}, x2=0)
    with_actions = DeckCounts(numbers={3: 3, 8: 8}, plus={}, x2=0, freeze=3, flip_three=3)
    assert (
        abs(lookahead_ev([3], 0, False, plain) - lookahead_ev([3], 0, False, with_actions)) < 1e-9
    )
