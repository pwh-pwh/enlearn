from __future__ import annotations

import argparse
from sqlite3 import Connection

from . import db
from .review import schedule_review
from .sources import categories as source_categories
from .sources import is_ecdict_cached, iter_words_from_ecdict, normalize_category
from .tui import run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="enlearn", description="英语单词学习记忆 TUI/CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("tui", help="启动终端图形界面")

    fetch = subparsers.add_parser("fetch", help="从网络词库导入单词")
    fetch.add_argument("--category", "-c", help="词库类别，默认读取学习设置")
    fetch.add_argument("--refresh", action="store_true", help="未导入时强制重新下载远程词库")

    subparsers.add_parser("categories", help="列出支持的词库类别")

    add = subparsers.add_parser("add", help="手动添加单词")
    add.add_argument("word", help="英文单词")
    add.add_argument("--translation", "-t", required=True, help="中文释义")
    add.add_argument("--phonetic", "-p", default="", help="音标")
    add.add_argument("--definition", "-d", default="", help="英文释义")
    add.add_argument("--pos", default="", help="词性")
    add.add_argument("--category", "-c", default="", help="类别标签")

    list_cmd = subparsers.add_parser("list", help="查看已导入单词")
    list_cmd.add_argument("--category", "-c", help="按类别过滤")
    list_cmd.add_argument("--limit", "-n", type=int, default=50, help="最多显示数量，默认 50")

    search_cmd = subparsers.add_parser("search", help="搜索单词")
    search_cmd.add_argument("query", help="搜索关键词（英文或中文）")
    search_cmd.add_argument("--limit", "-n", type=int, default=20, help="最多显示数量，默认 20")

    star_cmd = subparsers.add_parser("star", help="收藏/取消收藏单词")
    star_cmd.add_argument("word_id", type=int, help="单词 ID")

    subparsers.add_parser("starred", help="查看已收藏单词")

    review = subparsers.add_parser("review", help="复习今天到期的旧词")
    review.add_argument("--limit", "-n", type=int, help="最多复习数量，默认读取每日学习数量配置")
    review.add_argument("--category", "-c", help="复习指定词库，默认读取学习设置")
    review.add_argument("--mode", "-m", choices=["en-cn", "cn-en", "mixed"], help="复习模式，默认读取设置")
    review_order = review.add_mutually_exclusive_group()
    review_order.add_argument("--random", action="store_true", help="本次复习使用乱序")
    review_order.add_argument("--ordered", action="store_true", help="本次复习使用到期顺序")

    learn = subparsers.add_parser("learn", help="学习新词")
    learn.add_argument("--limit", "-n", type=int, help="最多学习数量，默认读取每日学习数量配置")
    learn.add_argument("--category", "-c", help="学习指定词库，默认读取学习设置")
    learn.add_argument("--mode", "-m", choices=["en-cn", "cn-en", "mixed"], help="学习模式，默认读取设置")
    learn_order = learn.add_mutually_exclusive_group()
    learn_order.add_argument("--random", action="store_true", help="本次学习使用乱序")
    learn_order.add_argument("--ordered", action="store_true", help="本次学习使用顺序")

    config = subparsers.add_parser("config", help="查看或修改学习配置")
    config.add_argument("--daily-limit", type=int, help="设置每天学习的单词数量")
    config.add_argument("--category", "-c", help="设置学习词库，如 cet4/cet6/ielts/toefl/gre")
    config.add_argument("--random-order", choices=["on", "off"], help="设置是否乱序复习")
    config.add_argument("--mode", "-m", choices=["en-cn", "cn-en", "mixed"], help="设置复习模式")

    subparsers.add_parser("stats", help="查看学习统计")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with db.connect() as conn:
        db.init_db(conn)
        try:
            return dispatch(conn, args)
        except (RuntimeError, ValueError) as exc:
            parser.exit(1, f"错误: {exc}\n")


