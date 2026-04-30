# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

enlearn is a local-first English vocabulary learning TUI/CLI. It imports words from the ECDICT open-source dictionary (cet4/cet6/ielts/toefl/gre/etc.) and uses a simplified SM-2 spaced repetition algorithm to schedule reviews. All data is stored in a local SQLite database.

## Commands

```bash
# Run TUI (default command)
python main.py
python main.py tui

# CLI commands
python main.py categories          # list supported word categories
python main.py fetch               # import current learning category
python main.py fetch -c cet6       # import specific category
python main.py review              # review due words
python main.py stats               # show learning statistics
python main.py config              # view/update settings
python main.py add <word> -t <translation>  # add word manually
python main.py list --limit 20     # list imported words

# Via uv
uv run enlearn <command>
```

No test suite or linter is configured. Python >=3.13 required, zero external dependencies.

## Architecture

```
enlearn/
├── cli.py      # argparse entry point, dispatches to TUI or CLI subcommands
├── tui.py      # curses-based terminal UI (TuiApp class)
├── db.py       # SQLite layer: schema, CRUD, settings, review queries
├── review.py   # SM-2 spaced repetition algorithm (schedule_review)
├── sources.py  # ECDICT download/cache, CSV parsing, category normalization
├── models.py   # Word, DueWord dataclasses
└── paths.py    # .enlearn/ directory layout (DB_PATH, CACHE_DIR)
```

**Entry flow**: `main.py` → `cli.run()` → `db.connect()` + `db.init_db()` → `dispatch()` routes to either `run_tui()` or a CLI subcommand.

**Data flow for reviews**: `db.due_words()` fetches due items → user rates 0-5 → `review.schedule_review()` computes next interval/ease → `db.update_review()` persists.

**Word import flow**: `sources.iter_words_from_ecdict()` downloads/caches ECDICT CSV → filters by category tag → `db.add_words()` bulk inserts with ON CONFLICT upsert.

## Key Design Decisions

- Tags are stored as space-separated strings in the `words.tags` column; category filtering uses `instr(' ' || tags || ' ', ' <category> ')` pattern matching.
- The `settings` table is a simple key-value store. Category import status is tracked as `imported_category:<name>` keys.
- Mastered words are defined as: `repetitions >= 4 AND total_lapses = 0 AND ease_factor >= 2.8`. These are skipped in due-word queries by default.
- Review groups are 10 words each; words rated < 3 trigger immediate weak-word reinforcement within the group.
- All paths are relative to project root (`.enlearn/`), not user home.
