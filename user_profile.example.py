"""
Your personal profile — copy this file to user_profile.py and fill in your details.
user_profile.py is gitignored and never committed.
"""

# ── Identity ──────────────────────────────────────────────────────────────────
NAME          = "Marco"           # Your first name
AGE           = 31                # Your age
NATIONALITY   = "Brazilian"       # Your nationality
CITY          = "Berlin"          # City you live in

# ── Physical & health goals ───────────────────────────────────────────────────
WEIGHT_KG     = 88                # Current weight in kg
HEIGHT_CM     = 185               # Height in cm
BULK_TARGET_KG = 83               # Body weight goal in kg

# Daily macro targets
KCAL_TARGET   = 2400
PROTEIN_G     = 160
CARBS_G       = 250
FAT_G         = 80

# ── Schedule ──────────────────────────────────────────────────────────────────
# School/work hours (24h format strings, used in prompts)
SCHOOL_HOURS  = "09:00–17:30 Mon–Thu, 09:00–13:00 Fri"
COMMUTE_MIN   = 45                # One-way commute in minutes

# ── Fitness ───────────────────────────────────────────────────────────────────
# Workout alternates: even days from GYM_REF_DATE = gym, odd = abs/warm-up
# Set GYM_REF_DATE in .env (YYYY-MM-DD). This is the fallback label only.
GYM_DAY_LABEL = "gym"
ABS_DAY_LABEL = "abs + warm-up"

# Supplements
SUPPLEMENT    = "whey protein 30g post-workout"

# ── Current reading ───────────────────────────────────────────────────────────
BOOK_TITLE    = "The Pragmatic Programmer"
BOOK_AUTHOR   = "David Thomas & Andrew Hunt"
BOOK_PAGES    = 352
READING_GOAL  = 15                # pages per day

# ── Language goals ────────────────────────────────────────────────────────────
LANGUAGES     = "German B2, Spanish native, English C1"

# ── Hobbies ───────────────────────────────────────────────────────────────────
HOBBIES       = "Brazilian jiu-jitsu, climbing, vinyl records, street photography"
MAIN_GAME     = "chess"

# ── Work / study ──────────────────────────────────────────────────────────────
OCCUPATION    = "backend developer, part-time MSc student"
MAIN_PROJECT  = "MyApp"           # Your main side project name
WORK_PROJECT  = "work"            # Internal work project label

# ── Vault structure ───────────────────────────────────────────────────────────
# Paths inside your GitHub vault repo
WORK_AREA_FILE    = "02 Areas/Work.md"
WORK_PROJECT_FILE = "03 Projects/work.md"
MAIN_PROJECT_FILE = "03 Projects/MyApp.md"
MAIN_IDEAS_FILE   = "03 Projects/MyApp Ideas.md"

# ── Near-term goals ───────────────────────────────────────────────────────────
FINANCIAL_GOALS = "pay off student loan and visit Japan"

# ── Location (for weather) ────────────────────────────────────────────────────
# Find your coordinates at: https://www.latlong.net/
WEATHER_LAT   = 52.5200           # Berlin
WEATHER_LON   = 13.4050
TIMEZONE      = "Europe/Berlin"
