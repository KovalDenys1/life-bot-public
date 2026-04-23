"""
Saved meals parsing, one-tap logging, and weekly meal plan generation.
"""
import re
import random
import logging
from datetime import datetime, timedelta
from config import LOCAL_TZ
from services.github_service import read_file, write_file
from vault.daily_note import get_today_note_path, create_daily_note, get_workout_type

logger = logging.getLogger(__name__)

MEALS_PER_PAGE = 6

BREAKFASTS = ["Oatmeal Bowl", "YT Yoghurt + Granola", "4 Eggs + Cherry Tomatoes + Cheese"]
LUNCHES_DINNERS = [
    "Chicken + Rice + Avocado", "Pasta + Chicken + Cheese",
    "Spaghetti + Salmon + Spinach", "Spaghetti + Shrimp + Cream + Cheddar",
    "Pasta Bolognese", "Salmon + Rice + Avocado",
]


def get_saved_meals() -> list:
    """Parse Saved Meals table from Nutrition.md. Returns list of (name, kcal, protein, carbs, fat)."""
    content = read_file("02 Areas/Nutrition.md") or ""
    meals = []
    in_section = False
    for line in content.splitlines():
        if "## 🍽 Saved Meals" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("| ") and "---" not in line and "| Meal" not in line:
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 5 and parts[0]:
                name = parts[0].strip("[]")
                meals.append((name, parts[1], parts[2], parts[3], parts[4]))
    return meals


