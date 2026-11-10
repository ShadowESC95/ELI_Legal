"""The standard measures of a ranking and of a set of answers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def recall_at(ranked: Sequence[str], relevant: Mapping[str, int], k: int) -> float:
    """Of the relevant items, the share found in the first ``k``."""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: Mapping[str, int]) -> float:
    """One over the rank of the first relevant item; nothing found is 0."""
    for i, item in enumerate(ranked, 1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked: Sequence[str], relevant: Mapping[str, int], k: int) -> float:
    """Normalised discounted cumulative gain: graded relevance, earlier counts more."""

    def gain(grades: Sequence[int]) -> float:
        return float(sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades)))

    ideal = gain(sorted(relevant.values(), reverse=True)[:k])
    return gain([relevant.get(item, 0) for item in ranked[:k]]) / ideal if ideal else 0.0


def precision_recall_f1(found: set[str], wanted: set[str]) -> tuple[float, float, float]:
    hits = len(found & wanted)
    precision = hits / len(found) if found else (1.0 if not wanted else 0.0)
    recall = hits / len(wanted) if wanted else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
