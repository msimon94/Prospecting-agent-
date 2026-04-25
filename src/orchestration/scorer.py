from ..signals.base import CompanySignal, SignalType, SignalPriority

_BASE_SCORES: dict = {
    SignalType.JOB_CHANGE: 90,
    SignalType.FUNDING_ROUND: 85,
    SignalType.G2_INTENT: 80,
    SignalType.TECH_INSTALL: 65,
    SignalType.HIRING_SURGE: 60,
    SignalType.TECH_UNINSTALL: 55,
}


def score_signal(signal: CompanySignal) -> int:
    score = _BASE_SCORES.get(signal.signal_type, 50)

    if signal.signal_type == SignalType.FUNDING_ROUND:
        amount = signal.metadata.get("funding_amount") or 0
        if amount >= 10_000_000:
            score += 10
        elif amount >= 5_000_000:
            score += 5

    if signal.signal_type == SignalType.HIRING_SURGE:
        jobs = signal.metadata.get("open_positions") or 0
        if jobs >= 20:
            score += 10
        elif jobs >= 10:
            score += 5

    # Bump score if Apollo already told us who the target person is
    if signal.signal_type == SignalType.JOB_CHANGE and signal.metadata.get("person_id"):
        score += 5

    return min(score, 100)


def assign_priority(score: int) -> SignalPriority:
    if score >= 80:
        return SignalPriority.HIGH
    if score >= 60:
        return SignalPriority.MEDIUM
    return SignalPriority.LOW
