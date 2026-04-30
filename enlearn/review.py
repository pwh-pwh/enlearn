from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MAX_INTERVAL = 365
EASY_BONUS = 1.3


@dataclass(frozen=True)
class ReviewResult:
    ease_factor: float
    interval_days: int
    repetitions: int
    due_date: date
    lapsed: bool


def schedule_review(
    *,
    quality: int,
    ease_factor: float,
    interval_days: int,
    repetitions: int,
    today: date | None = None,
) -> ReviewResult:
    if quality < 0 or quality > 5:
        raise ValueError("quality must be between 0 and 5")

    today = today or date.today()
    new_ease = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))

    if quality < 3:
        return ReviewResult(
            ease_factor=round(new_ease, 2),
            interval_days=1,
            repetitions=0,
            due_date=today + timedelta(days=1),
            lapsed=True,
        )

    new_repetitions = repetitions + 1
    if new_repetitions == 1:
        new_interval = 1
    elif new_repetitions == 2:
        new_interval = 6
    else:
        new_interval = max(1, round(interval_days * new_ease))

    # Easy bonus: push easy words further out
    if quality == 5:
        new_interval = round(new_interval * EASY_BONUS)

    # Cap maximum interval
    new_interval = min(new_interval, MAX_INTERVAL)

    return ReviewResult(
        ease_factor=round(new_ease, 2),
        interval_days=new_interval,
        repetitions=new_repetitions,
        due_date=today + timedelta(days=new_interval),
        lapsed=False,
    )