def dispatch(conn: Connection, args: argparse.Namespace) -> int:
    if args.command is None or args.command == "tui":
        run_tui(conn)
        return 0

    if args.command == "categories":
        for category in source_categories():
            print(category)
        return 0

    if args.command == "fetch":
        category = normalize_category(args.category or db.get_learning_category(conn))
        if db.is_category_imported(conn, category):
            total = db.count_words(conn, category=category)
            print(f"{category} 词库已经导入，当前 {total} 个单词")
            return 0
        cached = is_ecdict_cached() and not args.refresh
        before = db.count_words(conn, category=category)
        rows = iter_words_from_ecdict(category, refresh=args.refresh)
        scanned = db.add_words(conn, rows)
        after = db.count_words(conn, category=category)
        db.mark_category_imported(conn, category)
        cache_text = "使用本地缓存词库" if cached else "已下载远程词库"
        print(f"{cache_text}，处理 {scanned} 个 {category} 单词，新增 {after - before} 个，当前 {after} 个")
        return 0

    if args.command == "add":
        tag = normalize_category(args.category) if args.category else ""
        word_id = db.add_word(
            conn,
            word=args.word,
            phonetic=args.phonetic,
            translation=args.translation,
            definition=args.definition,
            pos=args.pos,
            tags=tag,
            source="manual",
        )
        print(f"已添加: {args.word} (id={word_id})")
        return 0

    if args.command == "list":
        category = normalize_category(args.category) if args.category else None
        words = db.list_words(conn, category=category, limit=args.limit)
        if not words:
            print("暂无单词")
            return 0
        for item in words:
            phonetic = f" [{item.phonetic}]" if item.phonetic else ""
            tags = f" ({item.tags})" if item.tags else ""
            star = " ★" if item.starred else ""
            print(f"{item.id}. {item.word}{phonetic} - {item.translation}{tags}{star}")
        return 0

    if args.command == "search":
        results = db.search_words(conn, args.query, limit=args.limit)
        if not results:
            print(f"未找到匹配 '{args.query}' 的单词")
            return 0
        for item in results:
            phonetic = f" [{item.phonetic}]" if item.phonetic else ""
            star = " ★" if item.starred else ""
            print(f"{item.id}. {item.word}{phonetic} - {item.translation}{star}")
        return 0

    if args.command == "star":
        try:
            new_state = db.toggle_star(conn, args.word_id)
            state_text = "已收藏" if new_state else "已取消收藏"
            print(f"{state_text}: word_id={args.word_id}")
        except ValueError as exc:
            print(f"错误: {exc}")
            return 1
        return 0

    if args.command == "starred":
        words = db.starred_words(conn)
        if not words:
            print("暂无收藏单词")
            return 0
        for item in words:
            phonetic = f" [{item.phonetic}]" if item.phonetic else ""
            print(f"{item.id}. {item.word}{phonetic} - {item.translation}")
        return 0

    if args.command == "review":
        limit = args.limit if args.limit is not None else db.get_daily_word_limit(conn)
        category = normalize_category(args.category or db.get_learning_category(conn))
        random_order = db.get_random_review_order(conn)
        mode = args.mode if args.mode else db.get_review_mode(conn)
        if args.random:
            random_order = True
        elif args.ordered:
            random_order = False
        return review_due_words(conn, limit=limit, category=category, random_order=random_order, skip_new=True, mode=mode)

    if args.command == "learn":
        limit = args.limit if args.limit is not None else db.get_daily_word_limit(conn)
        category = normalize_category(args.category or db.get_learning_category(conn))
        random_order = db.get_random_review_order(conn)
        mode = args.mode if args.mode else db.get_review_mode(conn)
        if args.random:
            random_order = True
        elif args.ordered:
            random_order = False
        return learn_new_words(conn, limit=limit, category=category, random_order=random_order, mode=mode)

    if args.command == "config":
        if args.daily_limit is not None:
            db.set_daily_word_limit(conn, args.daily_limit)
        if args.category:
            db.set_learning_category(conn, normalize_category(args.category))
        if args.random_order:
            db.set_random_review_order(conn, args.random_order == "on")
        if args.mode:
            db.set_review_mode(conn, args.mode)
        mode_names = {"en-cn": "英→中", "cn-en": "中→英", "mixed": "混合"}
        print(f"每天学习数量: {db.get_daily_word_limit(conn)}")
        print(f"学习词库: {db.get_learning_category(conn)}")
        print(f"复习顺序: {'乱序' if db.get_random_review_order(conn) else '到期顺序'}")
        print(f"复习模式: {mode_names.get(db.get_review_mode(conn), db.get_review_mode(conn))}")
        return 0

    if args.command == "stats":
        category = db.get_learning_category(conn)
        item = db.progress_summary(conn, category=category)
        streak = db.get_streak(conn)
        longest = db.get_longest_streak(conn)
        print(f"学习词库: {category}")
        print(f"单词总数: {item['total_words']}")
        print(f"已掌握: {item['mastered_words']} ({item['mastered_rate']}%)")
        print(f"学习中: {item['learning_words']}")
        print(f"未学习: {item['new_words']}")
        print(f"错词/薄弱: {item['weak_words']}")
        print(f"今日到期: {item['due_words']}")
        print(f"复习次数: {item['total_reviews']}")
        print(f"遗忘次数: {item['total_lapses']}")
        print(f"正确率: {item['correct_rate']}%")
        print(f"平均熟练度: {item['avg_ease']}")
        print(f"连续学习: {streak} 天")
        print(f"最长连续: {longest} 天")
        return 0

    raise ValueError(f"unsupported command: {args.command}")


