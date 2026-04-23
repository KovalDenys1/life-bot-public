"""
Life Bot — Flask entry point.
All business logic lives in services/, vault/, ai/, ui/.
"""
import os
import re
import logging
import threading
from datetime import datetime, timedelta
from threading import Lock

import telebot
from flask import Flask, request, jsonify

import user_profile as p
from config import bot, CHAT_ID, WEBHOOK_SECRET, LOCAL_TZ
from services.cost_tracker import load_cost, get_daily_cost, get_weekly_cost_summary
from services.weather import get_oslo_weather_daily, get_oslo_weather
from services.github_service import read_file, write_file
from vault.daily_note import (
    get_today_note_path, create_daily_note, remove_planned_tasks_for_date, get_workout_type
)
from vault.habits import (
    calculate_streaks, format_streaks, cmd_water, cmd_reading,
    handle_habit_water, handle_habit_check, handle_habit_reading,
)
from vault.meals import generate_weekly_meal_plan, cmd_log_saved_meal, get_saved_meals
from vault.finance import handle_csv_import, handle_statement_import, cmd_finance
from vault.context import VAULT_FILES
from ai.client import call_ai, process_quick_question
from ai.processor import process_message, analyze_photo, transcribe_voice
from ui.keyboards import get_menu_keyboard, get_habits_keyboard, get_meals_keyboard, get_boardly_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Debounce buffer ────────────────────────────────────────────────────────────

DEBOUNCE_DELAY = 2.0
_msg_buffer: dict[int, list[str]] = {}
_msg_timers: dict[int, threading.Timer] = {}
_msg_lock = Lock()
_haiku_mode: set[int] = set()


def sanitize_html(text: str) -> str:
    return re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)


def safe_answer_cq(cq_id: str, text: str = "", show_alert: bool = False) -> None:
    try:
        bot.answer_callback_query(cq_id, text=text, show_alert=show_alert)
    except Exception as e:
        logger.warning(f"answer_callback_query failed: {e}")


def flush_messages(chat_id: int) -> None:
    with _msg_lock:
        messages = _msg_buffer.pop(chat_id, [])
        _msg_timers.pop(chat_id, None)
    if not messages:
        return
    combined = "\n".join(messages)
    bot.send_message(chat_id, "⏳ Thinking...")
    reply = process_message(combined, chat_id=chat_id)
    bot.send_message(chat_id, sanitize_html(reply), parse_mode="HTML")


def enqueue_message(chat_id: int, text: str) -> None:
    with _msg_lock:
        _msg_buffer.setdefault(chat_id, []).append(text)
        if chat_id in _msg_timers:
            _msg_timers[chat_id].cancel()
        timer = threading.Timer(DEBOUNCE_DELAY, flush_messages, args=[chat_id])
        timer.daemon = True
        timer.start()
        _msg_timers[chat_id] = timer


# ── Command handlers ───────────────────────────────────────────────────────────

def cmd_today() -> str:
    today = read_file(get_today_note_path())
    if not today:
        return "📅 No note for today yet. Write something and it will be created automatically."
    return call_ai(
        system="You are a personal assistant. Respond in English. Use Telegram HTML only: <b>bold</b>, <i>italic</i>, <code>blocks</code>. NEVER use markdown.",
        user=f"""Summarize today's plan from this daily note. Rules:
- SKIP tasks that are completely empty (just "- [ ]" or "- [x]" with nothing after)
- Show only tasks that have actual text
- Completed tasks (- [x]): use ✅, group under <b>🏁 Completed</b>
- Pending tasks (- [ ]): group under <b>📋 Still to do</b>
- Habits go in a separate <b>🔄 Habits</b> section
- Be concise

{today}""",
        max_tokens=500,
    )


def cmd_health() -> str:
    health = read_file("02 Areas/Health.md") or ""
    return call_ai(
        system="You are a personal assistant. Respond in English. Use Telegram HTML only.",
        user=f"Give a brief health status summary. Show goals, current sleep schedule, fitness routine. Use emojis:\n\n{health}",
        max_tokens=400,
    )


