"""
Smart context loading — detects message topic and loads only relevant vault files.
"""
from services.github_service import read_file, read_file_tail
from vault.daily_note import get_today_note_path

VAULT_FILES = [
    "05 Planned.md",
    "02 Areas/Health.md",
    "02 Areas/Nutrition.md",
    "02 Areas/Finance.md",
    "02 Areas/Work.md",
    "02 Areas/Hobbies.md",
    "02 Areas/Personal Growth.md",
    "02 Areas/Relationships.md",
    "03 Projects/Boardly.md",
    "03 Projects/Boardly Ideas.md",
    "03 Projects/mohawk.md",
    "04 Ideas/Ideas.md",
]

TAIL_FILES = {"02 Areas/Finance.md"}


def load_context(text: str = "") -> str:
    t = text.lower()

    if any(w in t for w in ["water", "вода", "чай", "tea", "coffee", "кофе", "juice", "сок"]):
        paths = []
    elif any(w in t for w in ["eat", "ate", "food", "meal", "calories", "kcal", "protein", "carb", "fat",
                               "съел", "поел", "завтрак", "обед", "ужин", "перекус", "макрос", "nutrition"]):
        paths = ["02 Areas/Nutrition.md"]
    elif any(w in t for w in ["spent", "paid", "bought", "cost", "price", "money", "budget", "expense",
                               "потратил", "купил", "заплатил", "деньги", "финанс", "finance", "nok", "крон"]):
        paths = ["02 Areas/Finance.md"]
    elif any(w in t for w in ["sleep", "woke", "bed", "tired", "gym", "workout", "fitness", "weight",
                               "сон", "лёг", "проснулся", "устал", "зал", "тренировк", "вес", "health"]):
        paths = ["02 Areas/Health.md", "02 Areas/Fitness.md"]
    elif any(w in t for w in ["boardly", "game", "socket", "deploy", "feature", "bug", "игра"]):
        paths = ["03 Projects/Boardly.md", "03 Projects/Boardly Ideas.md"]
    elif any(w in t for w in ["mohawk", "work", "job", "internship", "работа", "стажировк"]):
        paths = ["02 Areas/Work.md", "03 Projects/mohawk.md"]
    elif any(w in t for w in ["read", "book", "pages", "atomic", "english", "norwegian", "language",
                               "читал", "книг", "страниц", "английск", "норвежск", "hobby", "хобби"]):
        paths = ["02 Areas/Hobbies.md", "02 Areas/Personal Growth.md"]
    elif any(w in t for w in ["idea", "идея", "future", "app", "business", "project"]):
        paths = ["04 Ideas/Ideas.md", "03 Projects/Boardly Ideas.md"]
    elif any(w in t for w in ["план", "remind", "напомни", "schedule", "tomorrow", "завтра",
                               "next week", "следующ", "friday", "пятниц", "monday", "понедельн",
                               "april", "апрел", "may", "май", "june", "июн"]):
        paths = ["05 Planned.md"]
    else:
        paths = ["02 Areas/Health.md", "03 Projects/Boardly.md", "02 Areas/Personal Growth.md"]

    parts = []
    for path in paths:
        content = read_file_tail(path, 60) if path in TAIL_FILES else read_file(path)
        if content:
            parts.append(f"=== {path} ===\n{content}")

    today = read_file(get_today_note_path())
    if today:
        parts.append(f"=== TODAY ({get_today_note_path()}) ===\n{today}")

    return "\n\n".join(parts)