def review_due_words(
    conn: Connection,
    *,
    limit: int,
    category: str | None = None,
    random_order: bool = False,
    skip_new: bool = False,
    mode: str = "en-cn",
) -> int:
    if limit <= 0:
        raise ValueError("--limit must be greater than 0")

    due_words = db.due_words(conn, limit=limit, category=category, random_order=random_order, skip_new=skip_new)
    if not due_words:
        scope = f"{category} " if category else ""
        print(f"今天没有到期的 {scope}旧词需要复习")
        return 0

    import random as _random
    reviewed = 0
    group_size = db.DEFAULT_REVIEW_GROUP_SIZE
    for group_start in range(0, len(due_words), group_size):
        group = due_words[group_start : group_start + group_size]
        weak_items = []
        group_no = group_start // group_size + 1
        group_count = (len(due_words) + group_size - 1) // group_size
        print()
        print(f"第 {group_no}/{group_count} 组")
        for item in group:
            actual_mode = mode
            if mode == "mixed":
                actual_mode = _random.choice(["en-cn", "cn-en"])
            print()
            if actual_mode == "cn-en":
                print(f"释义: {item.translation}")
                if item.pos:
                    print(f"词性: {item.pos}")
                input("回忆英文单词后按回车查看答案...")
                print(f"单词: {item.word}")
                if item.phonetic:
                    print(f"音标: {item.phonetic}")
                if item.definition:
                    print(f"英文: {item.definition}")
            else:
                print(f"单词: {item.word}")
                if item.phonetic:
                    print(f"音标: {item.phonetic}")
                input("回忆释义后按回车查看答案...")
                print(f"释义: {item.translation}")
                if item.definition:
                    print(f"英文: {item.definition}")
                if item.pos:
                    print(f"词性: {item.pos}")

            quality = ask_quality()
            result = schedule_review(
                quality=quality,
                ease_factor=item.ease_factor,
                interval_days=item.interval_days,
                repetitions=item.repetitions,
            )
            db.update_review(
                conn,
                word_id=item.word_id,
                ease_factor=result.ease_factor,
                interval_days=result.interval_days,
                repetitions=result.repetitions,
                due_date=result.due_date,
                lapsed=result.lapsed,
            )
            if quality < 3:
                weak_items.append(item)
            print(f"下次复习: {result.due_date.isoformat()}，间隔 {result.interval_days} 天")
            reviewed += 1
        if weak_items:
            print()
            print(f"第 {group_no} 组错词强化")
            for item in weak_items:
                print(f"- {item.word}: {item.translation}")

    print()
    print(f"本次复习完成: {reviewed} 个单词")
    return 0


