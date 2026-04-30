from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Word:
    id: int
    word: str
    phonetic: str
    translation: str
    definition: str
    pos: str
    tags: str
    source: str
    exchange: str = ""
    frequency: int = 0
    collins_level: int = 0
    starred: bool = False


@dataclass(frozen=True)
class DueWord:
    word_id: int
    word: str
    phonetic: str
    translation: str
    definition: str
    pos: str
    tags: str
    ease_factor: float
    interval_days: int
    repetitions: int
    due_date: date