def get_today_food_totals(note_content: str):
    """Parse 🍽 food lines from daily note and sum macros."""
    totals = {"kcal": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    meal_list = []
    for line in note_content.splitlines():
        if line.strip().startswith("- 🍽"):
            match = re.search(
                r'(\d+)\s*kcal\s*/\s*(\d+\.?\d*)\s*g?\s*P\s*/\s*(\d+\.?\d*)\s*g?\s*C\s*/\s*(\d+\.?\d*)\s*g?\s*F',
                line
            )
            if match:
                kcal = int(match.group(1))
                p, c, f = float(match.group(2)), float(match.group(3)), float(match.group(4))
                totals["kcal"] += kcal
                totals["protein"] += p
                totals["carbs"] += c
                totals["fat"] += f
                name_match = re.search(r'🍽\s*(.+?)\s*—', line)
                name = name_match.group(1).strip() if name_match else "Unknown"
                meal_list.append((name, kcal, p, c, f))
    return totals, meal_list


def append_food_to_note(note_path: str, food_line: str) -> bool:
    note = read_file(note_path)
    if not note:
        return False
    lines = note.splitlines()
    insert_at = len(lines)
    in_notes = False
    for i, line in enumerate(lines):
        if "## 📝 Notes & Log" in line:
            in_notes = True
            continue
        if in_notes and (line.startswith("## ") or line.strip() == "---"):
            insert_at = i
            break
    lines.insert(insert_at, food_line)
    write_file(note_path, "\n".join(lines), f"Log food: {food_line[:50]}")
    return True


def cmd_log_saved_meal(index: int) -> str:
    meals = get_saved_meals()
    if index >= len(meals):
        return "⚠️ Meal not found."
    name, kcal, protein, carbs, fat = meals[index]

    note_path = get_today_note_path()
    if not read_file(note_path):
        write_file(note_path, create_daily_note(), "Create daily note")

    food_line = f"- 🍽 {name} — {kcal} kcal / {protein} P / {carbs} C / {fat} F"
    append_food_to_note(note_path, food_line)

    note = read_file(note_path) or ""
    totals, meal_list = get_today_food_totals(note)

    remaining_kcal = 2900 - totals["kcal"]
    remaining_p = round(140 - totals["protein"])
    remaining_c = round(450 - totals["carbs"])
    remaining_f = round(60 - totals["fat"])

    lines = [f"✅ <b>Logged:</b> {name}\n", "<code>"]
    lines.append(f"{'Meal':<22} {'kcal':>4}  {'P':>4}  {'C':>4}  {'F':>4}")
    lines.append("─" * 44)
    for m_name, m_kcal, m_p, m_c, m_f in meal_list:
        lines.append(f"{m_name[:22]:<22} {m_kcal:>4}  {m_p:>3}g  {m_c:>3}g  {m_f:>3}g")
    lines.append("─" * 44)
    lines.append(f"{'Total':<22} {totals['kcal']:>4}  {round(totals['protein']):>3}g  {round(totals['carbs']):>3}g  {round(totals['fat']):>3}g")
    lines.append(f"{'Target':<22} {'2900':>4}  {'140':>3}g  {'450':>3}g  {'60':>3}g")
    lines.append(f"{'Remaining':<22} {remaining_kcal:>4}  {remaining_p:>3}g  {remaining_c:>3}g  {remaining_f:>3}g")
    lines.append("</code>")
    return "\n".join(lines)


def generate_weekly_meal_plan() -> str:
    """Generate a random weekly meal plan, save to vault, return Telegram message."""
    meals_data = get_saved_meals()
    macros = {name: int(kcal) for name, kcal, *_ in meals_data}

    now = datetime.now(LOCAL_TZ)
    days_until_monday = (7 - now.weekday()) % 7 or 7
    next_monday = now + timedelta(days=days_until_monday)
    week_days = [next_monday + timedelta(days=i) for i in range(7)]
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    oatmeal_count = random.randint(4, 5)
    other_breakfasts = [b for b in BREAKFASTS if b != "Oatmeal Bowl"]
    breakfasts = ["Oatmeal Bowl"] * oatmeal_count + random.choices(other_breakfasts, k=7 - oatmeal_count)
    random.shuffle(breakfasts)

    used_lunches: list[str] = []
    used_dinners: list[str] = []
    lunches, dinners = [], []
    for i in range(7):
        lunch_pool = [m for m in LUNCHES_DINNERS if m not in used_lunches[-2:]] or LUNCHES_DINNERS.copy()
        lunch = random.choice(lunch_pool)
        lunches.append(lunch)
        used_lunches.append(lunch)

        dinner_pool = [m for m in LUNCHES_DINNERS if m != lunch and m not in used_dinners[-2:]]
        if not dinner_pool:
            dinner_pool = [m for m in LUNCHES_DINNERS if m != lunch]
        dinner = random.choice(dinner_pool)
        dinners.append(dinner)
        used_dinners.append(dinner)

    table_rows = []
    total_kcal = 0
    for i, day in enumerate(week_days):
        wtype = get_workout_type(day)
        emoji = "🏋️" if wtype == "gym" else "💪"
        snack = "YT Melk + Banana" if wtype == "gym" else "Banana"
        day_kcal = macros.get(breakfasts[i], 0) + macros.get(lunches[i], 0) + macros.get(dinners[i], 0) + 105
        total_kcal += day_kcal
        table_rows.append(
            f"| **{DAY_NAMES[i]}** {emoji} | [[{breakfasts[i]}]] | [[{lunches[i]}]] | [[{dinners[i]}]] | {snack} |"
        )

    avg_kcal = total_kcal // 7
    week_num = next_monday.isocalendar()[1]
    date_range = f"{next_monday.strftime('%b %d')} – {(next_monday + timedelta(days=6)).strftime('%b %d')}"

    md_content = f"""---
type: area
area: nutrition
updated: {now.strftime('%Y-%m-%d')}
---

# 🗓 Weekly Meal Plan

> Gym days = more carbs around workout. Add snacks to hit 2900 kcal.

---

## 📅 Week {week_num} ({date_range})

| Day | Breakfast | Lunch | Dinner | Snacks |
|-----|-----------|-------|--------|--------|
{chr(10).join(table_rows)}

---

## 📊 Weekly Macros (avg per day)

| | Target | Estimated |
|-|--------|-----------|
| kcal | 2900 | ~{avg_kcal} |
| Protein | 140g | — |
| Carbs | 450g | — |
| Fat | 60g | — |

> To hit 2900 kcal — add 1 extra fruit or snack on days you feel hungry.
"""

    write_file("02 Areas/Weekly Meal Plan.md", md_content, f"Meal plan W{week_num}")

    msg_lines = [f"🗓 <b>Meal Plan W{week_num}</b> ({date_range})\n"]
    for i, day in enumerate(week_days):
        wtype = get_workout_type(day)
        emoji = "🏋️" if wtype == "gym" else "💪"
        msg_lines.append(f"<b>{DAY_NAMES[i]}</b> {emoji} {breakfasts[i]} / {lunches[i]} / {dinners[i]}")
    msg_lines.append(f"\n📊 Est. avg: ~{avg_kcal} kcal/day")
    return "\n".join(msg_lines)
