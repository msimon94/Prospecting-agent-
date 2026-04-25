from typing import List, Tuple

from ..signals.base import CompanySignal
from .scorer import score_signal, assign_priority


def route_signals(signals: List[CompanySignal]) -> List[Tuple[CompanySignal, int]]:
    """Score, prioritize, and sort signals highest-first."""
    scored: List[Tuple[CompanySignal, int]] = []
    for signal in signals:
        score = score_signal(signal)
        signal.priority = assign_priority(score)
        scored.append((signal, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
