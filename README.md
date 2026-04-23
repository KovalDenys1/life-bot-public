# 🤖 Life Bot — AI-Powered Personal Assistant via Telegram

A personal AI assistant that helps manage daily life through a simple Telegram chat. Instead of juggling multiple apps for habits, nutrition, finances, and notes — you just write naturally, and the bot understands, logs, and organizes everything automatically.

---

## 🧩 Problem

Modern life generates a lot of data worth tracking — what you ate, how much you slept, how much you spent, which habits you kept up. Most people either:

- Use 5+ separate apps that don't talk to each other
- Stop tracking after a few days because it's too much friction
- Lose their data when they switch apps or devices

The core issue is that **the act of logging should take zero effort**. If it's inconvenient, people simply don't do it.

---

## 💡 Solution

A single Telegram chat where you can write (or speak) naturally in any language, and the bot handles everything else:

- Understands what you're telling it
- Extracts structured data (macros, expenses, sleep times)
- Saves everything to a personal knowledge base (Obsidian vault)
- Answers questions about your own data
- Sends proactive morning and evening summaries

---

## ✨ Features

### 📝 Natural Language Logging
Write anything naturally — the AI extracts the relevant data:
> *"Had chicken with rice and a banana"* → logs macros to nutrition tracker  
> *"Spent 89 NOK on groceries"* → logs expense to finance tracker  
> *"Went to bed at 23:30"* → logs bedtime to yesterday's daily note

### 🥗 Nutrition Tracking
- Calculates calories, protein, carbs, fat from food descriptions
- Scans nutrition labels from photos (Claude Vision)
- Shows daily progress vs targets after every meal
- Tracks against personalized macro goals (set in `user_profile.py`)
- Paginated saved meals menu (6 per page) with one-tap logging

### 💰 Finance Tracking
- Logs expenses with auto-categorization
- Imports bank statements: CSV, PDF, and TXT exports (DNB, Revolut)
- Monthly spending breakdowns by category

### 🔥 Habit Streaks
- Tracks 7 daily habits: water, workout, main project, reading, English, Norwegian, supplement
- Smart alternating schedule: gym day / abs+warm-up day (every other day)
- Streak visualization over last 14 days
- Quick-tap buttons — one tap to log a habit, no typing needed
- Buttons update in-place showing real-time completion state (✅)
- Fixed-width 2-column keyboard layout (no truncation on habit completion)

### 💧 Health Tracking
- Water intake counter with live button (goal: 8 glasses/day)
- Sleep log with goal comparison
- Daily notes with morning check-in and evening reflection

### 📚 Reading Tracker
- Tracks pages read per day
- Progress bar for current book
- Daily reading habit with configurable daily page goal (set in `user_profile.py`)

### 🗓 Future Planning
- Tell the bot about future tasks: *"Friday — dentist appointment"*
- Tasks are automatically injected into that day's daily note when it arrives

### 🍽 Weekly Meal Plan Generation
- Every Sunday the bot auto-generates a randomized meal plan for the next week
- Guarantees 4–5 Oatmeal Bowl breakfasts per week
- Picks lunches/dinners from the saved meals pool, respecting gym vs. rest day macros
- Writes the full plan to `02 Areas/Weekly Meal Plan.md` in the vault and sends it to Telegram

### 🌅 Scheduled Messages
- **Morning (06:15):** Weather (yr.no), today's habit checklist, workout type reminder, language phrase of the day
- **Evening (21:30):** Wind-down reminder, evening reflection prompts, API cost summary
- **Friday (16:30):** Motivating end-of-week message with habit completion stats
- **Sunday (20:00):** AI weekly review + weekly meal plan + API cost summary

### ⚡ Quick Ask (Haiku)
- Tap "Quick Ask" in the menu for fast, cheap answers using Claude Haiku
- No vault context loaded — instant responses at ~10x lower cost

### 🔍 Vault Search
- `/search keyword` — searches across all personal notes and logs

### 📊 Reports
- `/today` — today's plan and habits status (AI)
- `/macros` — today's nutrition summary (AI)
- `/health` — health & sleep status (AI)
- `/streaks` — habit streak overview (free)
- `/finance` — monthly spending breakdown (AI)
- `/week` — AI-generated weekly review
- `/project` — external project live stats (optional, requires `BOARDLY_DATABASE_URL`)

### 📷 Photo & Voice Input
- Send a photo of food — AI reads the nutrition label
- Send a voice message — Whisper transcribes it, then AI processes it as text

---

## 🏗 Architecture