def cmd_macros() -> str:
    from vault.meals import get_today_food_totals
    today_note = read_file(get_today_note_path()) or ""
    if not today_note:
        return "📅 No note for today yet."

    totals, meal_list = get_today_food_totals(today_note)
    if not meal_list:
        return "🍽 No food logged today yet."

    remaining_kcal = 2900 - totals["kcal"]
    remaining_p = round(140 - totals["protein"])
    remaining_c = round(450 - totals["carbs"])
    remaining_f = round(60 - totals["fat"])

    lines = ["🍽 <b>Today's Nutrition</b>\n", "<code>"]
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


def cmd_week() -> str:
    now = datetime.now(LOCAL_TZ)
    notes = []
    for i in range(7):
        day = now - timedelta(days=i)
        path = f"01 Daily/{day.year}/{day.month:02d}/{day.strftime('%Y-%m-%d')}.md"
        content = read_file(path)
        if content:
            notes.append(f"=== {day.strftime('%A %d %b')} ===\n{content[:600]}")
    if not notes:
        return "📊 No notes found for the last 7 days."
    return call_ai(
        system="You are a personal assistant. Respond in English. Use Telegram HTML only.",
        user="Give a brief weekly summary: what was done, habits completed, what to improve. Use emojis:\n\n" + "\n\n".join(notes),
        max_tokens=600,
    )


def cmd_search(query: str) -> str:
    if not query:
        return "🔍 Usage: <code>/search your query</code>"
    all_files = VAULT_FILES + [get_today_note_path()]
    now = datetime.now(LOCAL_TZ)
    parts = []
    for path in all_files:
        content = read_file(path)
        if content:
            parts.append(f"=== FILE: {path} ===\n{content}")
    for i in range(1, 14):
        day = now - timedelta(days=i)
        path = f"01 Daily/{day.year}/{day.month:02d}/{day.strftime('%Y-%m-%d')}.md"
        content = read_file(path)
        if content:
            parts.append(f"=== FILE: {path} ===\n{content}")
    return call_ai(
        system="You are a personal knowledge assistant. Respond in English. Use HTML formatting for Telegram.",
        user=f'Search through the vault for: "{query}"\nFind all relevant mentions. Show file name in bold and a short excerpt.\n\n' + "\n\n".join(parts),
        max_tokens=800,
    )


