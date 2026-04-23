"""
Message processor: validates Claude's file_updates, applies patch/append/update,
handles photos and voice.
"""
import json
import re
import logging
import tempfile
import os
import requests
from datetime import datetime

import user_profile as p
from config import LOCAL_TZ, bot, TELEGRAM_TOKEN, anthropic_client, openai_client
from services.github_service import read_file, write_file
from services.cost_tracker import get_history, save_history, track_claude, track_whisper
from vault.daily_note import get_today_note_path, create_daily_note, remove_planned_tasks_for_date
from vault.context import load_context
from vault.finance import update_budget_actuals
from ai.client import call_ai
from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# ── Path validation ────────────────────────────────────────────────────────────

_ALLOWED_PREFIXES = (
    "01 Daily/",
    "02 Areas/",
    "03 Projects/",
    "04 Ideas/",
    "05 Planned.md",
)
_BLOCKED_PATHS = {"00 Meta/cost_log.json"}
_VALID_ACTIONS = {"append", "update", "patch"}


def _validate_update(op: dict) -> str | None:
    """Return an error string if the update op is invalid, else None."""
    path   = op.get("path", "")
    action = op.get("action", "append")

    if not path or ".." in path or path.startswith("/"):
        return f"invalid path: {path!r}"
    if path in _BLOCKED_PATHS:
        return f"bot-managed path, refusing write: {path}"
    if not any(path.startswith(p) for p in _ALLOWED_PREFIXES):
        return f"path outside allowed vault folders: {path}"
    if action not in _VALID_ACTIONS:
        return f"unknown action: {action!r}"
    if action == "append" and not op.get("content"):
        return "append with empty content"
    if action == "update" and not op.get("content"):
        return "update with empty content"
    if action == "patch" and not op.get("find"):
        return "patch missing 'find'"
    return None


# ── Apply file updates ─────────────────────────────────────────────────────────

def _apply_updates(updates: list[dict]) -> None:
    for op in updates:
        err = _validate_update(op)
        if err:
            logger.warning(f"Skipping file_update — {err}: {op}")
            continue

        path    = op["path"]
        action  = op.get("action", "append")
        content = op.get("content", "")

        if action == "patch":
            find    = op.get("find", "")
            replace = op.get("replace", "")
            current = read_file(path) or ""
            if find not in current:
                logger.warning(f"patch: {find!r} not found in {path}, skipping")
                continue
            updated = current.replace(find, replace, 1)
            if path == "02 Areas/Finance.md":
                updated = update_budget_actuals(updated)
            write_file(path, updated, f"Patch {path}")

        elif action == "update":
            final = update_budget_actuals(content) if path == "02 Areas/Finance.md" else content
            write_file(path, final, f"Update {path}")

        else:  # append
            # Food log lines (- 🍽 ...) must go inside "📝 Notes & Log", not at EOF
            if content.strip().startswith("- 🍽") and path.startswith("01 Daily/"):
                from vault.meals import append_food_to_note
                append_food_to_note(path, content.strip())
            else:
                current = read_file(path) or ""
                separator = "\n" if content.strip().startswith("|") else "\n\n"
                new_content = current.rstrip() + separator + content
                if path == "02 Areas/Finance.md":
                    new_content = update_budget_actuals(new_content)
                write_file(path, new_content, f"Update {path}")


# ── JSON helpers ───────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning(f"Could not parse JSON. First 200 chars: {text[:200]}")
    return {"reply": "⚠️ Something went wrong — the response was malformed. Please try again.", "file_updates": []}


# ── Main message processor ─────────────────────────────────────────────────────

def process_message(text: str, chat_id: int | None = None) -> str:
    vault_context = load_context(text)
    history = get_history(chat_id) if chat_id else []
    user_msg = f"Current vault:\n\n{vault_context}\n\n---\n\n{p.NAME} says: {text}"

    try:
        raw = call_ai(
            system=SYSTEM_PROMPT,
            user=user_msg,
            history=history,
            max_tokens=2500,
            prefill="{",
        )
        result = extract_json(raw)
        reply = result.get("reply", "Done.")

        if result.get("create_daily_note"):
            note_path = get_today_note_path()
            if not read_file(note_path):
                today_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
                write_file(note_path, create_daily_note(), "Create daily note")
                remove_planned_tasks_for_date(today_str)

        _apply_updates(result.get("file_updates", []))

        if chat_id is not None:
            save_history(chat_id, text, raw)

        return reply

    except Exception as e:
        logger.error(f"process_message error: {e}", exc_info=True)
        return f"⚠️ Error: <code>{type(e).__name__}: {e}</code>"


# ── Photo analysis ─────────────────────────────────────────────────────────────

def analyze_photo(file_id: str, caption: str = "") -> str:
    import base64
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        img_response = requests.get(url, timeout=30)

        ext = file_info.file_path.split(".")[-1].lower() if "." in file_info.file_path else "jpg"
        media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
        image_data = base64.standard_b64encode(img_response.content).decode("utf-8")

        today_note = read_file(get_today_note_path()) or ""
        now = datetime.now(LOCAL_TZ)
        user_note = f'\n\n{p.NAME} also says: "{caption}"' if caption else ""

        ai_response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=f"""You are a nutrition assistant for {p.NAME}.
CRITICAL: Respond ONLY in English.
Daily macro targets: {p.KCAL_TARGET} kcal / {p.PROTEIN_G}g protein / {p.CARBS_G}g carbs / {p.FAT_G}g fat.
Use HTML formatting for Telegram. No markdown.
Always respond with raw JSON only (no code blocks): {{"reply": "...", "file_updates": [...]}}""",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": f"""Today: {now.strftime('%Y-%m-%d')}{user_note}

Today's daily note:
{today_note[-1500:]}

If this is a food/drink label: extract macros per serving, append to today's note under "📝 Notes & Log":
- 🍽 [description] — [kcal] kcal / [X]g P / [X]g C / [X]g F

Then sum all 🍽 lines and include in reply."""}
                ],
            }]
        )

        raw = ai_response.content[0].text.strip()
        track_claude(ai_response.usage.input_tokens, ai_response.usage.output_tokens)
        result = extract_json(raw)

        if result.get("create_daily_note"):
            note_path = get_today_note_path()
            if not read_file(note_path):
                today_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
                write_file(note_path, create_daily_note(), "Create daily note")
                remove_planned_tasks_for_date(today_str)

        _apply_updates(result.get("file_updates", []))
        return result.get("reply", "Done.")

    except Exception as e:
        logger.error(f"Photo analysis error: {e}", exc_info=True)
        return f"⚠️ Photo analysis error: <code>{type(e).__name__}: {e}</code>"


# ── Voice transcription ────────────────────────────────────────────────────────

def transcribe_voice(file_id: str) -> str | None:
    if not openai_client:
        return None
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        response = requests.get(url, timeout=30)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",
            )

        duration = len(response.content) // 16000
        track_whisper(max(duration, 5))
        os.unlink(tmp_path)
        return transcript.text

    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        return None
