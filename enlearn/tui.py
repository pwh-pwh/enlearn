from __future__ import annotations

import curses
import textwrap
from dataclasses import dataclass
from datetime import date, timedelta
from sqlite3 import Connection

from . import db
from .review import schedule_review
from .sources import categories as source_categories
from .sources import is_ecdict_cached, iter_words_from_ecdict, normalize_category


MENU_ITEMS = [
    ("today", "今日任务"),
    ("review", "直接复习"),
    ("spelling", "拼写测试"),
    ("stats", "学习统计"),
    ("words", "单词列表"),
    ("search", "搜索单词"),
    ("starred", "已收藏"),
    ("fetch", "导入网络词库"),
    ("add", "手动添加单词"),
    ("settings", "学习设置"),
    ("quit", "退出"),
]


@dataclass
class Theme:
    normal: int = curses.A_NORMAL
    selected: int = curses.A_REVERSE
    title: int = curses.A_BOLD
    dim: int = curses.A_DIM
    accent: int = curses.A_BOLD
    panel: int = curses.A_NORMAL
    success: int = curses.A_BOLD


class TuiApp:
    def __init__(self, stdscr: curses.window, conn: Connection) -> None:
        self.stdscr = stdscr
        self.conn = conn
        self.selected = 0
        self.message = "↑/↓ 选择，Enter 确认，q 退出"
        self.theme = Theme()

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.init_theme()
        while True:
            self.draw_home()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                self.selected = (self.selected - 1) % len(MENU_ITEMS)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                self.selected = (self.selected + 1) % len(MENU_ITEMS)
            elif key in (curses.KEY_ENTER, 10, 13):
                action = MENU_ITEMS[self.selected][0]
                if action == "quit":
                    return
                self.handle_action(action)

    def init_theme(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)
        curses.init_pair(5, curses.COLOR_BLUE, -1)
        self.theme = Theme(
            normal=curses.A_NORMAL,
            selected=curses.color_pair(2) | curses.A_BOLD,
            title=curses.color_pair(1) | curses.A_BOLD,
            dim=curses.A_DIM,
            accent=curses.color_pair(3) | curses.A_BOLD,
            panel=curses.color_pair(5),
            success=curses.color_pair(4) | curses.A_BOLD,
        )

    def draw_home(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < 18 or width < 56:
            self.add_line(1, 2, "窗口太小，请放大终端后继续", self.theme.title)
            self.stdscr.refresh()
            return

        self.draw_frame("enlearn 英语单词记忆")
        self.add_line(2, 4, "本地词库 · 到期复习 · SM-2 记忆调度", self.theme.dim)

        learning_category = db.get_learning_category(self.conn)
        stat = db.progress_summary(self.conn, category=learning_category)
        daily_limit = db.get_daily_word_limit(self.conn)
        random_order = db.get_random_review_order(self.conn)
        streak = db.get_streak(self.conn)
        starred_count = db.count_starred(self.conn)
        review_mode = db.get_review_mode(self.conn)
        mode_names = {"en-cn": "英→中", "cn-en": "中→英", "mixed": "混合"}
        self.draw_box(4, 3, 6, width - 6, " 今日概览 ")
        first_line = [
            f"词库 {learning_category}",
            f"单词 {stat['total_words']}",
            f"到期 {stat['due_words']}",
            f"每日 {daily_limit}",
            "乱序" if random_order else "顺序",
        ]
        second_line = [
            f"正确率 {stat['correct_rate']}%",
            f"熟练度 {stat['avg_ease']}",
            f"连续 {streak}天",
            f"收藏 {starred_count}",
            f"模式 {mode_names.get(review_mode, review_mode)}",
        ]
        self.add_line(6, 6, "   ".join(first_line), self.theme.accent)
        self.add_line(7, 6, "   ".join(second_line), self.theme.dim)
        self.draw_labeled_progress(8, 6, "掌握进度", int(stat["mastered_words"]), int(stat["total_words"]))

        menu_width = min(30, max(22, width // 3))
        self.draw_box(11, 3, len(MENU_ITEMS) + 3, menu_width, " 菜单 ")
        self.draw_box(11, menu_width + 5, len(MENU_ITEMS) + 3, width - menu_width - 8, " 操作提示 ")

        top = 13
        for idx, (_, label) in enumerate(MENU_ITEMS):
            marker = "» " if idx == self.selected else "  "
            attr = self.theme.selected if idx == self.selected else self.theme.normal
            self.add_line(top + idx, 6, f"{marker}{label}", attr)

        help_x = menu_width + 8
        help_lines = [
            "↑/↓ 或 j/k 移动",
            "Enter 打开当前功能",
            "q 或 Esc 退出",
            "复习时按 0-5 评分",
        ]
        for idx, line in enumerate(help_lines):
            self.add_line(top + idx, help_x, line)

        self.draw_status(height, width)
        self.stdscr.refresh()

    def handle_action(self, action: str) -> None:
        if action == "today":
            self.today_screen()
        elif action == "review":
            self.review_screen()
        elif action == "spelling":
            self.spelling_screen()
        elif action == "stats":
            self.stats_screen()
        elif action == "words":
            self.words_screen()
        elif action == "search":
            self.search_screen()
        elif action == "starred":
            self.starred_screen()
        elif action == "fetch":
            self.fetch_screen()
        elif action == "add":
            self.add_word_screen()
        elif action == "settings":
            self.settings_screen()

    def stats_screen(self) -> None:
        learning_category = db.get_learning_category(self.conn)
        stat = db.progress_summary(self.conn, category=learning_category)
        streak = db.get_streak(self.conn)
        longest = db.get_longest_streak(self.conn)
        daily_counts = db.daily_review_counts(self.conn, days=7)
        mode_names = {"en-cn": "英→中", "cn-en": "中→英", "mixed": "混合"}
        review_mode = db.get_review_mode(self.conn)

        lines = [
            "学习统计",
            "",
            f"词库: {learning_category} | 模式: {mode_names.get(review_mode, review_mode)}",
            f"连续: {streak}天 | 最长: {longest}天 | 目标: {db.get_daily_word_limit(self.conn)}/天",
            "",
        ]

        # Word status distribution bar
        total = int(stat['total_words'])
        if total > 0:
            mastered = int(stat['mastered_words'])
            learning = int(stat['learning_words'])
            new_w = int(stat['new_words'])
            weak = int(stat['weak_words'])
            bar_w = 30
            m_len = max(1, round(bar_w * mastered / total)) if mastered else 0
            l_len = max(1, round(bar_w * learning / total)) if learning else 0
            n_len = max(1, round(bar_w * new_w / total)) if new_w else 0
            w_len = bar_w - m_len - l_len - n_len
            if w_len < 0:
                w_len = 0
            bar = "█" * m_len + "▓" * l_len + "░" * n_len + "▒" * w_len
            lines.append(f"单词分布: {bar}")
            lines.append(f"  █ 已掌握 {mastered}  ▓ 学习中 {learning}  ░ 未学习 {new_w}  ▒ 薄弱 {weak}")
            lines.append("")

        # Accuracy & reviews
        lines.append(f"复习 {stat['total_reviews']}次 | 遗忘 {stat['total_lapses']}次 | 正确率 {stat['correct_rate']}% | 熟练度 {stat['avg_ease']}")
        lines.append("")

        # Daily review chart (last 7 days)
        lines.append("近7天复习量:")
        if daily_counts:
            max_count = max((d["count"] for d in daily_counts), default=1) or 1
            bar_max = 20
            for d in reversed(daily_counts):
                day_str = str(d["date"])[-5:]  # MM-DD
                count = int(d["count"])
                bar_len = round(bar_max * count / max_count) if max_count else 0
                bar = "█" * bar_len
                lines.append(f"  {day_str} {bar} {count}")
        else:
            lines.append("  暂无数据")
        lines.append("")

        # Activity calendar (last 4 weeks)
        lines.append("近4周打卡日历:")
        activity_map = {str(d["date"]): int(d["count"]) for d in daily_counts}
        today = date.today()
        # Find the Monday of the current week
        start_of_week = today - timedelta(days=today.weekday())
        # Go back 3 more weeks
        cal_start = start_of_week - timedelta(weeks=3)
        lines.append("  一 二 三 四 五 六 日")
        current = cal_start
        week_line = "  "
        while current <= today:
            if current.weekday() == 0 and current != cal_start:
                lines.append(week_line.rstrip())
                week_line = "  "
            key = current.isoformat()
            if key in activity_map and activity_map[key] > 0:
                week_line += " + "
            elif current <= today:
                week_line += " · "
            else:
                week_line += "   "
            current += timedelta(days=1)
        lines.append(week_line.rstrip())

        lines.append("")
        lines.append("按任意键返回")
        self.show_text(lines)

    def search_screen(self) -> None:
        query = self.prompt("搜索单词（英文或中文）")
        if not query:
            return
        results = db.search_words(self.conn, query, limit=50)
        if not results:
            self.message = f"未找到匹配 '{query}' 的单词"
            return
        lines = [f"搜索结果: {query} ({len(results)} 个)", ""]
        for item in results:
            phonetic = f" [{item.phonetic}]" if item.phonetic else ""
            star = " ★" if item.starred else ""
            lines.append(f"{item.id}. {item.word}{phonetic} - {item.translation}{star}")
        lines.append("")
        lines.append("↑/↓ 滚动，按 q 返回")
        self.scroll_text(lines)

    def starred_screen(self) -> None:
        words = db.starred_words(self.conn, limit=100)
        if not words:
            self.message = "暂无收藏单词"
            return
        lines = [f"已收藏 ({len(words)} 个)", ""]
        for item in words:
            phonetic = f" [{item.phonetic}]" if item.phonetic else ""
            lines.append(f"{item.id}. {item.word}{phonetic} - {item.translation}")
        lines.append("")
        lines.append("↑/↓ 滚动，按 q 返回")
        self.scroll_text(lines)

    def today_screen(self) -> None:
        learning_category = db.get_learning_category(self.conn)
        stat = db.progress_summary(self.conn, category=learning_category)
        daily_limit = db.get_daily_word_limit(self.conn)
        random_order = db.get_random_review_order(self.conn)
        new_count = db.count_new_words(self.conn, learning_category)
        review_count = max(0, int(stat['due_words']) - new_count)
        today_activity = db.get_today_activity(self.conn)
        today_done = today_activity["words_reviewed"]
        today_new = today_activity["new_words_learned"]
        streak = db.get_streak(self.conn)
        self.stdscr.erase()
        self.draw_frame("今日任务")
        self.add_line(3, 4, f"词库: {learning_category}", self.theme.title)
        self.draw_labeled_progress(5, 4, "掌握进度", int(stat["mastered_words"]), int(stat["total_words"]))

        # Today's progress
        progress_pct = min(100, round(today_done * 100 / daily_limit)) if daily_limit else 0
        self.add_line(7, 4, f"今日已完成: {today_done}/{daily_limit} ({progress_pct}%)", self.theme.accent)
        if today_new > 0:
            self.add_line(8, 4, f"  其中新词: {today_new} 个", self.theme.dim)
        self.add_line(9, 4, f"连续学习: {streak} 天", self.theme.dim)

        # Remaining
        self.add_line(11, 4, f"待学习新词: {new_count} 个", self.theme.accent)
        self.add_line(12, 4, f"待复习旧词: {review_count} 个", self.theme.accent)
        self.add_line(13, 4, f"错词/薄弱: {stat['weak_words']}")
        self.add_line(14, 4, f"每日目标: {daily_limit} | 顺序: {'乱序' if random_order else '到期'}")

        if today_done >= daily_limit and new_count == 0 and review_count == 0:
            self.add_line(16, 4, "今日任务已完成！按 q 返回", self.theme.success)
        else:
            self.add_line(16, 4, "按 Enter 学习新词，r 复习旧词，q 返回", self.theme.dim)

        self.stdscr.refresh()
        while True:
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_ENTER, 10, 13):
                self.learn_new_screen()
                return
            if key in (ord("r"), ord("R")):
                self.review_screen()
                return

    def settings_screen(self) -> None:
        categories = source_categories()
        mode_names = {"en-cn": "英→中", "cn-en": "中→英", "mixed": "混合"}
        order_options = ["顺序", "乱序"]
        mode_options = ["en-cn", "cn-en", "mixed"]

        # Current values
        daily_limit = db.get_daily_word_limit(self.conn)
        category = db.get_learning_category(self.conn)
        random_order = db.get_random_review_order(self.conn)
        review_mode = db.get_review_mode(self.conn)

        cat_idx = categories.index(category) if category in categories else 0
        order_idx = 1 if random_order else 0
        mode_idx = mode_options.index(review_mode) if review_mode in mode_options else 0
        field = 0  # 0=daily_limit, 1=category, 2=order, 3=mode

        while True:
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            self.draw_frame("学习设置")

            y = 3
            fields = [
                ("每日学习数量", str(daily_limit)),
                ("学习词库", categories[cat_idx]),
                ("复习顺序", order_options[order_idx]),
                ("复习模式", f"{mode_options[mode_idx]} ({mode_names[mode_options[mode_idx]]})"),
            ]
            for idx, (label, val) in enumerate(fields):
                cursor = "» " if idx == field else "  "
                attr = self.theme.selected if idx == field else self.theme.normal
                self.add_line(y, 4, f"{cursor}{label}: {val}", attr)
                y += 1

            y += 1
            self.add_line(y, 4, "↑/↓ 切换字段  ←/→ 修改选项  Enter 编辑数量", self.theme.dim)
            self.add_line(y + 1, 4, "s 保存  q 取消", self.theme.dim)

            # Hint for current field
            y += 3
            if field == 0:
                self.add_line(y, 4, "提示: 按 Enter 输入数字，↑/↓ 增减", self.theme.dim)
            elif field == 1:
                self.add_line(y, 4, f"可选: {', '.join(categories)}", self.theme.dim)
            elif field == 2:
                self.add_line(y, 4, "←/→ 切换顺序/乱序", self.theme.dim)
            elif field == 3:
                self.add_line(y, 4, "←/→ 切换英→中 / 中→英 / 混合", self.theme.dim)

            self.stdscr.refresh()
            key = self.stdscr.getch()

            if key in (ord("q"), ord("Q"), 27):
                self.message = "设置已取消"
                return
            if key in (ord("s"), ord("S")):
                # Save all settings
                db.set_daily_word_limit(self.conn, daily_limit)
                db.set_learning_category(self.conn, categories[cat_idx])
                db.set_random_review_order(self.conn, order_idx == 1)
                db.set_review_mode(self.conn, mode_options[mode_idx])
                self.message = (
                    f"设置已保存：每日 {daily_limit}，"
                    f"词库 {categories[cat_idx]}，"
                    f"{order_options[order_idx]}，"
                    f"{mode_names[mode_options[mode_idx]]}"
                )
                return
            if key in (curses.KEY_UP, ord("k")):
                field = (field - 1) % 4
            elif key in (curses.KEY_DOWN, ord("j")):
                field = (field + 1) % 4
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("h"), ord("l")):
                if field == 1:
                    if key in (curses.KEY_RIGHT, ord("l")):
                        cat_idx = (cat_idx + 1) % len(categories)
                    else:
                        cat_idx = (cat_idx - 1) % len(categories)
                elif field == 2:
                    order_idx = 1 - order_idx
                elif field == 3:
                    if key in (curses.KEY_RIGHT, ord("l")):
                        mode_idx = (mode_idx + 1) % len(mode_options)
                    else:
                        mode_idx = (mode_idx - 1) % len(mode_options)
            elif key in (curses.KEY_ENTER, 10, 13):
                if field == 0:
                    raw = self.prompt("每天学习数量", default=str(daily_limit))
                    try:
                        val = int(raw)
                        if val > 0:
                            daily_limit = val
                    except ValueError:
                        pass

    def words_screen(self) -> None:
        category = self.prompt("输入类别过滤，留空显示全部")
        if category:
            try:
                category = normalize_category(category)
            except ValueError as exc:
                self.message = str(exc)
                return

        status_options = ["all", "new", "learning", "mastered", "weak", "starred"]
        status_labels = {"all": "全部", "new": "未学习", "learning": "学习中", "mastered": "已掌握", "weak": "薄弱", "starred": "收藏"}
        sort_options = ["alpha", "frequency", "collins"]
        sort_labels = {"alpha": "字母", "frequency": "词频", "collins": "Collins"}
        status_idx = 0
        sort_idx = 0
        offset = 0

        while True:
            status = status_options[status_idx]
            sort = sort_options[sort_idx]
            words = db.list_words_filtered(
                self.conn, status=status, sort=sort, category=category or None, limit=100,
            )
            filter_text = status_labels[status]
            sort_text = sort_labels[sort]
            cat_text = f"({category})" if category else ""
            title = f"单词列表 {cat_text} [{filter_text}] [{sort_text}]"

            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            self.draw_frame(title)
            visible: list[str] = []
            if not words:
                visible.append("暂无单词")
            for item in words:
                phonetic = f" [{item.phonetic}]" if item.phonetic else ""
                star = " ★" if item.starred else ""
                visible.append(f"{item.id}. {item.word}{phonetic} - {item.translation}{star}")
            max_offset = max(0, len(visible) - height + 5)
            offset = min(offset, max_offset)
            for idx, line in enumerate(visible[offset : offset + height - 4]):
                self.add_line(idx + 3, 2, line[:width - 4])
            self.add_line(height - 2, 2, "↑/↓ 滚动  f 筛选  s 排序  q 返回", self.theme.dim)
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_DOWN, ord("j"), ord("J")):
                offset = min(max_offset, offset + 1)
            elif key in (curses.KEY_UP, ord("k"), ord("K")):
                offset = max(0, offset - 1)
            elif key == curses.KEY_NPAGE:
                offset = min(max_offset, offset + height - 3)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - height + 3)
            elif key in (ord("f"), ord("F")):
                status_idx = (status_idx + 1) % len(status_options)
                offset = 0
            elif key in (ord("s"), ord("S")):
                sort_idx = (sort_idx + 1) % len(sort_options)
                offset = 0

    def fetch_screen(self) -> None:
        categories = ", ".join(source_categories())
        current_category = db.get_learning_category(self.conn)
        category = self.prompt(f"导入词库类别: {categories}", default=current_category)
        if not category:
            return

        try:
            category = normalize_category(category)
            if db.is_category_imported(self.conn, category):
                total = db.count_words(self.conn, category=category)
                self.message = f"{category} 词库已经导入，当前 {total} 个单词"
                return
            cached = is_ecdict_cached()
            status = "使用本地缓存词库" if cached else "首次下载远程词库"
            self.show_loading(f"{status}，正在全量导入 {category}...")
            before = db.count_words(self.conn, category=category)
            rows = iter_words_from_ecdict(category)
            scanned = db.add_words(self.conn, rows)
            after = db.count_words(self.conn, category=category)
            db.mark_category_imported(self.conn, category)
        except (RuntimeError, ValueError) as exc:
            self.message = f"导入失败: {exc}"
            return
        self.message = f"处理 {scanned} 个 {category} 单词，新增 {after - before} 个，当前 {after} 个"

    def add_word_screen(self) -> None:
        word = self.prompt("英文单词")
        if not word:
            return
        translation = self.prompt("中文释义")
        if not translation:
            self.message = "中文释义不能为空"
            return
        phonetic = self.prompt("音标，可留空")
        category = self.prompt("类别，可留空")
        try:
            tag = normalize_category(category) if category else ""
            word_id = db.add_word(
                self.conn,
                word=word,
                translation=translation,
                phonetic=phonetic,
                tags=tag,
                source="manual",
            )
        except ValueError as exc:
            self.message = str(exc)
            return
        self.message = f"已添加 {word} (id={word_id})"

    def review_screen(self) -> None:
        daily_limit = db.get_daily_word_limit(self.conn)
        learning_category = db.get_learning_category(self.conn)
        random_order = db.get_random_review_order(self.conn)
        review_mode = db.get_review_mode(self.conn)
        due_words = db.due_words(
            self.conn,
            limit=daily_limit,
            category=learning_category,
            random_order=random_order,
            skip_new=True,
        )
        if not due_words:
            self.message = f"今天没有到期的 {learning_category} 旧词需要复习"
            return

        reviewed = 0
        group_size = db.DEFAULT_REVIEW_GROUP_SIZE
        for group_start in range(0, len(due_words), group_size):
            group = due_words[group_start : group_start + group_size]
            weak_items = []
            group_no = group_start // group_size + 1
            group_count = (len(due_words) + group_size - 1) // group_size
            for item in group:
                quality = self.review_one_word(item, reviewed, len(due_words), group_no, group_count, mode=review_mode)
                if quality is None:
                    self.message = f"本次复习完成 {reviewed} 个单词"
                    return
                result = schedule_review(
                    quality=quality,
                    ease_factor=item.ease_factor,
                    interval_days=item.interval_days,
                    repetitions=item.repetitions,
                )
                db.update_review(
                    self.conn,
                    word_id=item.word_id,
                    ease_factor=result.ease_factor,
                    interval_days=result.interval_days,
                    repetitions=result.repetitions,
                    due_date=result.due_date,
                    lapsed=result.lapsed,
                )
                if quality < 3:
                    weak_items.append(item)
                reviewed += 1
            if weak_items:
                self.reinforce_weak_words(weak_items, group_no)

        self.message = f"本次复习完成 {reviewed} 个单词"

    def learn_new_screen(self) -> None:
        daily_limit = db.get_daily_word_limit(self.conn)
        learning_category = db.get_learning_category(self.conn)
        random_order = db.get_random_review_order(self.conn)
        review_mode = db.get_review_mode(self.conn)
        new_words = db.new_words(
            self.conn,
            limit=daily_limit,
            category=learning_category,
            random_order=random_order,
        )
        if not new_words:
            self.message = f"没有待学习的 {learning_category} 新词"
            return

        learned = 0
        group_size = db.DEFAULT_REVIEW_GROUP_SIZE
        total = len(new_words)
        group_count = (total + group_size - 1) // group_size

        for group_start in range(0, total, group_size):
            group = new_words[group_start : group_start + group_size]
            group_no = group_start // group_size + 1

            # Phase 1: Learn — show full details, self-assess
            for item in group:
                quality = self.learn_one_word(item, learned, total, group_no, group_count)
                if quality is None:
                    self.message = f"本次学习完成 {learned} 个新词"
                    return
                result = schedule_review(
                    quality=quality,
                    ease_factor=item.ease_factor,
                    interval_days=item.interval_days,
                    repetitions=item.repetitions,
                )
                db.update_review(
                    self.conn,
                    word_id=item.word_id,
                    ease_factor=result.ease_factor,
                    interval_days=result.interval_days,
                    repetitions=result.repetitions,
                    due_date=result.due_date,
                    lapsed=result.lapsed,
                    is_new=True,
                )
                learned += 1

            # Phase 2: Review — re-fetch updated words, test recall
            self.show_text([
                f"第 {group_no}/{group_count} 组学完！",
                "",
                f"本组 {len(group)} 个新词已学完",
                f"接下来用 {review_mode} 模式复习本组单词",
                "",
                "按 Enter 开始复习，q 跳过",
            ], wait=False)
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                continue

            # Re-fetch the same words with updated review state
            word_ids = [item.word_id for item in group]
            review_items = [
                item for item in db.due_words(
                    self.conn, limit=999, category=learning_category,
                )
                if item.word_id in set(word_ids)
            ]
            if not review_items:
                continue

            reviewed = 0
            weak_items = []
            for item in review_items:
                quality = self.review_one_word(
                    item, reviewed, len(review_items), group_no, group_count, mode=review_mode,
                )
                if quality is None:
                    break
                result = schedule_review(
                    quality=quality,
                    ease_factor=item.ease_factor,
                    interval_days=item.interval_days,
                    repetitions=item.repetitions,
                )
                db.update_review(
                    self.conn,
                    word_id=item.word_id,
                    ease_factor=result.ease_factor,
                    interval_days=result.interval_days,
                    repetitions=result.repetitions,
                    due_date=result.due_date,
                    lapsed=result.lapsed,
                )
                if quality < 3:
                    weak_items.append(item)
                reviewed += 1
            if weak_items:
                self.reinforce_weak_words(weak_items, group_no)

        self.message = f"本次学习完成 {learned} 个新词（含复习）"

    def learn_one_word(self, item: db.DueWord, learned: int, total: int, group_no: int, group_count: int) -> int | None:
        """Show full word details for learning (not recall), then ask self-assessment."""
        is_starred = self._is_word_starred(item.word_id)
        self.stdscr.erase()
        self.draw_frame(f"第 {group_no}/{group_count} 组 · 学习 {learned + 1}/{total}")
        self.draw_progress(3, 4, learned, total)
        star_mark = " ★" if is_starred else ""
        self.add_line(6, 4, f"{item.word}{star_mark}", self.theme.title)
        if item.phonetic:
            self.add_line(7, 4, f"[{item.phonetic}]", self.theme.dim)
        self.add_line(9, 4, f"释义: {item.translation}", self.theme.accent)
        if item.definition:
            self.add_line(10, 4, f"英文: {item.definition}", self.theme.dim)
        if item.pos:
            self.add_line(11, 4, f"词性: {item.pos}", self.theme.dim)
        self.add_line(13, 4, "记住后按 Enter 自评，s 收藏，q 结束学习", self.theme.dim)
        self.stdscr.refresh()
        while True:
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if key in (ord("s"), ord("S")):
                is_starred = db.toggle_star(self.conn, item.word_id)
                star_mark = " ★" if is_starred else ""
                self.add_line(6, 4, f"{item.word}{star_mark}  ", self.theme.title)
                self.stdscr.refresh()
                continue
            if key in (curses.KEY_ENTER, 10, 13):
                break

        lines = [
            f"第 {group_no}/{group_count} 组 · 学习",
            f"单词: {item.word}",
            f"音标: {item.phonetic}" if item.phonetic else "",
            "",
            f"释义: {item.translation}",
            "",
            "自评吸收程度：0 忘了 1 勉强 2 记住 3 很熟",
        ]
        while True:
            self.show_text(lines, wait=False)
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if ord("0") <= key <= ord("3"):
                # Map 0-3 to SM-2 quality 0-5
                mapping = {0: 0, 1: 2, 2: 4, 3: 5}
                return mapping[key - ord("0")]

    def spelling_screen(self) -> None:
        daily_limit = db.get_daily_word_limit(self.conn)
        learning_category = db.get_learning_category(self.conn)
        random_order = db.get_random_review_order(self.conn)
        due = db.due_words(
            self.conn,
            limit=daily_limit,
            category=learning_category,
            random_order=random_order,
        )
        if not due:
            self.message = f"今天没有到期的 {learning_category} 单词"
            return

        tested = 0
        group_size = db.DEFAULT_REVIEW_GROUP_SIZE
        for group_start in range(0, len(due), group_size):
            group = due[group_start : group_start + group_size]
            weak_items = []
            group_no = group_start // group_size + 1
            group_count = (len(due) + group_size - 1) // group_size
            for item in group:
                quality = self._spelling_one_word(item, tested, len(due), group_no, group_count)
                if quality is None:
                    self.message = f"拼写测试完成 {tested} 个单词"
                    return
                result = schedule_review(
                    quality=quality,
                    ease_factor=item.ease_factor,
                    interval_days=item.interval_days,
                    repetitions=item.repetitions,
                )
                db.update_review(
                    self.conn,
                    word_id=item.word_id,
                    ease_factor=result.ease_factor,
                    interval_days=result.interval_days,
                    repetitions=result.repetitions,
                    due_date=result.due_date,
                    lapsed=result.lapsed,
                )
                if quality < 3:
                    weak_items.append(item)
                tested += 1
            if weak_items:
                self.reinforce_weak_words(weak_items, group_no)

        self.message = f"拼写测试完成 {tested} 个单词"

    def _spelling_input(self, y: int, x: int) -> str | None:
        """Read user input character by character, return None on q/Esc."""
        curses.curs_set(1)
        buf = ""
        _, width = self.stdscr.getmaxyx()
        max_len = width - x - 2
        while True:
            self.add_line(y, x, "> " + buf + " ", curses.A_NORMAL)
            self.stdscr.move(y, x + 2 + len(buf))
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                curses.curs_set(0)
                return None
            if key in (curses.KEY_ENTER, 10, 13):
                curses.curs_set(0)
                return buf
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if buf:
                    buf = buf[:-1]
            elif 32 <= key <= 126 and len(buf) < max_len:
                buf += chr(key)

    def _spelling_one_word(self, item: db.DueWord, tested: int, total: int, group_no: int, group_count: int) -> int | None:
        """Show Chinese meaning, user types English word."""
        is_starred = self._is_word_starred(item.word_id)
        self.stdscr.erase()
        self.draw_frame(f"第 {group_no}/{group_count} 组 · 拼写 {tested + 1}/{total}")
        self.draw_progress(3, 4, tested, total)
        star_mark = " ★" if is_starred else ""
        self.add_line(6, 4, f"{item.translation}", self.theme.title)
        if item.pos:
            self.add_line(7, 4, f"({item.pos})", self.theme.dim)
        self.add_line(9, 4, "输入英文单词，按 Enter 确认，q 结束:", self.theme.dim)
        self.stdscr.refresh()

        answer = self._spelling_input(10, 4)
        if answer is None:
            return None

        correct = answer.strip().lower() == item.word.strip().lower()

        if correct:
            self.add_line(11, 4, f"正确! {item.word}", self.theme.success)
            quality = 4
        else:
            self.add_line(11, 4, f"错误! 正确答案: {item.word}", curses.color_pair(1) | curses.A_BOLD)
            self.add_line(12, 4, f"你的输入: {answer}", self.theme.dim)
            quality = 1

        if item.phonetic:
            self.add_line(14, 4, f"[{item.phonetic}]", self.theme.dim)

        self.add_line(16, 4, "按 Enter 继续，q 结束", self.theme.dim)
        self.stdscr.refresh()
        while True:
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if key in (curses.KEY_ENTER, 10, 13):
                return quality

    def review_one_word(self, item: db.DueWord, reviewed: int, total: int, group_no: int, group_count: int, mode: str = "en-cn") -> int | None:
        import random as _random
        is_starred = self._is_word_starred(item.word_id)
        actual_mode = mode
        if mode == "mixed":
            actual_mode = _random.choice(["en-cn", "cn-en"])

        if actual_mode == "cn-en":
            return self._review_cn_en(item, reviewed, total, group_no, group_count, is_starred)
        else:
            return self._review_en_cn(item, reviewed, total, group_no, group_count, is_starred)

    def _review_en_cn(self, item: db.DueWord, reviewed: int, total: int, group_no: int, group_count: int, is_starred: bool) -> int | None:
        """English word shown first, recall Chinese meaning."""
        while True:
            self.stdscr.erase()
            self.draw_frame(f"第 {group_no}/{group_count} 组 · 复习 {reviewed + 1}/{total}")
            self.draw_progress(3, 4, reviewed, total)
            star_mark = " ★" if is_starred else ""
            self.add_line(6, 4, f"{item.word}{star_mark}", self.theme.title)
            if item.phonetic:
                self.add_line(7, 4, f"[{item.phonetic}]", self.theme.dim)
            self.add_line(10, 4, "先回忆释义，按 Enter 查看答案，s 收藏，q 结束复习", self.theme.dim)
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if key in (ord("s"), ord("S")):
                is_starred = db.toggle_star(self.conn, item.word_id)
                continue
            break

        lines = [
            f"第 {group_no}/{group_count} 组",
            f"单词: {item.word}{star_mark}",
            f"音标: {item.phonetic}" if item.phonetic else "",
            "",
            f"释义: {item.translation}",
            f"英文: {item.definition}" if item.definition else "",
            f"词性: {item.pos}" if item.pos else "",
            "",
            "按 0-5 评分：0 完全忘记，5 很熟；s 收藏；q 结束复习",
        ]
        return self.ask_quality(lines)

    def _review_cn_en(self, item: db.DueWord, reviewed: int, total: int, group_no: int, group_count: int, is_starred: bool) -> int | None:
        """Chinese meaning shown first, recall English word."""
        while True:
            self.stdscr.erase()
            self.draw_frame(f"第 {group_no}/{group_count} 组 · 复习 {reviewed + 1}/{total} [中→英]")
            self.draw_progress(3, 4, reviewed, total)
            star_mark = " ★" if is_starred else ""
            self.add_line(6, 4, f"{item.translation}", self.theme.title)
            if item.pos:
                self.add_line(7, 4, f"({item.pos})", self.theme.dim)
            self.add_line(10, 4, "回忆英文单词，按 Enter 查看答案，s 收藏，q 结束复习", self.theme.dim)
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if key in (ord("s"), ord("S")):
                is_starred = db.toggle_star(self.conn, item.word_id)
                continue
            break

        lines = [
            f"第 {group_no}/{group_count} 组 [中→英]",
            f"释义: {item.translation}{star_mark}",
            "",
            f"单词: {item.word}",
            f"音标: {item.phonetic}" if item.phonetic else "",
            f"英文: {item.definition}" if item.definition else "",
            f"词性: {item.pos}" if item.pos else "",
            "",
            "按 0-5 评分：0 完全忘记，5 很熟；s 收藏；q 结束复习",
        ]
        return self.ask_quality(lines)

    def _is_word_starred(self, word_id: int) -> bool:
        row = self.conn.execute("SELECT starred FROM words WHERE id = ?", (word_id,)).fetchone()
        return bool(row["starred"]) if row else False

    def reinforce_weak_words(self, items: list[db.DueWord], group_no: int) -> None:
        for idx, item in enumerate(items, start=1):
            lines = [
                f"第 {group_no} 组错词强化 {idx}/{len(items)}",
                f"单词: {item.word}",
                f"音标: {item.phonetic}" if item.phonetic else "",
                "",
                f"释义: {item.translation}",
                f"英文: {item.definition}" if item.definition else "",
                "",
                "按任意键继续",
            ]
            self.show_text(lines)

    def ask_quality(self, lines: list[str]) -> int | None:
        while True:
            self.show_text(lines, wait=False)
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if ord("0") <= key <= ord("5"):
                return key - ord("0")

    def prompt(self, label: str, *, default: str = "") -> str:
        curses.curs_set(1)
        self.stdscr.erase()
        self.draw_frame("输入")
        self.add_line(3, 4, label, self.theme.title)
        if default:
            self.add_line(5, 4, f"默认值: {default}", self.theme.dim)
        self.add_line(7, 4, "> ")
        self.stdscr.refresh()
        curses.echo()
        try:
            raw = self.stdscr.getstr(7, 6, 200).decode("utf-8").strip()
        finally:
            curses.noecho()
            curses.curs_set(0)
        return raw or default

    def show_loading(self, text: str) -> None:
        self.stdscr.erase()
        self.draw_frame("处理中")
        self.add_line(3, 4, text, self.theme.title)
        self.stdscr.refresh()

    def show_text(self, lines: list[str], *, wait: bool = True) -> None:
        self.stdscr.erase()
        _, width = self.stdscr.getmaxyx()
        title = lines[0] if lines else ""
        self.draw_frame(title)
        row = 3
        for line in lines[1:]:
            for wrapped in wrap_line(line, width - 4):
                self.add_line(row, 4, wrapped)
                row += 1
        if wait:
            height, _ = self.stdscr.getmaxyx()
            self.add_line(height - 2, 4, "按任意键返回", self.theme.dim)
        self.stdscr.refresh()
        if wait:
            self.stdscr.getch()

    def scroll_text(self, lines: list[str]) -> None:
        offset = 0
        while True:
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            title = lines[0] if lines else "列表"
            self.draw_frame(title)
            visible: list[str] = []
            for line in lines[1:]:
                visible.extend(wrap_line(line, width - 4))
            max_offset = max(0, len(visible) - height + 5)
            offset = min(offset, max_offset)
            for idx, line in enumerate(visible[offset : offset + height - 4]):
                self.add_line(idx + 3, 4, line)
            self.add_line(height - 2, 4, "↑/↓ 滚动，PageUp/PageDown 翻页，q 返回", self.theme.dim)
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_DOWN, ord("j"), ord("J")):
                offset = min(max_offset, offset + 1)
            elif key in (curses.KEY_UP, ord("k"), ord("K")):
                offset = max(0, offset - 1)
            elif key == curses.KEY_NPAGE:
                offset = min(max_offset, offset + height - 3)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - height + 3)

    def add_line(self, y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> None:
        height, width = self.stdscr.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        try:
            self.stdscr.addnstr(y, x, text, max(0, width - x - 1), attr)
        except curses.error:
            pass

    def draw_frame(self, title: str) -> None:
        height, width = self.stdscr.getmaxyx()
        self.draw_box(0, 0, height, max(4, width - 1), f" {title} ")

    def draw_box(self, y: int, x: int, height: int, width: int, title: str = "") -> None:
        if height < 2 or width < 4:
            return
        max_y, max_x = self.stdscr.getmaxyx()
        if y >= max_y or x >= max_x:
            return
        bottom = min(y + height - 1, max_y - 1)
        right = min(x + width - 1, max_x - 2)
        horizontal = "─" * max(0, right - x - 1)
        self.add_line(y, x, f"┌{horizontal}┐", self.theme.panel)
        for row in range(y + 1, bottom):
            self.add_line(row, x, "│", self.theme.panel)
            self.add_line(row, right, "│", self.theme.panel)
        self.add_line(bottom, x, f"└{horizontal}┘", self.theme.panel)
        if title:
            self.add_line(y, x + 2, title[: max(0, right - x - 3)], self.theme.title)

    def draw_status(self, height: int, width: int) -> None:
        text = f" {self.message} "
        self.add_line(height - 2, 3, text[: max(0, width - 6)], self.theme.success)

    def draw_progress(self, y: int, x: int, current: int, total: int) -> None:
        _, width = self.stdscr.getmaxyx()
        bar_width = min(40, max(10, width - x - 12))
        filled = round(bar_width * current / max(1, total))
        bar = "█" * filled + "░" * (bar_width - filled)
        self.add_line(y, x, f"{bar} {current}/{total}", self.theme.accent)

    def draw_labeled_progress(self, y: int, x: int, label: str, current: int, total: int) -> None:
        _, width = self.stdscr.getmaxyx()
        bar_width = min(28, max(8, width - x - len(label) - 16))
        filled = round(bar_width * current / max(1, total))
        bar = "█" * filled + "░" * (bar_width - filled)
        percent = 0 if total <= 0 else round(current * 100 / total)
        self.add_line(y, x, f"{label}: {bar} {percent}% ({current}/{total})", self.theme.accent)


def wrap_line(line: str, width: int) -> list[str]:
    if not line:
        return [""]
    if width <= 4:
        return [line[: max(1, width)]]
    return textwrap.wrap(line, width=width, replace_whitespace=False) or [""]


def run_tui(conn: Connection) -> None:
    def _run(stdscr: curses.window) -> None:
        TuiApp(stdscr, conn).run()

    curses.wrapper(_run)
