"""
Habit tracking: streaks, water, reading, and direct habit handlers.
"""
import re
import logging
from datetime import datetime, timedelta
from threading import Lock
from config import LOCAL_TZ
from services.github_service import read_file, write_file
from vault.daily_note import get_today_note_path, create_daily_note, get_workout_type

logger = logging.getLogger(__name__)

_water_lock = Lock()

ATOMIC_HABITS_PAGES = 320

TRACKED_HABITS = [
    ("workout", None),
    ("boardly", ["Boardly", "boardly"]),
    ("reading", ["Read (10 pages", "Read ("]),
    ("english", ["English (15"]),
    ("norwegian", ["Norwegian (15"]),
    ("creatine", ["Creatine (5g)", "💊 Creatine"]),
    ("coding", ["Coding (30"]),
    ("skincare_morning", ["🧴 Morning skincare"]),
    ("skincare_evening", ["🌙 Evening skincare"]),
    ("sleep", ["In bed by 23"]),
    ("wakeup", ["⏰ Wake up by 06", "Wake up by 06"]),
]

WORKOUT_KEYWORDS = {
    "gym": ["Gym session"],
    "abs": ["Morning abs"],
}

HABIT_LABELS = {
    "workout": "🏋️ Workout",
    "boardly": "💻 Boardly",
    "reading": "📚 Reading",
    "english": "🇬🇧 English",
    "norwegian": "🇳🇴 Norwegian",
    "creatine": "💊 Creatine",
    "coding": "👨‍💻 Coding",
    "skincare_morning": "🧴 AM Skincare",
    "skincare_evening": "🌙 PM Skincare",
    "sleep": "😴 Sleep by 23:00",
    "wakeup": "⏰ Wake up 6:00",
}


# ── Streak calculation ─────────────────────────────────────────────────────────

def calculate_streaks(days: int = 14) -> dict:
    now = datetime.now(LOCAL_TZ)
    results = {habit: {"streak": 0, "done_days": [], "total": 0} for habit, _ in TRACKED_HABITS}

    daily_data = []
    for i in range(days):
        day = now - timedelta(days=i)
        path = f"01 Daily/{day.year}/{day.month:02d}/{day.strftime('%Y-%m-%d')}.md"
        daily_data.append((day, read_file(path)))

    for habit, keywords in TRACKED_HABITS:
        streak = total = 0
        done_days = []
        streak_broken = False

        for idx, (day, content) in enumerate(daily_data):
            is_today = (idx == 0)
            if not content:
                if not streak_broken and streak > 0 and not is_today:
                    streak_broken = True
                continue

            kws = WORKOUT_KEYWORDS[get_workout_type(day)] if habit == "workout" else keywords
            completed = any(
                any(f"- [x]" in line and kw in line or f"- [X]" in line and kw in line
                    for line in content.splitlines())
                for kw in kws
            )

            if completed:
                total += 1
                done_days.append(day.strftime("%Y-%m-%d"))
                if not streak_broken:
                    streak += 1
            elif not streak_broken and not is_today:
                streak_broken = True

        results[habit]["streak"] = streak
        results[habit]["total"] = total
        results[habit]["done_days"] = done_days

    return results


def format_streaks(streaks: dict, days: int = 14) -> str:
    lines = [f"<b>🔥 Habit Streaks (last {days} days)</b>\n"]
    for habit, data in streaks.items():
        label = HABIT_LABELS.get(habit, habit)
        streak = data["streak"]
        total = data["total"]
        fire = "🔥" if streak >= 3 else ("✅" if streak >= 1 else "❌")
        lines.append(f"{fire} {label}: <b>{streak} day streak</b> ({total}/{days} days)")

    best = max(streaks.items(), key=lambda x: x[1]["streak"])
    if best[1]["streak"] >= 2:
        lines.append(f"\n⭐ Best streak: <b>{HABIT_LABELS.get(best[0], best[0])}</b> — {best[1]['streak']} days")

    return "\n".join(lines)


# ── Water ──────────────────────────────────────────────────────────────────────

def get_water_count(note_content: str) -> int:
    for line in note_content.splitlines():
        if line.startswith("**Water:**"):
            try:
                return int(line.split("**Water:**")[1].strip().split("/")[0])
            except (ValueError, IndexError):
                return 0
    return 0


def get_water_streak() -> int:
    now = datetime.now(LOCAL_TZ)
    streak = 0
    for i in range(1, 30):
        day = now - timedelta(days=i)
        path = f"01 Daily/{day.year}/{day.month:02d}/{day.strftime('%Y-%m-%d')}.md"
        content = read_file(path)
        if not content:
            break
        if get_water_count(content) >= 8:
            streak += 1
        else:
            break
    return streak


