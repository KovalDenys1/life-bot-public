"""
API cost tracking + chat history persistence via GitHub JSON.
Saves are async and debounced (3 s) — multiple rapid calls produce one commit.
"""
import json
import time
import threading
import logging
from threading import Lock
from datetime import datetime, timedelta
import user_profile as p
from config import LOCAL_TZ
from services.github_service import read_file, write_file

logger = logging.getLogger(__name__)

_COST_LOG_PATH = "00 Meta/cost_log.json"
HISTORY_MAX = 3  # exchanges to keep per chat

_cost_tracker: dict = {
    "date": "", "claude_in": 0, "claude_out": 0,
    "gpt_in": 0, "gpt_out": 0, "whisper_sec": 0,
}
_weekly_cost_log: dict = {}
_chat_history: dict[int, list[dict]] = {}

_save_pending = False
_save_lock = Lock()


def _today_str() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def load_cost() -> None:
    """Load cost tracker + chat history from GitHub on startup."""
    try:
        raw = read_file(_COST_LOG_PATH)
        if not raw:
            return
        data = json.loads(raw)
        today = _today_str()
        daily = data.get("daily", {})
        if daily.get("date") == today:
            _cost_tracker.update(daily)
        else:
            _cost_tracker.update({
                "date": today, "claude_in": 0, "claude_out": 0,
                "gpt_in": 0, "gpt_out": 0, "whisper_sec": 0,
            })
        _weekly_cost_log.update(data.get("weekly", {}))
        for chat_id_str, hist in data.get("chat_history", {}).items():
            _chat_history[int(chat_id_str)] = hist
    except Exception:
        pass


def _save_cost_to_github() -> None:
    """Schedule a background save. Debounced: multiple calls within 3 s → one commit."""
    global _save_pending
    with _save_lock:
        if _save_pending:
            return
        _save_pending = True

    def _do_save():
        global _save_pending
        time.sleep(3)
        _save_pending = False
        try:
            payload = json.dumps({
                "daily": dict(_cost_tracker),
                "weekly": _weekly_cost_log,
                "chat_history": {str(k): v for k, v in _chat_history.items()},
            }, indent=2)
            write_file(_COST_LOG_PATH, payload, "Cost tracker update")
        except Exception as e:
            logger.error(f"Cost save failed: {e}")

    threading.Thread(target=_do_save, daemon=True).start()


def _reset_if_new_day() -> None:
    if _cost_tracker["date"] != _today_str():
        _cost_tracker.update({
            "date": _today_str(), "claude_in": 0, "claude_out": 0,
            "gpt_in": 0, "gpt_out": 0, "whisper_sec": 0,
        })


def track_claude(input_tokens: int, output_tokens: int) -> None:
    _reset_if_new_day()
    _cost_tracker["claude_in"] += input_tokens
    _cost_tracker["claude_out"] += output_tokens
    _save_cost_to_github()


def track_openai(input_tokens: int, output_tokens: int) -> None:
    _reset_if_new_day()
    _cost_tracker["gpt_in"] += input_tokens
    _cost_tracker["gpt_out"] += output_tokens
    _save_cost_to_github()


def track_whisper(duration_seconds: int) -> None:
    _reset_if_new_day()
    _cost_tracker["whisper_sec"] += duration_seconds
    _save_cost_to_github()


def _save_daily_to_weekly(date_str: str, total: float) -> None:
    _weekly_cost_log[date_str] = round(total, 6)
    _save_cost_to_github()


def get_daily_cost() -> tuple[float, str]:
    t = _cost_tracker
    claude_cost  = (t["claude_in"] * 3 + t["claude_out"] * 15) / 1_000_000
    gpt_cost     = (t["gpt_in"] * 2.5 + t["gpt_out"] * 10) / 1_000_000
    whisper_cost = (t["whisper_sec"] / 60) * 0.006
    total = claude_cost + gpt_cost + whisper_cost

    _save_daily_to_weekly(_today_str(), total)

    breakdown = (
        f"<code>"
        f"Claude    ${claude_cost:.4f}  ({t['claude_in'] + t['claude_out']:,} tokens)\n"
        f"GPT-4o    ${gpt_cost:.4f}  ({t['gpt_in'] + t['gpt_out']:,} tokens)\n"
        f"Whisper   ${whisper_cost:.4f}  ({t['whisper_sec']}s audio)\n"
        f"──────────────────────\n"
        f"Total     ${total:.4f}"
        f"</code>"
    )
    return total, breakdown


def get_weekly_cost_summary() -> str:
    if not _weekly_cost_log:
        return ""
    now = datetime.now(LOCAL_TZ)
    week_total = 0.0
    lines = []
    for i in range(7):
        day = now - timedelta(days=i)
        d = day.strftime("%Y-%m-%d")
        cost = _weekly_cost_log.get(d, 0.0)
        week_total += cost
        lines.append(f"{day.strftime('%a %d.%m')}   ${cost:.4f}")
    lines.reverse()
    return (
        f"<b>💸 API costs this week:</b>\n"
        f"<code>{''.join(f'{l}{chr(10)}' for l in lines)}"
        f"──────────────────\n"
        f"Total      ${week_total:.4f}</code>"
    )


def get_history(chat_id: int) -> list[dict]:
    return _chat_history.get(chat_id, [])


def save_history(chat_id: int, user_text: str, raw_response: str) -> None:
    hist = _chat_history.setdefault(chat_id, [])
    hist.append({"role": "user", "content": f"{p.NAME} says: {user_text}"})
    hist.append({"role": "assistant", "content": raw_response})
    _chat_history[chat_id] = hist[-(HISTORY_MAX * 2):]
