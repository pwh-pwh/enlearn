from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from .models import DueWord, Word
from .paths import DB_PATH


DEFAULT_DAILY_WORD_LIMIT = 50
DEFAULT_LEARNING_CATEGORY = "cet4"
DEFAULT_RANDOM_REVIEW_ORDER = False
DEFAULT_REVIEW_GROUP_SIZE = 10
DEFAULT_REVIEW_MODE = "en-cn"

MASTERED_REPETITIONS = 4
MASTERED_EASE_FACTOR = 2.8


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE COLLATE NOCASE,
            phonetic TEXT NOT NULL DEFAULT '',
            translation TEXT NOT NULL DEFAULT '',
            definition TEXT NOT NULL DEFAULT '',
            pos TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reviews (
            word_id INTEGER PRIMARY KEY,
            ease_factor REAL NOT NULL DEFAULT 2.5,
            interval_days INTEGER NOT NULL DEFAULT 0,
            repetitions INTEGER NOT NULL DEFAULT 0,
            due_date TEXT NOT NULL,
            last_reviewed TEXT,
            total_reviews INTEGER NOT NULL DEFAULT 0,
            total_lapses INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('daily_word_limit', ?)",
        (str(DEFAULT_DAILY_WORD_LIMIT),),
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('learning_category', ?)",
        (DEFAULT_LEARNING_CATEGORY,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('random_review_order', ?)",
        (bool_to_setting(DEFAULT_RANDOM_REVIEW_ORDER),),
    )
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply idempotent schema migrations for existing databases."""
    word_cols = {row[1] for row in conn.execute("PRAGMA table_info(words)")}
    if "starred" not in word_cols:
        conn.execute("ALTER TABLE words ADD COLUMN starred INTEGER NOT NULL DEFAULT 0")
    if "exchange" not in word_cols:
        conn.execute("ALTER TABLE words ADD COLUMN exchange TEXT NOT NULL DEFAULT ''")
    if "frequency" not in word_cols:
        conn.execute("ALTER TABLE words ADD COLUMN frequency INTEGER NOT NULL DEFAULT 0")
    if "collins_level" not in word_cols:
        conn.execute("ALTER TABLE words ADD COLUMN collins_level INTEGER NOT NULL DEFAULT 0")

    review_cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    if "first_seen" not in review_cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN first_seen TEXT")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_activity (
            date TEXT PRIMARY KEY,
            words_reviewed INTEGER NOT NULL DEFAULT 0,
            new_words_learned INTEGER NOT NULL DEFAULT 0
        )"""
    )


def add_word(
    conn: sqlite3.Connection,
    *,
    word: str,
    phonetic: str = "",
    translation: str = "",
    definition: str = "",
    pos: str = "",
    tags: str = "",
    source: str = "manual",
    exchange: str = "",
    frequency: int = 0,
    collins_level: int = 0,
    commit: bool = True,
) -> int:
    normalized = word.strip()
    if not normalized:
        raise ValueError("word cannot be empty")

    cur = conn.execute(
        """
        INSERT INTO words (word, phonetic, translation, definition, pos, tags, source, exchange, frequency, collins_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(word) DO UPDATE SET
            phonetic = CASE WHEN excluded.phonetic != '' THEN excluded.phonetic ELSE words.phonetic END,
            translation = CASE WHEN excluded.translation != '' THEN excluded.translation ELSE words.translation END,
            definition = CASE WHEN excluded.definition != '' THEN excluded.definition ELSE words.definition END,
            pos = CASE WHEN excluded.pos != '' THEN excluded.pos ELSE words.pos END,
            tags = CASE
                WHEN words.tags = '' THEN excluded.tags
                WHEN excluded.tags = '' THEN words.tags
                WHEN instr(' ' || words.tags || ' ', ' ' || excluded.tags || ' ') > 0 THEN words.tags
                ELSE words.tags || ' ' || excluded.tags
            END,
            source = excluded.source,
            exchange = CASE WHEN excluded.exchange != '' THEN excluded.exchange ELSE words.exchange END,
            frequency = CASE WHEN excluded.frequency != 0 THEN excluded.frequency ELSE words.frequency END,
            collins_level = CASE WHEN excluded.collins_level != 0 THEN excluded.collins_level ELSE words.collins_level END
        RETURNING id
        """,
        (normalized, phonetic, translation, definition, pos, tags, source, exchange, frequency, collins_level),
    )
    word_id = int(cur.fetchone()["id"])
    conn.execute(
        "INSERT OR IGNORE INTO reviews (word_id, due_date) VALUES (?, ?)",
        (word_id, date.today().isoformat()),
    )
    if commit:
        conn.commit()
    return word_id


