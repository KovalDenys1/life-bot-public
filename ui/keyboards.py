"""
All Telegram InlineKeyboardMarkup builders.
"""
import telebot.types as tg
from vault.daily_note import get_today_note_path, get_workout_type
from vault.habits import get_water_count
from vault.meals import get_saved_meals, MEALS_PER_PAGE
from services.github_service import read_file


def get_menu_keyboard() -> tg.InlineKeyboardMarkup:
    keyboard = tg.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        tg.InlineKeyboardButton("📅 Today",    callback_data="today"),
        tg.InlineKeyboardButton("🏃 Health",   callback_data="health"),
        tg.InlineKeyboardButton("🥗 Macros",   callback_data="macros"),
        tg.InlineKeyboardButton("💰 Finance",  callback_data="finance"),
        tg.InlineKeyboardButton("💬 Quick Ask",callback_data="quick_ask"),
        tg.InlineKeyboardButton("🔥 Streaks",  callback_data="streaks"),
        tg.InlineKeyboardButton("💧 Water",    callback_data="water"),
        tg.InlineKeyboardButton("📚 Reading",  callback_data="reading"),
        tg.InlineKeyboardButton("✅ Habits",   callback_data="habits"),
        tg.InlineKeyboardButton("🍽 Meals",    callback_data="meals_menu"),
        tg.InlineKeyboardButton("💻 Boardly",  callback_data="boardly_menu"),
    )
    return keyboard


def get_boardly_keyboard() -> tg.InlineKeyboardMarkup:
    keyboard = tg.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        tg.InlineKeyboardButton("📊 Stats",  callback_data="boardly_stats"),
        tg.InlineKeyboardButton("📋 Status", callback_data="boardly_status"),
        tg.InlineKeyboardButton("💡 Ideas",  callback_data="boardly_ideas"),
    )
    keyboard.row(tg.InlineKeyboardButton("🔙 Menu", callback_data="back_menu"))
    return keyboard


def get_meals_keyboard(page: int = 0) -> tg.InlineKeyboardMarkup:
    meals = get_saved_meals()
    total = len(meals)
    total_pages = max(1, (total + MEALS_PER_PAGE - 1) // MEALS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * MEALS_PER_PAGE
    page_meals = meals[start:start + MEALS_PER_PAGE]

    keyboard = tg.InlineKeyboardMarkup(row_width=1)
    for i, (name, kcal, protein, carbs, fat) in enumerate(page_meals):
        label = f"🍽 {name} — {kcal} kcal / {protein} P"
        keyboard.add(tg.InlineKeyboardButton(label, callback_data=f"meal_log_{start + i}"))

    nav = []
    if page > 0:
        nav.append(tg.InlineKeyboardButton("◀️", callback_data=f"meals_page_{page - 1}"))
    if total_pages > 1:
        nav.append(tg.InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(tg.InlineKeyboardButton("▶️", callback_data=f"meals_page_{page + 1}"))
    if nav:
        keyboard.row(*nav)

    keyboard.row(tg.InlineKeyboardButton("🔙 Menu", callback_data="back_menu"))
    return keyboard


def get_habits_keyboard() -> tg.InlineKeyboardMarkup:
    note = read_file(get_today_note_path()) or ""

    def done(keyword) -> bool:
        keywords = keyword if isinstance(keyword, list) else [keyword]
        for line in note.splitlines():
            if "- [x]" in line or "- [X]" in line:
                for kw in keywords:
                    if kw in line:
                        return True
        return False

    water = get_water_count(note)
    water_label = f"💧 {water}/8 (+1)"

    wtype = get_workout_type()
    if wtype == "gym":
        workout_done = done("Gym session")
        workout_label = "✅ Gym" if workout_done else "🏋️ Gym"
    else:
        workout_done = done("Morning abs")
        workout_label = "✅ Abs" if workout_done else "🌅 Abs"

    def lbl(emoji: str, name: str, keyword) -> str:
        return f"✅ {name}" if done(keyword) else f"{emoji} {name}"

    keyboard = tg.InlineKeyboardMarkup()
    keyboard.row(
        tg.InlineKeyboardButton(water_label, callback_data="habit_water"),
        tg.InlineKeyboardButton(workout_label, callback_data="habit_workout"),
    )
    keyboard.row(
        tg.InlineKeyboardButton(lbl("💻", "Boardly",   "Boardly"),           callback_data="habit_boardly"),
        tg.InlineKeyboardButton(lbl("📚", "+10 Pages", "Read (10 pages"),    callback_data="habit_reading"),
    )
    keyboard.row(
        tg.InlineKeyboardButton(lbl("🇬🇧", "English",   "English (15"),       callback_data="habit_english"),
        tg.InlineKeyboardButton(lbl("🇳🇴", "Norwegian", "Norwegian (15"),     callback_data="habit_norwegian"),
    )
    keyboard.row(
        tg.InlineKeyboardButton(lbl("💊", "Creatine", "Creatine"),           callback_data="habit_creatine"),
        tg.InlineKeyboardButton(lbl("👨‍💻", "Coding",   "Coding (30"),         callback_data="habit_coding"),
    )
    keyboard.row(
        tg.InlineKeyboardButton(lbl("🧴", "AM Skin", "🧴 Morning skincare"), callback_data="habit_skincare_morning"),
        tg.InlineKeyboardButton(lbl("🌙", "PM Skin", "🌙 Evening skincare"), callback_data="habit_skincare_evening"),
    )
    keyboard.row(
        tg.InlineKeyboardButton(lbl("⏰", "Wake 6:00", "Wake up by 06"),     callback_data="habit_wakeup"),
    )
    keyboard.row(tg.InlineKeyboardButton("🔙 Menu", callback_data="back_menu"))
    return keyboard
