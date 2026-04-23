"""
Global configuration and client initialization.
Import from here everywhere — single source of truth.
"""
import os
import datetime
import pytz
import telebot
import anthropic
from openai import OpenAI
from github import Github
import user_profile as p

# ── Env vars ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_KEY"]
GITHUB_TOKEN     = os.environ["GITHUB_TOKEN"]
GITHUB_REPO      = os.environ["GITHUB_REPO"]
CHAT_ID          = int(os.environ["CHAT_ID"])
OPENAI_KEY       = os.environ.get("OPENAI_KEY", "")
WEBHOOK_SECRET   = os.environ["WEBHOOK_SECRET"]

# Workout schedule reference date — set GYM_REF_DATE in .env (YYYY-MM-DD, a known gym day)
_ref_str = os.environ["GYM_REF_DATE"]
GYM_REF  = datetime.date.fromisoformat(_ref_str)

LOCAL_TZ = pytz.timezone(p.TIMEZONE)

# ── Global clients (initialised once at startup) ───────────────────────────────
bot              = telebot.TeleBot(TELEGRAM_TOKEN)
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
openai_client    = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None
gh               = Github(GITHUB_TOKEN)