```
You (Telegram)
      │
      │  text / voice / photo / document
      ▼
Telegram Servers
      │
      │  POST /webhook
      ▼
┌─────────────────────────────────┐
│         Render.com              │
│   Flask web server (bot.py)     │
│                                 │
│  • Message debounce (2s buffer) │
│  • Conversation history         │
│    (persisted to GitHub JSON)   │
│  • Smart context loading        │
│  • File cache (60s TTL)         │
│  • Weather cache (10min TTL)    │
│  • Async GitHub saves (3s       │
│    debounce, background thread) │
└──────┬──────────────────────────┘
       │
       ├──► GitHub API ──────────► Your vault repository
       │    read/write .md files   (Obsidian vault)
       │                                │
       ├──► Anthropic API               │ iCloud/local sync
       │    Claude Sonnet 4.6 (main)    │
       │    Claude Haiku 4.5 (quick)    ▼
       │                           Mac / iPhone / iPad
       ├──► OpenAI                      (Obsidian app)
       │    GPT-4o (fallback)
       │    Whisper (voice)
       │
       ├──► yr.no API
       │    Oslo weather (free, official Norwegian service)
       │
       └──► PostgreSQL (optional)
            External project stats (psycopg2)
```

**Data flow for a typical message:**
1. User sends a message in Telegram
2. Telegram forwards it to the Flask webhook on Render
3. Bot loads only the relevant vault files from GitHub (smart context)
4. Claude processes the message + vault context → returns JSON
5. Bot applies file updates to GitHub (`append` for new log entries, `update` for edits) via async background thread
6. Bot sends reply back to Telegram
7. Vault files auto-sync via iCloud to all devices

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot framework | pyTelegramBotAPI |
| Web server | Flask + Gunicorn |
| AI (primary) | Anthropic Claude Sonnet 4.6 |
| AI (quick/cheap) | Anthropic Claude Haiku 4.5 |
| AI (fallback) | OpenAI GPT-4o |
| Voice transcription | OpenAI Whisper |
| Vision (food labels) | Claude Vision |
| Knowledge base | GitHub API + Markdown files |
| Hosting | Render.com (free tier) |
| Scheduling | GitHub Actions (cron workflows) |
| Weather | yr.no (official Norwegian meteorological service) |
| External project stats | psycopg2 → PostgreSQL (optional) |

---

## 📁 Vault Structure

The personal knowledge base is a set of Markdown files stored in a GitHub repository and synced locally via iCloud for use in Obsidian:

```
Life-vault/
├── 00 Home.md              # Dashboard — overview of all areas and goals
├── 00 Meta/
│   └── cost_log.json       # API usage stats + chat history (bot-managed)
├── 01 Daily/               # Daily notes (auto-created each morning)
│   └── 2026/04/
│       └── 2026-04-16.md
├── 02 Areas/               # Ongoing life areas
│   ├── Health.md           # Sleep log, fitness routine, body metrics
│   ├── Fitness.md          # Training program (Push/Pull/Legs), workout log
│   ├── Nutrition.md        # Macro targets, meal list with macros
│   ├── Finance.md          # Budget, expense log, savings goals
│   ├── Work.md             # Career goals, weekly log
│   ├── Hobbies.md          # Gaming, sports, activities
│   ├── Personal Growth.md  # Schedule, languages, reading, values
│   ├── Relationships.md    # People, contact log
│   ├── Weekly Meal Plan.md # Current week's meal plan (auto-generated Sundays)
│   └── Meals/              # Recipe pages (14 meals with full macros + ingredients)
│       ├── Oatmeal Bowl.md
│       ├── Chicken + Rice + Avocado.md
│       ├── Pasta Bolognese.md
│       └── ...
├── 03 Projects/            # Active projects (configurable in user_profile.py)
│   ├── MyProject.md        # Main side project
│   ├── MyProject Ideas.md  # Feature and game ideas for the main project
│   └── Work.md             # Internship / job project
├── 04 Ideas/               # General ideas and future projects
│   ├── Ideas.md            # Ideas log
│   └── Life Assistant Bot.md  # Product idea: multi-user AI life assistant
└── 05 Planned.md           # Future tasks (auto-injected into daily notes)
```

---

## ⚙️ Cost Optimizations

Since the bot runs on a budget, several optimizations reduce API costs:

- **Smart context loading** — detects message topic and loads only relevant files (e.g., only `Nutrition.md` for food messages), reducing input tokens by ~50–70%
- **Claude Haiku for Quick Ask** — ~10x cheaper than Sonnet for simple questions
- **Direct Python handlers for habit buttons** — no AI call needed, pure string operations
- **File cache (60s TTL)** — avoids redundant GitHub API calls within the same session
- **Weather cache (10min TTL)** — avoids redundant yr.no API calls between the morning cron and on-demand requests
- **Async debounced GitHub saves (3s)** — batches rapid vault writes into a single API call
- **Conversation history limited to 3 exchanges** — enough for corrections without excess tokens
- **File tail truncation** — large files (Finance, Nutrition) read only the last 60 lines
- **History stores only user text** — not full vault context (saves ~3x tokens per entry)

