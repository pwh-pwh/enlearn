from __future__ import annotations

import csv
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from .paths import CACHE_DIR


ECDICT_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
ECDICT_CACHE = CACHE_DIR / "ecdict.csv"

SUPPORTED_CATEGORIES = ["cet4", "cet6", "gk", "gre", "ielts", "ky", "toefl", "zk"]

CATEGORY_ALIASES = {
    "cet4": "cet4",
    "cet6": "cet6",
    "ielts": "ielts",
    "toefl": "toefl",
    "gre": "gre",
    "gk": "gk",
    "zk": "zk",
    "考研": "ky",
    "kaoyan": "ky",
    "ky": "ky",
}


def categories() -> list[str]:
    return SUPPORTED_CATEGORIES


def is_ecdict_cached() -> bool:
    return ECDICT_CACHE.exists()


def normalize_category(category: str) -> str:
    key = category.strip().lower()
    if key not in CATEGORY_ALIASES:
        known = ", ".join(categories())
        raise ValueError(f"unknown category '{category}'. Known categories: {known}")
    return CATEGORY_ALIASES[key]


def ensure_ecdict(*, refresh: bool = False) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if ECDICT_CACHE.exists() and not refresh:
        return ECDICT_CACHE

    try:
        with urllib.request.urlopen(ECDICT_URL, timeout=60) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        if ECDICT_CACHE.exists():
            return ECDICT_CACHE
        raise RuntimeError(f"failed to download ECDICT: {exc}") from exc

    ECDICT_CACHE.write_bytes(data)
    return ECDICT_CACHE


def iter_words_from_ecdict(category: str, *, limit: int | None = None, refresh: bool = False) -> Iterator[dict[str, str]]:
    tag = normalize_category(category)
    path = ensure_ecdict(refresh=refresh)
    yielded = 0

    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            tags = (row.get("tag") or "").strip()
            tag_set = set(tags.split())
            if tag not in tag_set:
                continue

            word = (row.get("word") or "").strip()
            translation = clean_text(row.get("translation") or "")
            if not word or not translation:
                continue

            yield {
                "word": word,
                "phonetic": clean_text(row.get("phonetic") or ""),
                "translation": translation,
                "definition": clean_text(row.get("definition") or ""),
                "pos": clean_text(row.get("pos") or ""),
                "tags": tags,
                "source": "ecdict",
                "exchange": clean_text(row.get("exchange") or ""),
                "frequency": _safe_int(row.get("bnc")),
                "collins_level": _safe_int(row.get("collins")),
            }
            yielded += 1
            if limit is not None and yielded >= limit:
                break


def clean_text(value: str) -> str:
    return value.replace("\\n", "; ").replace("\r", " ").replace("\n", " ").strip()


def _safe_int(value: object) -> int:
    try:
        return int(value) if value else 0
    except (ValueError, TypeError):
        return 0