def get_boardly_stats(period_hours: int = 24) -> str:
    db_url = os.environ.get("BOARDLY_DATABASE_URL", "")
    if not db_url:
        return ""
    try:
        import psycopg2
        import psycopg2.extras
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed = urlparse(db_url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        for key in ("pgbouncer", "statement_cache_size", "connection_limit", "pool_timeout"):
            qs.pop(key, None)
        clean_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
        conn = psycopg2.connect(clean_url, connect_timeout=10)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        since = datetime.now(LOCAL_TZ) - timedelta(hours=period_hours)

        cur.execute('SELECT COUNT(*) AS cnt FROM "Users" WHERE "isGuest" = false AND "createdAt" >= %s', (since,))
        new_real = cur.fetchone()["cnt"]
        cur.execute('SELECT COUNT(*) AS cnt FROM "Users" WHERE "isGuest" = true AND "createdAt" >= %s', (since,))
        new_guests = cur.fetchone()["cnt"]
        cur.execute('SELECT COUNT(*) AS cnt FROM "Games" WHERE "startedAt" >= %s', (since,))
        games_started = cur.fetchone()["cnt"]
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'finished') AS finished,
                COUNT(*) FILTER (WHERE status = 'abandoned') AS abandoned,
                COUNT(*) FILTER (WHERE status IN ('finished','abandoned','cancelled')) AS total_ended,
                AVG("durationSeconds") FILTER (WHERE status = 'finished' AND "durationSeconds" IS NOT NULL) AS avg_dur
            FROM "Games" WHERE "endedAt" >= %s
        """, (since,))
        row = cur.fetchone()
        finished = row["finished"] or 0
        abandoned = row["abandoned"] or 0
        total_ended = row["total_ended"] or 0
        avg_dur = row["avg_dur"]
        cur.execute('SELECT "gameType", COUNT(*) AS cnt FROM "Games" WHERE "startedAt" >= %s GROUP BY "gameType" ORDER BY cnt DESC LIMIT 3', (since,))
        top_games = cur.fetchall()
        cur.close()
        conn.close()

        lines = ["\n📊 <b>Boardly (last 24h)</b>"]
        lines.append(f"👥 New users: <b>{new_real}</b> real + <b>{new_guests}</b> guests")
        lines.append(f"🎮 Games started: <b>{games_started}</b>")
        if total_ended > 0:
            lines.append(f"✅ Finished: <b>{finished}</b> ({int(finished/total_ended*100)}%)   💀 Abandoned: <b>{abandoned}</b> ({int(abandoned/total_ended*100)}%)")
        if avg_dur:
            lines.append(f"⏱ Avg game: <b>{int(avg_dur // 60)} min</b>")
        if top_games:
            lines.append("🏆 Top: " + ",  ".join(f"{r['gameType'].replace('_',' ').title()} ({r['cnt']})" for r in top_games))
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Boardly stats error: {type(e).__name__}")
        return ""


def cmd_boardly() -> str:
    stats = get_boardly_stats(24)
    return stats.strip() if stats else "⚠️ Boardly DB unavailable."


def cmd_boardly_status() -> str:
    content = read_file("03 Projects/Boardly.md")
    return f"📋 <b>Boardly Status</b>\n\n{content[:1500].strip()}" if content else "⚠️ Boardly.md not found."


def cmd_boardly_ideas() -> str:
    content = read_file("03 Projects/Boardly Ideas.md")
    return f"💡 <b>Boardly Ideas</b>\n\n{content[:1500].strip()}" if content else "⚠️ Boardly Ideas.md not found."


def cmd_streaks() -> str:
    return format_streaks(calculate_streaks(14), 14)


def generate_morning_plan() -> str:
    now = datetime.now(LOCAL_TZ)
    weather = get_oslo_weather_daily()
    boardly = read_file("03 Projects/Boardly.md") or ""
    today_note = read_file(get_today_note_path()) or ""
    priorities = ""
    if today_note and "Top 3 Priorities" in today_note:
        priorities = today_note.split("Top 3 Priorities")[1].split("##")[0].strip()

    return call_ai(
        system=f"You are a personal assistant for {p.NAME}. Respond in English. Use Telegram HTML only: <b>bold</b>, <i>italic</i>, <code>blocks</code>. NEVER use markdown.",
        user=f"""Write a morning briefing for {p.NAME}. Today is {now.strftime('%A, %B %d')}.

Weather: {weather}
Today's priorities: {priorities or 'Not set yet'}
Boardly: {boardly[:200]}

Include:
1. ☀️ One energetic greeting + weather summary
2. ✅ Habit checklist (workout/Boardly/reading/english/norwegian/sleep)
3. 🎯 Top focus for today
4. 💬 Phrase of the day — advanced B2-C1 English phrase (not common idioms). Format: 🇬🇧 <b>phrase</b> — meaning → 🇳🇴 norsk → 🇷🇺 русский
5. 🌅 Morning check-in — ask energy/mood/intention/bedtime in one message

Keep it concise and motivating.""",
        max_tokens=700,
    )


def generate_weekly_report() -> str:
    now = datetime.now(LOCAL_TZ)
    week_num = now.isocalendar()[1]
    daily_notes = []
    for i in range(7):
        day = now - timedelta(days=i)
        path = f"01 Daily/{day.year}/{day.month:02d}/{day.strftime('%Y-%m-%d')}.md"
        content = read_file(path)
        if content:
            daily_notes.append(f"=== {day.strftime('%A %b %d')} ===\n{content[:800]}")

    streaks = calculate_streaks(7)
    habit_labels = {
        "workout": "🏋️ Workout", "boardly": "💻 Boardly", "reading": "📚 Reading",
        "english": "🇬🇧 English", "norwegian": "🇳🇴 Norwegian", "sleep": "😴 Sleep",
        "wakeup": "⏰ Wake up 6:00",
    }
    streak_lines = [
        f"{'🔥' if d['total'] >= 5 else '✅' if d['total'] >= 3 else '❌'} {habit_labels.get(h, h)}: {d['total']}/7 days"
        for h, d in streaks.items() if h in habit_labels
    ]

    finance = read_file("02 Areas/Finance.md") or ""
    boardly = read_file("03 Projects/Boardly.md") or ""

    return call_ai(
        system="You are a personal life coach. Respond in English. Use HTML formatting for Telegram. Be concise but insightful.",
        user=f"""Generate a weekly review for {p.NAME} for Week {week_num}.

