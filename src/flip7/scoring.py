FLIP7_BONUS = 15
TARGET_SCORE = 200


def score_line(
    numbers: list[int] | tuple[int, ...],
    plus: int,
    has_x2: bool,
    flip7: bool,
) -> int:
    """Banked score for a non-busted line.

    Order: sum numbers, optional x2 on that sum, plus modifiers, then Flip 7 bonus.
    """
    total = sum(numbers)
    if has_x2:
        total *= 2
    total += plus
    if flip7:
        total += FLIP7_BONUS
    return total
