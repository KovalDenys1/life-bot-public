"""
Daily note creation, planning injection, and workout schedule.
"""
from datetime import datetime, timedelta
from config import LOCAL_TZ, GYM_REF
from services.github_service import read_file, write_file


def get_workout_type(date=None) -> str:
    """Returns 'gym' or 'abs' for the given date."""
    if date is None:
        date = datetime.now(LOCAL_TZ).date()
    elif hasattr(date, 'date'):
        date = date.date()
    delta = (date - GYM_REF).days
    return "gym" if delta % 2 == 0 else "abs"


def get_today_note_path() -> str:
    now = datetime.now(LOCAL_TZ)
    return f"01 Daily/{now.year}/{now.month:02d}/{now.strftime('%Y-%m-%d')}.md"


def get_weekly_priorities() -> list[str]:
    content = read_file("05 Planned.md") or ""
    priorities = []
    in_section = False
    for line in content.splitlines():
        if line.startswith("# 🎯 Weekly Priorities"):
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break
            if line.startswith("- [ ] ") or line.startswith("- [x] "):
                task = line[6:].strip()
                if task:
                    priorities.append(task)
    return priorities[:3]


def get_planned_tasks_for_date(date_str: str) -> list[tuple[str, str]]:
    content = read_file("05 Planned.md") or ""
    tasks = []
    for line in content.splitlines():
        if line.startswith(f"| {date_str}"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[2]:
                tasks.append((parts[2], parts[3]))
    return tasks


def remove_planned_tasks_for_date(date_str: str) -> None:
    content = read_file("05 Planned.md") or ""
    lines = [l for l in content.splitlines() if not l.startswith(f"| {date_str}")]
    updated = "\n".join(lines)
    if updated != content:
        write_file("05 Planned.md", updated, f"Inject planned tasks for {date_str}")


def ensure_month_note(now: datetime) -> None:
    month_str = now.strftime("%Y-%m")
    month_path = f"01 Daily/{now.year}/{now.month:02d}/{month_str}.md"
    if read_file(month_path):
        return
    days_in_month = (
        datetime(now.year, now.month % 12 + 1, 1) - timedelta(days=1)
    ).day if now.month < 12 else 31
    day_links = []
    for week_start in range(1, days_in_month + 1, 5):
        week_days = [
            f"[[{month_str}-{d:02d}]]"
            for d in range(week_start, min(week_start + 5, days_in_month + 1))
        ]
        day_links.append(" - ".join(week_days))
    content = f"""---
type: month
month: {now.strftime('%B %Y')}
---

# 📅 {now.strftime('%B %Y')}

## Daily Notes
{chr(10).join('- ' + line for line in day_links)}
"""
    write_file(month_path, content, f"Create month note {month_str}")


def create_daily_note() -> str:
    now = datetime.now(LOCAL_TZ)
    today_str = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    workout_type = get_workout_type(now)
    workout_line = (
        "- [ ] 🏋️ Gym session (with friends)"
        if workout_type == "gym"
        else "- [ ] 🌅 Morning abs + warm-up"
    )

    ensure_month_note(now)

    planned = get_planned_tasks_for_date(today_str)
    planned_lines = "\n".join(f"- [ ] 📅 {task}" for task, _ in planned)

    weekly = get_weekly_priorities()
    priority_lines = "\n".join(f"- [ ] {p}" for p in weekly) if weekly else "- [ ] \n- [ ] \n- [ ] "

    return f"""---
date: {now.strftime('%Y-%m-%d')}
display: {now.strftime('%d.%m.%Y')}
day: {now.strftime('%A')}
week: W{now.isocalendar()[1]:02d}
type: daily
---

# {now.strftime('%A, %d %B %Y')}

## 🎯 Top 3 Priorities
{priority_lines}

---

## 📋 Tasks

### 💼 Work
- [ ] Work on Boardly (daily habit)
- [ ]

### 🏠 Personal
{planned_lines if planned_lines else "- [ ]"}

### 🔄 Habits
{workout_line}
- [ ] Boardly — work on project
- [ ] Read (10 pages minimum)
- [ ] English (15 min)
- [ ] Norwegian (15 min)
- [ ] 💊 Creatine (5g)
- [ ] Coding (30 min minimum)
- [ ] ⏰ Wake up by 06:00
- [ ] 🧴 Morning skincare
- [ ] 🌙 Evening skincare
- [ ] In bed by 23:00

---

## 🌅 Morning Check-in
⚡ Energy: —
😊 Mood: —
🎯 Intention: —

---

## 📝 Notes & Log


---

## 🌙 Evening Reflection
**What went well:**
-

**What didn't go as planned:**
-

**One thing to improve tomorrow:**
>

**Grateful for:**
-

---
[[{now.strftime('%Y-%m')}|📅 {now.strftime('%B %Y')}]]  |  *[[{yesterday}|← Yesterday]]*  |  *[[{tomorrow}|Tomorrow →]]*
"""