def cmd_water(note_content: str) -> str:
    count = get_water_count(note_content)
    goal = 8
    filled = min(count, goal)
    bar = "💧" * filled + "⬜" * (goal - filled)
    pct = round(count / goal * 100)
    streak = get_water_streak()
    streak_text = f"\n🔥 <b>{streak} day streak</b>" if streak >= 2 else ""
    return f"💧 <b>Water today: {count}/{goal} glasses</b>\n{bar}\n{pct}% of daily goal{streak_text}"


def handle_habit_water() -> str:
    with _water_lock:
        return _handle_habit_water_locked()


def _handle_habit_water_locked() -> str:
    note_path = get_today_note_path()
    note = read_file(note_path) or ""
    if not note:
        write_file(note_path, create_daily_note(), "Create daily note")
        note = read_file(note_path) or ""

    count = get_water_count(note) + 1
    goal = 8

    water_line = next((l for l in note.splitlines() if "**Water:**" in l), None)
    if water_line is not None:
        lines = [f"**Water:** {count}/{goal}" if "**Water:**" in l else l for l in note.splitlines()]
        updated = "\n".join(lines)
    else:
        updated = note.rstrip() + f"\n\n**Water:** {count}/{goal}"

    write_file(note_path, updated, "Water +1")

    filled = min(count, goal)
    bar = "💧" * filled + "⬜" * (goal - filled)
    return f"💧 <b>Water: {count}/{goal}</b>\n{bar}"


# ── Habit checkbox ─────────────────────────────────────────────────────────────

def handle_habit_check(habit_keyword: str, label: str) -> str:
    note_path = get_today_note_path()
    note = read_file(note_path) or ""
    if not note:
        write_file(note_path, create_daily_note(), "Create daily note")
        note = read_file(note_path) or ""

    lines = note.splitlines()
    changed = False
    for i, line in enumerate(lines):
        if habit_keyword in line and "- [ ]" in line:
            lines[i] = line.replace("- [ ]", "- [x]", 1)
            changed = True
            break

    if changed:
        write_file(note_path, "\n".join(lines), f"Habit done: {label}")
        return f"✅ <b>{label}</b> logged for today!"
    else:
        return f"✅ <b>{label}</b> — already marked or not found in today's note."


# ── Reading ────────────────────────────────────────────────────────────────────

def get_reading_progress() -> int:
    pg = read_file("02 Areas/Personal Growth.md") or ""
    for line in pg.splitlines():
        if "Atomic Habits" in line and "Pages read:" in line:
            try:
                return int(line.split("Pages read:")[1].strip().split("/")[0])
            except (ValueError, IndexError):
                pass
    return 0


def cmd_reading() -> str:
    total = get_reading_progress()
    remaining = max(0, ATOMIC_HABITS_PAGES - total)
    pct = round(total / ATOMIC_HABITS_PAGES * 100)
    days_left = max(1, remaining // 10)
    bar_filled = min(20, round(pct / 5))
    bar = "📗" * bar_filled + "⬜" * (20 - bar_filled)
    return (
        f"📚 <b>Atomic Habits</b>\n"
        f"{bar}\n"
        f"<b>{total}/{ATOMIC_HABITS_PAGES} pages</b> ({pct}%)\n"
        f"~{days_left} days left at 10 pages/day"
    )


def handle_habit_reading() -> str:
    note_path = get_today_note_path()
    note = read_file(note_path) or ""
    if not note:
        write_file(note_path, create_daily_note(), "Create daily note")
        note = read_file(note_path) or ""

    lines = note.splitlines()
    for i, line in enumerate(lines):
        if "Read (10 pages" in line and "- [ ]" in line:
            lines[i] = line.replace("- [ ]", "- [x]", 1)
            break

    has_read_log = any("**Read:**" in l for l in lines)
    if has_read_log:
        for i, line in enumerate(lines):
            if "**Read:**" in line:
                try:
                    existing = int(line.split("**Read:**")[1].strip().split(" ")[0])
                except (ValueError, IndexError):
                    existing = 0
                lines[i] = f"**Read:** {existing + 10} pages"
                break
    else:
        lines.append("**Read:** 10 pages")

    write_file(note_path, "\n".join(lines), "Reading +10 pages")

    pg = read_file("02 Areas/Personal Growth.md") or ""
    total = 0
    for line in pg.splitlines():
        if "Atomic Habits" in line and "Pages read:" in line:
            try:
                total = int(line.split("Pages read:")[1].strip().split("/")[0])
            except (ValueError, IndexError):
                pass
    total += 10
    remaining = max(0, ATOMIC_HABITS_PAGES - total)
    pct = round(total / ATOMIC_HABITS_PAGES * 100)

    pg_updated = re.sub(r"Pages read: \d+/\d+", f"Pages read: {total}/{ATOMIC_HABITS_PAGES}", pg)
    if pg_updated != pg:
        write_file("02 Areas/Personal Growth.md", pg_updated, f"Reading: {total}/{ATOMIC_HABITS_PAGES} pages")

    return f"📚 <b>+10 pages logged!</b>\n<b>{total}/{ATOMIC_HABITS_PAGES}</b> total ({pct}%) — {remaining} pages left"