Estimated cost: **~$0.003–0.005 per message**

---

## 🚀 Setup

### Prerequisites
- Python 3.11+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Anthropic API key
- OpenAI API key (for voice + fallback)
- GitHub personal access token
- A GitHub repository for the vault

### Environment Variables

```env
TELEGRAM_TOKEN=your_telegram_bot_token
ANTHROPIC_KEY=your_anthropic_api_key
OPENAI_KEY=your_openai_api_key
GITHUB_TOKEN=your_github_token
GITHUB_REPO=username/Life-vault
CHAT_ID=your_telegram_chat_id
WEBHOOK_SECRET=your_webhook_secret
PROJECT_DATABASE_URL=postgresql://...  # optional, for /project command
```

### Install & Run

```bash
pip install -r requirements.txt
gunicorn bot:app --workers 1 --threads 4
```

### Set Webhook

```bash
curl -X GET "https://your-app.onrender.com/set-webhook" \
  -H "X-Cron-Secret: YOUR_WEBHOOK_SECRET"
```

### Scheduled Endpoints (via GitHub Actions)

Cron jobs in `.github/workflows/cron.yml` call these endpoints, passing the secret in the `X-Cron-Secret` header:

| Endpoint | Schedule | Purpose |
|----------|----------|---------|
| `POST /morning` | 06:15 Oslo daily | Morning briefing + create daily note |
| `POST /evening` | 21:30 Oslo daily | Evening reminder + API cost summary |
| `POST /friday` | 16:30 Oslo Fridays | End-of-week motivational summary |
| `POST /weekly-report` | 20:00 Oslo Sunday | Weekly meal plan + AI weekly review + cost summary |

---

## 📦 Dependencies

```
flask==3.1.0
pyTelegramBotAPI==4.22.0
anthropic>=0.50.0
openai==1.57.0
PyGithub==2.4.0
pytz==2024.2
gunicorn==23.0.0
requests==2.32.3
pdfplumber==0.11.4
psycopg2-binary==2.9.10
```

---

## 🗒 Public Version Notice

This is the **public version** of a private personal project. The private repository contains actual vault files with health, finance, and daily notes — personal data I can't publish. All personal details (name, body metrics, macro targets, vault paths, coordinates) have been moved to `user_profile.py`, which is gitignored and never committed.

To run your own instance, copy `user_profile.example.py` → `user_profile.py` and fill in your details.

---

## 🎓 What I Learned

Building this bot was a hands-on deep dive into production Python and AI integration. Here's what I picked up along the way:

**Python & architecture**
- Structuring a real multi-module Python project (not just scripts) with clear separation between services, vault, AI, and UI layers
- How Python's module import system works in practice — circular imports, package `__init__.py`, and using a single `config.py` as the source of truth for all clients
- Threading and concurrency: debounced background saves with `threading.Thread` and `Lock`, message buffering with `threading.Timer` to collapse rapid inputs into one AI call

**AI & prompting**
- How to write large, structured system prompts that make the model behave reliably — routing rules, output format constraints, and explicit fallbacks
- Why prefilling (`prefill="{"`) dramatically improves JSON reliability compared to just asking for JSON in the prompt
- Practical tradeoffs between Claude Sonnet (capable, more expensive) and Claude Haiku (fast, cheap) for different use cases
- Using Claude Vision for food label reading and OpenAI Whisper for voice transcription

**APIs and external services**
- GitHub API (via PyGithub) for reading and writing Markdown vault files — treating GitHub as a free structured database
- Telegram Bot API: webhooks vs polling, inline keyboards, message editing in-place, and `message_id` tracking
- yr.no weather API (official Norwegian meteorological service): no API key needed, but requires a specific `User-Agent`
- Flask webhooks on Render: deploying a Python web app with Gunicorn and wiring up the Telegram webhook URL

**Performance & cost optimization**
- Smart context loading: detecting message intent and loading only relevant vault files to cut input tokens by 50–70%
- File-level caching (60s TTL) to avoid redundant GitHub API calls
- Async debounced GitHub writes: batching multiple rapid file updates into a single commit
- Conversation history truncation: keeping only the last 3 exchanges while still storing enough for corrections

**DevOps & deployment**
- Environment variable management: separating secrets (`.env`) from personal config (`user_profile.py`)
- Render.com deployment with Gunicorn and Procfile; scheduled endpoints triggered via GitHub Actions cron workflows instead of relying on polling
- Webhook signature validation to prevent unauthorized trigger calls

---

## 👤 Author

**Denys Koval** — IT student, Oslo  
Built as a personal productivity tool and learning project.
