"""The Diverge lenses and the yield-weighted choice between them (P2-28)."""

from __future__ import annotations

import random

from aura.config import settings

# The first five are the card's lenses and the first run's choice; the rest only enter
# through exploration once yield data exists. These go into prompts: no em dashes.
LENSES: dict[str, str] = {
    "remove_constraint": "Remove the main constraint of the problem and ask what becomes possible.",
    "steal_distant": "Steal an approach from a distant field that has nothing to do with this problem.",
    "invert": "Invert the problem: do the opposite of the obvious move.",
    "worst_idea": "Give the worst idea that might secretly work.",
    "ten_x_cheaper": "Give the 10x cheaper version: what is left when almost everything is cut?",
    "other_audience": "Design it for a completely different audience than the obvious one.",
    "combine_unrelated": "Combine the problem with two unrelated things and keep what survives.",
    "make_it_a_game": "Turn it into a game or ritual people would do for fun.",
}
DEFAULT_ORDER = tuple(list(LENSES)[:5])


def lens_weights(yields: dict[tuple[str, str], tuple[int, int]]) -> dict[str, float]:
    """Smoothed survival share per lens, over all models: (s + p) / (o + 2p)."""
    prior = settings.diverge_yield_prior
    weights = {}
    for lens in LENSES:
        offered = sum(o for (_, lk), (o, _) in yields.items() if lk == lens)
        survived = sum(s for (_, lk), (_, s) in yields.items() if lk == lens)
        weights[lens] = (survived + prior) / (offered + 2 * prior)
    return weights


def choose_lenses(
    yields: dict[tuple[str, str], tuple[int, int]],
    count: int,
    rng: random.Random,
    exploration_rate: float | None = None,
) -> list[str]:
    """``count`` distinct lens keys. No yield data yet: the card's lenses in order.

    Otherwise each slot is explored (uniform among the rest) with probability
    ``diverge_exploration_rate`` and exploited (weighted by yield) otherwise.
    """
    rate = settings.diverge_exploration_rate if exploration_rate is None else exploration_rate
    count = min(count, len(LENSES))
    if not yields:
        return list(LENSES)[:count]
    weights = lens_weights(yields)
    remaining = list(LENSES)
    chosen: list[str] = []
    while len(chosen) < count:
        if rng.random() < rate:
            pick = rng.choice(remaining)
        else:
            total = sum(weights[k] for k in remaining)
            point, acc, pick = rng.random() * total, 0.0, remaining[-1]
            for k in remaining:
                acc += weights[k]
                if point < acc:
                    pick = k
                    break
        remaining.remove(pick)
        chosen.append(pick)
    return chosen