HABIT COMPLETION:
{chr(10).join(streak_lines)}

DAILY NOTES (last 7 days):
{chr(10).join(daily_notes) if daily_notes else 'No daily notes this week.'}

FINANCE:
{finance[-600:]}

BOARDLY:
{boardly[:400]}

Write a structured review:
1. <b>Week {week_num} Summary</b> — 2-3 sentences
2. <b>🔥 Habits</b> — consistent vs needs work
3. <b>💼 Work & Projects</b> — Boardly progress
4. <b>💰 Finance</b> — brief note if data available
5. <b>🎯 Focus for Next Week</b> — 3 specific priorities

Under 300 words. Be direct and motivating.""",
        max_tokens=700,
    )


def generate_friday_summary() -> str:
    now = datetime.now(LOCAL_TZ)
    daily_notes = []
    for i in range(5):
        day = now - timedelta(days=i)
        if day.weekday() > 4:
            continue
        path = f"01 Daily/{day.year}/{day.month:02d}/{day.strftime('%Y-%m-%d')}.md"
        content = read_file(path)
        if content:
            daily_notes.append(f"=== {day.strftime('%A %b %d')} ===\n{content[:600]}")

    streaks = calculate_streaks(5)
    habit_labels = {
        "workout": "🏋️ Workout", "boardly": "💻 Boardly", "reading": "📚 Reading",
        "english": "🇬🇧 English", "norwegian": "🇳🇴 Norwegian", "sleep": "😴 Sleep",
        "wakeup": "⏰ Wake up 6:00",
    }
    streak_lines = [
        f"{'🔥' if d['total'] >= 4 else '✅' if d['total'] >= 2 else '❌'} {habit_labels.get(h, h)}: {d['total']}/5 days"
        for h, d in streaks.items() if h in habit_labels
    ]

    return call_ai(
        system=f"You are {p.NAME}'s personal coach. Respond in English. Use Telegram HTML only.",
        user=f"""It's Friday! Write a warm, motivating end-of-week message for {p.NAME}.

HABITS (Mon-Fri):
{chr(10).join(streak_lines)}

DAILY NOTES:
{chr(10).join(daily_notes) if daily_notes else 'No notes found.'}

Structure:
1. 🎉 Warm congratulations — school week done, energetic
2. 📊 Quick stats — what went well
3. ⚠️ One thing to improve next week (honest but supportive)
4. 🏖 Weekend reminder — rest is important