def learn_new_words(
    conn: Connection,
    *,
    limit: int,
    category: str | None = None,
    random_order: bool = False,
    mode: str = "en-cn",
) -> int:
    import random as _random

    if limit <= 0:
        raise ValueError("--limit must be greater than 0")

    words = db.new_words(conn, limit=limit, category=category, random_order=random_order)
    if not words:
        scope = f"{category} " if category else ""
        print(f"没有待学习的 {scope}新词")
        return 0

    learned = 0
    group_size = db.DEFAULT_REVIEW_GROUP_SIZE
    total = len(words)
    group_count = (total + group_size - 1) // group_size

    for group_start in range(0, total, group_size):
        group = words[group_start : group_start + group_size]
        group_no = group_start // group_size + 1

        # Phase 1: Learn — show full details, self-assess
        print()
        print(f"=== 第 {group_no}/{group_count} 组：学习 ===")
        for item in group:
            print()
            print(f"单词: {item.word}")
            if item.phonetic:
                print(f"音标: {item.phonetic}")
            print(f"释义: {item.translation}")
            if item.definition:
                print(f"英文: {item.definition}")
            if item.pos:
                print(f"词性: {item.pos}")

            quality = ask_learn_quality()
            result = schedule_review(
                quality=quality,
                ease_factor=item.ease_factor,
                interval_days=item.interval_days,
                repetitions=item.repetitions,
            )
            db.update_review(
                conn,
                word_id=item.word_id,
                ease_factor=result.ease_factor,
                interval_days=result.interval_days,
                repetitions=result.repetitions,
                due_date=result.due_date,
                lapsed=result.lapsed,
                is_new=True,
            )
            learned += 1

        # Phase 2: Review — test recall on the same words
        print()
        print(f"=== 第 {group_no}/{group_count} 组：复习 ===")
        word_ids = {item.word_id for item in group}
        review_items = [
            item for item in db.due_words(conn, limit=999, category=category)
            if item.word_id in word_ids
        ]
        weak_items = []
        for item in review_items:
            actual_mode = mode
            if mode == "mixed":
                actual_mode = _random.choice(["en-cn", "cn-en"])
            print()
            if actual_mode == "cn-en":
                print(f"释义: {item.translation}")
                if item.pos:
                    print(f"词性: {item.pos}")
                input("回忆英文单词后按回车查看答案...")
                print(f"单词: {item.word}")
                if item.phonetic:
                    print(f"音标: {item.phonetic}")
            else:
                print(f"单词: {item.word}")
                if item.phonetic:
                    print(f"音标: {item.phonetic}")
                input("回忆释义后按回车查看答案...")
                print(f"释义: {item.translation}")
                if item.definition:
                    print(f"英文: {item.definition}")

            quality = ask_quality()
            result = schedule_review(
                quality=quality,
                ease_factor=item.ease_factor,
                interval_days=item.interval_days,
                repetitions=item.repetitions,
            )
            db.update_review(
                conn,
                word_id=item.word_id,
                ease_factor=result.ease_factor,
                interval_days=result.interval_days,
                repetitions=result.repetitions,
                due_date=result.due_date,
                lapsed=result.lapsed,
            )
            if quality < 3:
                weak_items.append(item)
            print(f"下次复习: {result.due_date.isoformat()}，间隔 {result.interval_days} 天")
        if weak_items:
            print()
            print(f"第 {group_no} 组薄弱词强化")
            for item in weak_items:
                print(f"- {item.word}: {item.translation}")

    print()
    print(f"本次学习完成: {learned} 个新词（含复习）")
    return 0


def ask_quality() -> int:
    while True:
        raw = input("评分 0-5（0 完全忘记，5 很熟）: ").strip()
        try:
            quality = int(raw)
        except ValueError:
            print("请输入 0 到 5 的数字")
            continue
        if 0 <= quality <= 5:
            return quality
        print("请输入 0 到 5 的数字")


def ask_learn_quality() -> int:
    """Ask self-assessment for new word learning (0-3 mapped to SM-2 quality)."""
    mapping = {0: 0, 1: 2, 2: 4, 3: 5}
    while True:
        raw = input("自评 0-3（0 忘了 1 勉强 2 记住 3 很熟）: ").strip()
        try:
            level = int(raw)
        except ValueError:
            print("请输入 0 到 3 的数字")
            continue
        if 0 <= level <= 3:
            return mapping[level]
        print("请输入 0 到 3 的数字")