def add_words(conn: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> int:
    count = 0
    try:
        for row in rows:
            add_word(
                conn,
                word=str(row["word"]),
                phonetic=str(row.get("phonetic", "")),
                translation=str(row.get("translation", "")),
                definition=str(row.get("definition", "")),
                pos=str(row.get("pos", "")),
                tags=str(row.get("tags", "")),
                source=str(row.get("source", "remote")),
                exchange=str(row.get("exchange", "")),
                frequency=int(row.get("frequency", 0)),
                collins_level=int(row.get("collins_level", 0)),
                commit=False,
            )
            count += 1
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return count


def is_category_imported(conn: sqlite3.Connection, category: str) -> bool:
    return get_setting(conn, f"imported_category:{category}", "0") == "1"


def mark_category_imported(conn: sqlite3.Connection, category: str) -> None:
    set_setting(conn, f"imported_category:{category}", "1")


def count_words(conn: sqlite3.Connection, *, category: str | None = None) -> int:
    if category:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM words WHERE instr(' ' || tags || ' ', ?) > 0",
            (f" {category} ",),
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS total FROM words").fetchone()
    return int(row["total"])


def list_words(conn: sqlite3.Connection, *, category: str | None = None, limit: int = 50) -> list[Word]:
    params: list[object] = []
    where = ""
    if category:
        where = "WHERE instr(' ' || tags || ' ', ?) > 0"
        params.append(f" {category} ")
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, word, phonetic, translation, definition, pos, tags, source,
               exchange, frequency, collins_level, starred
        FROM words
        {where}
        ORDER BY word COLLATE NOCASE
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [Word(**dict(row)) for row in rows]


def due_words(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    category: str | None = None,
    random_order: bool = False,
    skip_mastered: bool = True,
    skip_new: bool = False,
) -> list[DueWord]:
    params: list[object] = []
    category_filter = ""
    mastered_filter = ""
    new_filter = ""
    if category:
        category_filter = "AND instr(' ' || w.tags || ' ', ?) > 0"
        params.append(f" {category} ")
    if skip_mastered:
        mastered_filter = """
        AND NOT (
            r.repetitions >= ?
            AND r.total_lapses = 0
            AND r.ease_factor >= ?
        )
        """
        params.extend([MASTERED_REPETITIONS, MASTERED_EASE_FACTOR])
    if skip_new:
        new_filter = "AND r.total_reviews > 0"
    params.append(limit)
    order_by = "RANDOM()" if random_order else "date(r.due_date), r.repetitions, w.word COLLATE NOCASE"
    rows = conn.execute(
        f"""
        SELECT
            w.id AS word_id,
            w.word,
            w.phonetic,
            w.translation,
            w.definition,
            w.pos,
            w.tags,
            r.ease_factor,
            r.interval_days,
            r.repetitions,
            r.due_date
        FROM words w
        JOIN reviews r ON r.word_id = w.id
        WHERE date(r.due_date) <= date('now', 'localtime')
        {category_filter}
        {mastered_filter}
        {new_filter}
        ORDER BY {order_by}
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        DueWord(
            word_id=int(row["word_id"]),
            word=row["word"],
            phonetic=row["phonetic"],
            translation=row["translation"],
            definition=row["definition"],
            pos=row["pos"],
            tags=row["tags"],
            ease_factor=float(row["ease_factor"]),
            interval_days=int(row["interval_days"]),
            repetitions=int(row["repetitions"]),
            due_date=date.fromisoformat(row["due_date"]),
        )
        for row in rows
    ]


def update_review(
    conn: sqlite3.Connection,
    *,
    word_id: int,
    ease_factor: float,
    interval_days: int,
    repetitions: int,
    due_date: date,
    lapsed: bool,
    is_new: bool = False,
) -> None:
    conn.execute(
        """
        UPDATE reviews
        SET ease_factor = ?,
            interval_days = ?,
            repetitions = ?,
            due_date = ?,
            last_reviewed = date('now', 'localtime'),
            total_reviews = total_reviews + 1,
            total_lapses = total_lapses + ?
        WHERE word_id = ?
        """,
        (ease_factor, interval_days, repetitions, due_date.isoformat(), 1 if lapsed else 0, word_id),
    )
    record_daily_activity(conn, words_reviewed=1, new_words_learned=1 if is_new else 0)


def stats(conn: sqlite3.Connection, *, category: str | None = None) -> dict[str, int | float]:
    params: list[object] = []
    where = ""
    if category:
        where = "WHERE instr(' ' || w.tags || ' ', ?) > 0"
        params.append(f" {category} ")
    row = conn.execute(
        f"""
        SELECT
            COUNT(w.id) AS total_words,
            SUM(CASE WHEN date(r.due_date) <= date('now', 'localtime') THEN 1 ELSE 0 END) AS due_words,
            SUM(CASE WHEN r.total_reviews = 0 THEN 1 ELSE 0 END) AS new_words,
            SUM(CASE
                WHEN r.repetitions >= {MASTERED_REPETITIONS}
                    AND r.total_lapses = 0
                    AND r.ease_factor >= {MASTERED_EASE_FACTOR}
                THEN 1 ELSE 0
            END) AS mastered_words,
            SUM(CASE
                WHEN r.total_lapses > 0
                    OR r.ease_factor < 2.3
                THEN 1 ELSE 0
            END) AS weak_words,
            COALESCE(SUM(r.total_reviews), 0) AS total_reviews,
            COALESCE(SUM(r.total_lapses), 0) AS total_lapses,
            COALESCE(AVG(r.ease_factor), 0) AS avg_ease
        FROM words w
        LEFT JOIN reviews r ON r.word_id = w.id
        {where}
        """,
        params,
    ).fetchone()
    total_reviews = int(row["total_reviews"])
    total_lapses = int(row["total_lapses"])
    correct_rate = 0.0
    if total_reviews:
        correct_rate = round((total_reviews - total_lapses) * 100 / total_reviews, 1)
    return {
        "total_words": int(row["total_words"]),
        "due_words": int(row["due_words"] or 0),
        "new_words": int(row["new_words"] or 0),
        "mastered_words": int(row["mastered_words"] or 0),
        "weak_words": int(row["weak_words"] or 0),
        "total_reviews": total_reviews,
        "total_lapses": total_lapses,
        "correct_rate": correct_rate,
        "avg_ease": round(float(row["avg_ease"] or 0), 2),
    }


def progress_summary(conn: sqlite3.Connection, *, category: str | None = None) -> dict[str, int | float]:
    item = stats(conn, category=category)
    total_words = int(item["total_words"])
    mastered_words = int(item["mastered_words"])
    weak_words = int(item["weak_words"])
    new_words = int(item["new_words"])
    learning_words = max(0, total_words - mastered_words - new_words)
    mastered_rate = 0.0
    if total_words:
        mastered_rate = round(mastered_words * 100 / total_words, 1)
    return {
        **item,
        "learning_words": learning_words,
        "mastered_rate": mastered_rate,
        "remaining_words": max(0, total_words - mastered_words),
    }


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()


def get_daily_word_limit(conn: sqlite3.Connection) -> int:
    raw = get_setting(conn, "daily_word_limit", str(DEFAULT_DAILY_WORD_LIMIT))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_DAILY_WORD_LIMIT
    if value <= 0:
        return DEFAULT_DAILY_WORD_LIMIT
    return value


def set_daily_word_limit(conn: sqlite3.Connection, value: int) -> None:
    if value <= 0:
        raise ValueError("daily word limit must be greater than 0")
    set_setting(conn, "daily_word_limit", str(value))


def get_learning_category(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "learning_category", DEFAULT_LEARNING_CATEGORY)


def set_learning_category(conn: sqlite3.Connection, category: str) -> None:
    set_setting(conn, "learning_category", category)


def get_random_review_order(conn: sqlite3.Connection) -> bool:
    raw = get_setting(conn, "random_review_order", bool_to_setting(DEFAULT_RANDOM_REVIEW_ORDER))
    return setting_to_bool(raw)


def set_random_review_order(conn: sqlite3.Connection, value: bool) -> None:
    set_setting(conn, "random_review_order", bool_to_setting(value))


def get_review_mode(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "review_mode", DEFAULT_REVIEW_MODE)


def set_review_mode(conn: sqlite3.Connection, mode: str) -> None:
    if mode not in {"en-cn", "cn-en", "mixed"}:
        raise ValueError(f"invalid review mode '{mode}'. Use: en-cn, cn-en, mixed")
    set_setting(conn, "review_mode", mode)


def bool_to_setting(value: bool) -> str:
    return "1" if value else "0"


def setting_to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


# --- Phase 1: Search ---


def search_words(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[Word]:
    q = query.strip()
    if not q:
        return []
    pattern = f"%{q}%"
    prefix = f"{q}%"
    rows = conn.execute(
        """SELECT id, word, phonetic, translation, definition, pos, tags, source,
                  exchange, frequency, collins_level, starred
           FROM words
           WHERE word LIKE ? OR translation LIKE ?
           ORDER BY
             CASE WHEN word LIKE ? THEN 0 ELSE 1 END,
             word COLLATE NOCASE
           LIMIT ?""",
        (pattern, pattern, prefix, limit),
    ).fetchall()
    return [Word(**dict(row)) for row in rows]


# --- Phase 1: Star/Favorite ---


def toggle_star(conn: sqlite3.Connection, word_id: int) -> bool:
    """Toggle starred status. Returns new starred state."""
    row = conn.execute("SELECT starred FROM words WHERE id = ?", (word_id,)).fetchone()
    if row is None:
        raise ValueError(f"word id {word_id} not found")
    new_val = 0 if row["starred"] else 1
    conn.execute("UPDATE words SET starred = ? WHERE id = ?", (new_val, word_id))
    conn.commit()
    return bool(new_val)


def starred_words(conn: sqlite3.Connection, limit: int = 50) -> list[Word]:
    rows = conn.execute(
        """SELECT id, word, phonetic, translation, definition, pos, tags, source,
                  exchange, frequency, collins_level, starred
           FROM words
           WHERE starred = 1
           ORDER BY word COLLATE NOCASE
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [Word(**dict(row)) for row in rows]


def count_starred(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM words WHERE starred = 1").fetchone()
    return int(row["c"])


# --- Phase 1: Daily Activity / Streaks ---


def record_daily_activity(conn: sqlite3.Connection, *, words_reviewed: int = 0, new_words_learned: int = 0) -> None:
    if words_reviewed == 0 and new_words_learned == 0:
        return
    conn.execute(
        """INSERT INTO daily_activity (date, words_reviewed, new_words_learned)
           VALUES (date('now', 'localtime'), ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             words_reviewed = daily_activity.words_reviewed + excluded.words_reviewed,
             new_words_learned = daily_activity.new_words_learned + excluded.new_words_learned""",
        (words_reviewed, new_words_learned),
    )
    conn.commit()


def get_streak(conn: sqlite3.Connection) -> int:
    """Count consecutive days of activity ending today or yesterday."""
    rows = conn.execute(
        "SELECT date FROM daily_activity ORDER BY date DESC"
    ).fetchall()
    if not rows:
        return 0
    streak = 0
    expected = date.today()
    for row in rows:
        d = date.fromisoformat(row["date"])
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif streak == 0 and d == expected - timedelta(days=1):
            expected = d
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


def get_longest_streak(conn: sqlite3.Connection) -> int:
    """Find the longest consecutive activity streak."""
    rows = conn.execute(
        "SELECT date FROM daily_activity ORDER BY date"
    ).fetchall()
    if not rows:
        return 0
    longest = 0
    current = 1
    prev = date.fromisoformat(rows[0]["date"])
    for row in rows[1:]:
        d = date.fromisoformat(row["date"])
        if d == prev + timedelta(days=1):
            current += 1
        else:
            longest = max(longest, current)
            current = 1
        prev = d
    return max(longest, current)


def daily_review_counts(conn: sqlite3.Connection, days: int = 7) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT date, words_reviewed, new_words_learned
           FROM daily_activity ORDER BY date DESC LIMIT ?""",
        (days,),
    ).fetchall()
    return [{"date": row["date"], "count": row["words_reviewed"], "new": row["new_words_learned"]} for row in rows]


def list_words_filtered(
    conn: sqlite3.Connection,
    *,
    status: str = "all",
    sort: str = "alpha",
    category: str | None = None,
    limit: int = 50,
) -> list[Word]:
    """List words with status filter and sort options.

    status: all, new, learning, mastered, weak, starred
    sort: alpha, frequency, collins
    """
    params: list[object] = []
    where_parts: list[str] = []

    if category:
        where_parts.append("instr(' ' || w.tags || ' ', ?) > 0")
        params.append(f" {category} ")

    if status == "new":
        where_parts.append("r.total_reviews = 0")
    elif status == "learning":
        where_parts.append(f"r.total_reviews > 0 AND NOT (r.repetitions >= {MASTERED_REPETITIONS} AND r.total_lapses = 0 AND r.ease_factor >= {MASTERED_EASE_FACTOR})")
    elif status == "mastered":
        where_parts.append(f"r.repetitions >= {MASTERED_REPETITIONS} AND r.total_lapses = 0 AND r.ease_factor >= {MASTERED_EASE_FACTOR}")
    elif status == "weak":
        where_parts.append("(r.total_lapses > 0 OR r.ease_factor < 2.3)")
    elif status == "starred":
        where_parts.append("w.starred = 1")

    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    order = "w.word COLLATE NOCASE"
    if sort == "frequency":
        order = "w.frequency ASC, w.word COLLATE NOCASE"
    elif sort == "collins":
        order = "w.collins_level DESC, w.word COLLATE NOCASE"

    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT w.id, w.word, w.phonetic, w.translation, w.definition, w.pos, w.tags, w.source,
               w.exchange, w.frequency, w.collins_level, w.starred
        FROM words w
        JOIN reviews r ON r.word_id = w.id
        {where}
        ORDER BY {order}
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [Word(**dict(row)) for row in rows]


def count_new_words(conn: sqlite3.Connection, category: str | None = None) -> int:
    """Count words that have never been reviewed."""
    params: list[object] = []
    category_filter = ""
    if category:
        category_filter = "AND instr(' ' || w.tags || ' ', ?) > 0"
        params.append(f" {category} ")
    row = conn.execute(
        f"""SELECT COUNT(*) AS c
            FROM words w
            JOIN reviews r ON r.word_id = w.id
            WHERE r.total_reviews = 0
            AND date(r.due_date) <= date('now', 'localtime')
            {category_filter}""",
        params,
    ).fetchone()
    return int(row["c"])


def new_words(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    category: str | None = None,
    random_order: bool = False,
) -> list[DueWord]:
    """Return words that have never been reviewed (new words to learn)."""
    params: list[object] = []
    category_filter = ""
    if category:
        category_filter = "AND instr(' ' || w.tags || ' ', ?) > 0"
        params.append(f" {category} ")
    params.append(limit)
    order_by = "RANDOM()" if random_order else "w.word COLLATE NOCASE"
    rows = conn.execute(
        f"""
        SELECT
            w.id AS word_id,
            w.word,
            w.phonetic,
            w.translation,
            w.definition,
            w.pos,
            w.tags,
            r.ease_factor,
            r.interval_days,
            r.repetitions,
            r.due_date
        FROM words w
        JOIN reviews r ON r.word_id = w.id
        WHERE r.total_reviews = 0
        AND date(r.due_date) <= date('now', 'localtime')
        {category_filter}
        ORDER BY {order_by}
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        DueWord(
            word_id=int(row["word_id"]),
            word=row["word"],
            phonetic=row["phonetic"],
            translation=row["translation"],
            definition=row["definition"],
            pos=row["pos"],
            tags=row["tags"],
            ease_factor=float(row["ease_factor"]),
            interval_days=int(row["interval_days"]),
            repetitions=int(row["repetitions"]),
            due_date=date.fromisoformat(row["due_date"]),
        )
        for row in rows
    ]