Concise, friendly, like a coach who knows him well.""",
        max_tokens=600,
    )


def send_evening_reminder() -> None:
    today = read_file(get_today_note_path()) or ""
    boardly_mentioned = "boardly" in today.lower()
    total_cost, cost_breakdown = get_daily_cost()

    lines = ["🌙 <b>Evening check-in</b>\n", "⏰ Time to wind down — be in bed by 23:00!"]
    if not boardly_mentioned:
        lines.append("\n⚠️ You haven't worked on <b>Boardly</b> today. Got 15 minutes?")
    lines.append(
        "\n📝 <b>Evening reflection — answer these 3 questions:</b>\n"
        "1️⃣ What went well today?\n"
        "2️⃣ What didn't go as planned?\n"
        "3️⃣ What are you grateful for?\n\n"
        "Just reply naturally — I'll save it to your vault."
    )
    lines.append(f"\n💸 <b>Today's API cost:</b>\n{cost_breakdown}")
    boardly_block = get_boardly_stats(24)
    if boardly_block:
        lines.append(boardly_block)
    bot.send_message(CHAT_ID, "\n".join(lines), parse_mode="HTML", reply_markup=get_menu_keyboard())


# ── Webhook ────────────────────────────────────────────────────────────────────

MENU_TEXT = (
    "💸 <b>AI</b> — Today, Health, Macros, Finance, Quick Ask\n"
    "⚡ <b>Free</b> — Streaks, Water, Reading, Habits\n"
    "🍽 <b>Meals</b> — quick log from saved menu\n"
    "💻 <b>Boardly</b> — Stats, Status, Ideas"
)


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"ok": True})

    update = telebot.types.Update.de_json(data)

    # ── Callback queries ───────────────────────────────────────────────────────
    if update.callback_query:
        cq = update.callback_query
        if cq.message.chat.id != CHAT_ID:
            return jsonify({"ok": True})
        cmd = cq.data
        is_habit = cmd.startswith("habit_")

        AI_COMMANDS = {"today", "health", "macros", "finance", "week"}
        if cmd in AI_COMMANDS:
            safe_answer_cq(cq.id, text="⏳ Loading...")
            bot.send_message(CHAT_ID, "⏳ Working on it...")
        elif is_habit:
            safe_answer_cq(cq.id, text="✅ Logged!")
        else:
            safe_answer_cq(cq.id)

        reply = None

        if cmd == "back_menu":
            try:
                bot.edit_message_text(chat_id=CHAT_ID, message_id=cq.message.message_id,
                    text=MENU_TEXT, parse_mode="HTML", reply_markup=get_menu_keyboard())
            except Exception:
                bot.send_message(CHAT_ID, MENU_TEXT, parse_mode="HTML", reply_markup=get_menu_keyboard())
            return jsonify({"ok": True})

        elif cmd == "quick_ask":
            _haiku_mode.add(CHAT_ID)
            bot.send_message(CHAT_ID, "💬 <b>Quick Ask</b> — type your question:", parse_mode="HTML")
            return jsonify({"ok": True})

        elif cmd == "today":    reply = cmd_today()
        elif cmd == "health":   reply = cmd_health()
        elif cmd == "macros":   reply = cmd_macros()
        elif cmd == "streaks":  reply = cmd_streaks()
        elif cmd == "week":     reply = cmd_week()
        elif cmd == "finance":  reply = cmd_finance()
        elif cmd == "water":
            today = read_file(get_today_note_path()) or ""
            reply = cmd_water(today)
        elif cmd == "reading":  reply = cmd_reading()

        elif cmd == "meals_menu":
            meals = get_saved_meals()
            if not meals:
                bot.send_message(CHAT_ID, "⚠️ No saved meals yet.", parse_mode="HTML")
            else:
                try:
                    bot.edit_message_text(chat_id=CHAT_ID, message_id=cq.message.message_id,
                        text="🍽 <b>Saved Meals</b> — tap to log:", parse_mode="HTML",
                        reply_markup=get_meals_keyboard(0))
                except Exception:
                    bot.send_message(CHAT_ID, "🍽 <b>Saved Meals</b> — tap to log:",
                        parse_mode="HTML", reply_markup=get_meals_keyboard(0))
            return jsonify({"ok": True})

        elif cmd.startswith("meals_page_"):
            try:
                page = int(cmd[len("meals_page_"):])
                bot.edit_message_reply_markup(chat_id=CHAT_ID, message_id=cq.message.message_id,
                    reply_markup=get_meals_keyboard(page))
            except Exception:
                pass
            return jsonify({"ok": True})

        elif cmd == "noop":
            return jsonify({"ok": True})

        elif cmd.startswith("meal_log_"):
            try:
                index = int(cmd[len("meal_log_"):])
                from vault.meals import MEALS_PER_PAGE
                reply_text = cmd_log_saved_meal(index)
                try:
                    bot.edit_message_text(
                        chat_id=CHAT_ID, message_id=cq.message.message_id,
                        text=f"🍽 <b>Saved Meals</b>\n{reply_text}",
                        parse_mode="HTML", reply_markup=get_meals_keyboard(index // MEALS_PER_PAGE)
                    )
                except Exception:
                    bot.send_message(CHAT_ID, reply_text, parse_mode="HTML", reply_markup=get_meals_keyboard(0))
            except (ValueError, IndexError):
                bot.send_message(CHAT_ID, "⚠️ Invalid meal.", parse_mode="HTML")
            return jsonify({"ok": True})

        elif cmd == "boardly_menu":
            try:
                bot.edit_message_text(chat_id=CHAT_ID, message_id=cq.message.message_id,
                    text="💻 <b>Boardly</b>", parse_mode="HTML", reply_markup=get_boardly_keyboard())
            except Exception:
                bot.send_message(CHAT_ID, "💻 <b>Boardly</b>", parse_mode="HTML", reply_markup=get_boardly_keyboard())
            return jsonify({"ok": True})

        elif cmd == "boardly_stats":  reply = cmd_boardly()
        elif cmd == "boardly_status": reply = cmd_boardly_status()
        elif cmd == "boardly_ideas":  reply = cmd_boardly_ideas()

        elif cmd == "habits":
            note_path = get_today_note_path()
            if not read_file(note_path):
                today_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
                write_file(note_path, create_daily_note(), "Create daily note")
                remove_planned_tasks_for_date(today_str)
            safe_answer_cq(cq.id)
            try:
                bot.edit_message_text(chat_id=CHAT_ID, message_id=cq.message.message_id,
                    text="✅ <b>Habits</b> — tap to log:", parse_mode="HTML",
                    reply_markup=get_habits_keyboard())
            except Exception:
                bot.send_message(CHAT_ID, "✅ <b>Habits</b> — tap to log:",
                    parse_mode="HTML", reply_markup=get_habits_keyboard())
            return jsonify({"ok": True})

        elif cmd == "habit_water":   reply = handle_habit_water()
        elif cmd == "habit_workout":
            wtype = get_workout_type()
            reply = handle_habit_check("Gym session", "Gym session") if wtype == "gym" \
                else handle_habit_check("Morning abs", "Morning abs + warm-up")
        elif cmd == "habit_boardly":          reply = handle_habit_check("Boardly", "Boardly session")
        elif cmd == "habit_reading":          reply = handle_habit_reading()
        elif cmd == "habit_english":          reply = handle_habit_check("English (15", "English practice")
        elif cmd == "habit_norwegian":        reply = handle_habit_check("Norwegian (15", "Norwegian practice")
        elif cmd == "habit_creatine":         reply = handle_habit_check("Creatine", "Creatine 💊")
        elif cmd == "habit_coding":           reply = handle_habit_check("Coding (30", "Coding session 👨‍💻")
        elif cmd == "habit_skincare_morning": reply = handle_habit_check("🧴 Morning skincare", "Morning skincare 🧴")
        elif cmd == "habit_skincare_evening": reply = handle_habit_check("🌙 Evening skincare", "Evening skincare 🌙")
        elif cmd == "habit_wakeup":           reply = handle_habit_check("Wake up by 06", "Wake up by 06:00 ⏰")
        else:
            reply = "Unknown command"
            is_habit = False

        if reply is None:
            return jsonify({"ok": True})

        if is_habit:
            try:
                bot.edit_message_text(
                    chat_id=CHAT_ID, message_id=cq.message.message_id,
                    text=f"✅ <b>Habits</b>\n{reply}", parse_mode="HTML",
                    reply_markup=get_habits_keyboard()
                )
            except Exception:
                bot.send_message(CHAT_ID, reply, parse_mode="HTML", reply_markup=get_habits_keyboard())
        else:
            bot.send_message(CHAT_ID, reply, parse_mode="HTML", reply_markup=get_menu_keyboard())

        return jsonify({"ok": True})

    # ── Regular messages ───────────────────────────────────────────────────────
    if not update.message:
        return jsonify({"ok": True})
    if update.message.chat.id != CHAT_ID:
        return jsonify({"ok": True})

    if update.message.photo:
        photo = update.message.photo[-1]
        bot.send_message(CHAT_ID, "🔍 Analyzing photo...")
        reply = analyze_photo(photo.file_id, update.message.caption or "")
        bot.send_message(CHAT_ID, reply, parse_mode="HTML")
        return jsonify({"ok": True})

    if update.message.voice:
        bot.send_message(CHAT_ID, "🎙 Transcribing...")
        text = transcribe_voice(update.message.voice.file_id)
        if not text:
            bot.send_message(CHAT_ID, "⚠️ Could not transcribe. Check Whisper/OpenAI key.")
            return jsonify({"ok": True})
        bot.send_message(CHAT_ID, f"📝 <i>Heard: {text}</i>", parse_mode="HTML")
        bot.send_message(CHAT_ID, "⏳ Thinking...")
        reply = process_message(text, chat_id=CHAT_ID)
        bot.send_message(CHAT_ID, reply, parse_mode="HTML")
        return jsonify({"ok": True})

    if update.message.document:
        doc = update.message.document
        fname = doc.file_name or ""
        if (doc.file_size or 0) > 20 * 1024 * 1024:
            bot.send_message(CHAT_ID, "⚠️ File is too large (max 20 MB).", parse_mode="HTML")
            return jsonify({"ok": True})
        if fname.endswith((".csv", ".xlsx", ".xls")):
            bot.send_message(CHAT_ID, "⏳ Importing transactions...")
            reply = handle_csv_import(doc.file_id, fname)
            bot.send_message(CHAT_ID, reply, parse_mode="HTML")
        elif fname.endswith((".pdf", ".txt")):
            bot.send_message(CHAT_ID, "⏳ Reading statement…")
            reply = handle_statement_import(doc.file_id, fname)
            bot.send_message(CHAT_ID, reply, parse_mode="HTML")
        else:
            bot.send_message(CHAT_ID, "⚠️ Send a DNB or Revolut export as <b>.csv</b>, <b>.xlsx</b>, <b>.pdf</b>, or <b>.txt</b>.", parse_mode="HTML")
        return jsonify({"ok": True})

    if not update.message.text:
        return jsonify({"ok": True})

    text = update.message.text

    if text == "/today":
        bot.send_message(CHAT_ID, cmd_today(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/week":
        bot.send_message(CHAT_ID, cmd_week(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/health":
        bot.send_message(CHAT_ID, cmd_health(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/macros":
        bot.send_message(CHAT_ID, cmd_macros(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/streaks":
        bot.send_message(CHAT_ID, cmd_streaks(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/water":
        today = read_file(get_today_note_path()) or ""
        bot.send_message(CHAT_ID, cmd_water(today), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/reading":
        bot.send_message(CHAT_ID, cmd_reading(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text.startswith("/search"):
        bot.send_message(CHAT_ID, cmd_search(text[7:].strip()), parse_mode="HTML"); return jsonify({"ok": True})
    elif text == "/finance":
        bot.send_message(CHAT_ID, cmd_finance(), parse_mode="HTML"); return jsonify({"ok": True})
    elif text in ("/menu", "/start"):
        bot.send_message(CHAT_ID, MENU_TEXT, parse_mode="HTML", reply_markup=get_menu_keyboard()); return jsonify({"ok": True})
    elif text == "/habits":
        bot.send_message(CHAT_ID, "✅ <b>Habits</b> — tap to log:", parse_mode="HTML", reply_markup=get_habits_keyboard()); return jsonify({"ok": True})
    elif text == "/boardly":
        bot.send_message(CHAT_ID, cmd_boardly(), parse_mode="HTML"); return jsonify({"ok": True})

    if update.message.reply_to_message and update.message.reply_to_message.text:
        prev = update.message.reply_to_message.text[:400]
        text = f"[Correcting your previous response: \"{prev}\"]\n{text}"

    if CHAT_ID in _haiku_mode:
        _haiku_mode.discard(CHAT_ID)
        reply = process_quick_question(text)
        bot.send_message(CHAT_ID, reply, parse_mode="HTML", reply_markup=get_menu_keyboard())
        return jsonify({"ok": True})

    enqueue_message(CHAT_ID, text)
    return jsonify({"ok": True})


@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"ok": True}), 200


# ── Cron routes ────────────────────────────────────────────────────────────────

def _check_secret(req) -> bool:
    secret = req.headers.get("X-Cron-Secret", "")
    return secret == WEBHOOK_SECRET


@app.route("/morning", methods=["GET", "POST"])
def morning():
    if not _check_secret(request):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        note_path = get_today_note_path()
        today_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
        if not read_file(note_path):
            write_file(note_path, create_daily_note(), "Morning: create daily note")
            remove_planned_tasks_for_date(today_str)
        bot.send_message(CHAT_ID, generate_morning_plan(), parse_mode="HTML")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Morning cron error: {e}", exc_info=True)
        return jsonify({"ok": True}), 200


@app.route("/evening", methods=["GET", "POST"])
def evening():
    if not _check_secret(request):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        send_evening_reminder()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Evening cron error: {e}", exc_info=True)
        return jsonify({"ok": True}), 200


@app.route("/weekly-report", methods=["GET", "POST"])
def weekly_report():
    if not _check_secret(request):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        bot.send_message(CHAT_ID, generate_weekly_meal_plan(), parse_mode="HTML")
        bot.send_message(CHAT_ID, generate_weekly_report(), parse_mode="HTML", reply_markup=get_menu_keyboard())
        weekly_costs = get_weekly_cost_summary()
        if weekly_costs:
            bot.send_message(CHAT_ID, weekly_costs, parse_mode="HTML")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Weekly report cron error: {e}", exc_info=True)
        return jsonify({"ok": True}), 200


@app.route("/friday", methods=["GET", "POST"])
def friday():
    if not _check_secret(request):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        bot.send_message(CHAT_ID, generate_friday_summary(), parse_mode="HTML", reply_markup=get_menu_keyboard())
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Friday cron error: {e}", exc_info=True)
        return jsonify({"ok": True}), 200


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})


@app.route("/debug", methods=["GET"])
def debug():
    if not _check_secret(request):
        return jsonify({"error": "Unauthorized"}), 403
    results = {}
    try:
        from services.github_service import get_repo
        contents = get_repo().get_contents("")
        results["github"] = f"OK — {len(contents)} files in root"
    except Exception as e:
        results["github"] = f"ERROR: {e}"
    try:
        content = read_file("02 Areas/Health.md")
        results["read_file"] = f"OK — {len(content)} chars" if content else "File not found"
    except Exception as e:
        results["read_file"] = f"ERROR: {e}"
    try:
        from config import anthropic_client as ac
        ac.messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[{"role": "user", "content": "hi"}])
        results["anthropic"] = "OK"
    except Exception as e:
        results["anthropic"] = f"ERROR: {e}"
    try:
        results["telegram"] = f"OK — @{bot.get_me().username}"
    except Exception as e:
        results["telegram"] = f"ERROR: {e}"
    return jsonify(results)


@app.route("/set-webhook", methods=["GET"])
def set_webhook():
    if not _check_secret(request):
        return jsonify({"error": "Unauthorized"}), 403
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    webhook_url = f"{render_url}/webhook"
    bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
    bot.set_my_description(
        "Your personal life assistant. Tell me anything — what you ate, how you slept, what you did — and I'll organize it in your Obsidian vault."
    )
    bot.set_my_short_description("AI life assistant connected to your Obsidian vault")
    commands = [
        telebot.types.BotCommand("menu",    "📋 Open menu"),
        telebot.types.BotCommand("habits",  "✅ Log habits"),
        telebot.types.BotCommand("streaks", "🔥 Habit streaks — last 14 days"),
        telebot.types.BotCommand("water",   "💧 Water intake today"),
        telebot.types.BotCommand("reading", "📚 Reading progress"),
        telebot.types.BotCommand("today",   "📅 Today's plan (AI)"),
        telebot.types.BotCommand("macros",  "🥗 Nutrition totals today (AI)"),
        telebot.types.BotCommand("health",  "🏃 Health & sleep status (AI)"),
        telebot.types.BotCommand("finance", "💰 Monthly spending (AI)"),
        telebot.types.BotCommand("week",    "📊 Weekly summary (AI)"),
        telebot.types.BotCommand("search",  "🔍 Search vault (AI)"),
        telebot.types.BotCommand("boardly", "📊 Boardly stats (last 24h)"),
    ]
    bot.set_my_commands(commands)
    return jsonify({"ok": True, "webhook": webhook_url})


# ── Startup ────────────────────────────────────────────────────────────────────
load_cost()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
