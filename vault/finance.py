"""
Finance: bank statement parsing (DNB, Revolut), AI categorization, budget actuals.
"""
import csv
import io
import json
import logging
import re
from datetime import datetime
from config import LOCAL_TZ, bot, TELEGRAM_TOKEN
from services.github_service import read_file, write_file
import requests

logger = logging.getLogger(__name__)

DNB_SKIP_KEYWORDS = [
    "overføring mellom egne",
    "kontoregulering",
    "revolut",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dnb_date(raw) -> str | None:
    if hasattr(raw, "strftime"):
        return raw.strftime("%Y-%m-%d")
    parts = str(raw).strip().split(".")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return None


def detect_bank(filename: str, content_sample: str) -> str:
    name = filename.lower()
    if "revolut" in name:
        return "revolut"
    if "dnb" in name:
        return "dnb"
    sample = content_sample[:500].lower()
    if "started date" in sample or "completed date" in sample or "topup" in sample:
        return "revolut"
    if "dato" in sample and ("ut fra konto" in sample or "inn på konto" in sample or "tekst" in sample):
        return "dnb"
    return "unknown"


# ── Parsers ────────────────────────────────────────────────────────────────────

def parse_dnb_xlsx(raw: bytes) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl not installed")
        return []
    transactions = []
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header_idx, header = None, []
    for i, row in enumerate(rows):
        cells = [str(c).lower().strip() if c is not None else "" for c in row]
        if any("dato" in c for c in cells) and any("forklaring" in c or "tekst" in c for c in cells):
            header_idx, header = i, cells
            break
    if header_idx is None:
        return []

    def col(*candidates):
        for i, h in enumerate(header):
            if any(c in h for c in candidates):
                return i
        return None

    dato_col = col("dato")
    desc_col = col("forklaring", "tekst")
    ut_col   = col("ut fra")
    if any(c is None for c in [dato_col, desc_col, ut_col]):
        return []

    for row in rows[header_idx + 1:]:
        try:
            date = _dnb_date(row[dato_col])
            if not date:
                continue
            desc = str(row[desc_col]).strip() if row[desc_col] else ""
            ut_raw = row[ut_col]
            if ut_raw is None:
                continue
            ut = float(str(ut_raw).replace(",", ".").replace("\xa0", "").replace(" ", ""))
            if ut <= 0 or not desc:
                continue
            if any(kw in desc.lower() for kw in DNB_SKIP_KEYWORDS):
                continue
            transactions.append({"date": date, "description": desc, "amount": ut, "currency": "NOK"})
        except (ValueError, TypeError):
            continue
    return transactions


def parse_dnb_csv(content: str) -> list[dict]:
    transactions = []
    lines = content.strip().splitlines()
    if not lines:
        return []
    reader = csv.DictReader(lines, delimiter=";")
    for row in reader:
        try:
            date = _dnb_date(row.get("Dato", "").strip())
            if not date:
                continue
            desc = (row.get("Forklaring") or row.get("Tekst") or "").strip()
            ut_str = row.get("Ut fra konto", "").replace(",", ".").replace("\xa0", "").replace(" ", "").strip()
            if not ut_str:
                continue
            ut = float(ut_str)
            if ut <= 0 or not desc:
                continue
            if any(kw in desc.lower() for kw in DNB_SKIP_KEYWORDS):
                continue
            transactions.append({"date": date, "description": desc, "amount": ut, "currency": "NOK"})
        except (ValueError, KeyError):
            continue
    return transactions


def parse_revolut_csv(content: str) -> list[dict]:
    transactions = []
    lines = content.strip().splitlines()
    if not lines:
        return []
    reader = csv.DictReader(lines)
    for row in reader:
        try:
            state = row.get("State", "").upper()
            if state != "COMPLETED":
                continue
            tx_type = row.get("Type", "").replace(" ", "").upper()
            if tx_type == "TOPUP":
                continue
            amount = float(row.get("Amount", "0"))
            if amount >= 0:
                continue
            raw_date = row.get("Completed Date") or row.get("Started Date") or ""
            date = raw_date[:10]
            desc = row.get("Description", "").strip()
            currency = row.get("Currency", "NOK")
            if not date or not desc:
                continue
            transactions.append({"date": date, "description": desc, "amount": abs(amount), "currency": currency})
        except (ValueError, KeyError):
            continue
    return transactions


# ── AI categorization ──────────────────────────────────────────────────────────

def categorize_and_import(transactions: list[dict]) -> str:
    if not transactions:
        return ""
    from ai.client import call_ai

    tx_list = "\n".join(
        f"- {t['date']} | {t['description']} | {t['amount']} {t['currency']}"
        for t in transactions
    )
    result = call_ai(
        system="You are a finance assistant. Respond with raw JSON only, no markdown.",
        user=f"""Categorize these bank transactions. For each, assign one category from:
Food, Transport, Clothing, Tech, Entertainment, Health, Subscriptions, Housing, Education, Savings, Other.

Transactions:
{tx_list}

Return a JSON array:
[{{"date": "YYYY-MM-DD", "description": "short description", "category": "Category", "amount": 123.45, "currency": "NOK"}}]

Keep descriptions short (max 4 words). Dates must stay as-is.""",
        max_tokens=2000
    )
    try:
        raw = result.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        categorized = json.loads(raw)
        rows = []
        for t in categorized:
            amount = f"{t['amount']:.0f} {t.get('currency', 'NOK')}"
            rows.append(f"| {t['date']} | {t['description']} | {t['category']} | {amount} |")
        return "\n".join(rows)
    except Exception as e:
        logger.error(f"Categorize error: {e}")
        return ""


def extract_transactions_from_text(raw_text: str) -> str:
    from ai.client import call_ai
    return call_ai(
        system="You are a finance assistant. Respond with raw JSON only, no markdown.",
        user=f"""This is a bank statement. Extract all expense transactions (outgoing payments only).
For each transaction assign a category: Food, Transport, Clothing, Tech, Entertainment, Health, Subscriptions, Housing, Education, Savings, Other.

Return a JSON array:
[{{"date": "YYYY-MM-DD", "description": "short description (max 4 words)", "category": "Category", "amount": 123.45, "currency": "NOK"}}]

If dates are in Norwegian format (DD.MM.YYYY), convert to YYYY-MM-DD.
Only include expenses (money going out). Skip incoming transfers, salary, refunds.
If currency is missing, assume NOK.

Statement:
{raw_text[:6000]}""",
        max_tokens=3000
    )


# ── Budget actuals updater ─────────────────────────────────────────────────────

def update_budget_actuals(finance_content: str) -> str:
    now = datetime.now(LOCAL_TZ)
    month_prefix = now.strftime("%Y-%m")

    category_totals: dict[str, float] = {}
    grand_total = 0.0
    in_expense_log = False

    for line in finance_content.splitlines():
        if "## 📒 Expense Log" in line:
            in_expense_log = True
            continue
        if in_expense_log and line.startswith("## "):
            in_expense_log = False
            continue
        if in_expense_log and line.startswith(f"| {month_prefix}"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                category = parts[3]
                amount_str = parts[4].upper().replace("NOK", "").strip()
                try:
                    amount = float(amount_str)
                    category_totals[category] = category_totals.get(category, 0.0) + amount
                    grand_total += amount
                except ValueError:
                    pass

    if not category_totals:
        return finance_content

    BUDGET_MAP: dict[str, list[str]] = {
        "Housing": ["Housing"], "Food": ["Food"], "Transport": ["Transport"],
        "Subscriptions": ["Subscriptions"], "Entertainment": ["Entertainment"], "Savings": [],
    }

    lines = finance_content.splitlines()
    result = []
    in_budget = False

    for line in lines:
        if "## 📊 Monthly Budget" in line:
            in_budget = True
            result.append(line)
            continue
        if in_budget and line.startswith("## "):
            in_budget = False
            result.append(line)
            continue
        if in_budget and line.startswith("|") and not line.startswith("|---") and not line.startswith("| Category"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                row_name = parts[1].strip("*").strip()
                if row_name == "Total":
                    actual = f"{int(grand_total)} NOK" if grand_total > 0 else ""
                    result.append(f"| **Total** | {parts[2]} | {actual} |")
                    continue
                elif row_name in BUDGET_MAP:
                    cats = BUDGET_MAP[row_name]
                    actual = sum(category_totals.get(c, 0.0) for c in cats)
                    actual_str = f"{int(actual)} NOK" if actual > 0 else ""
                    result.append(f"| {row_name} | {parts[2]} | {actual_str} |")
                    continue
        result.append(line)

    return "\n".join(result)


# ── Import handlers ────────────────────────────────────────────────────────────

def handle_csv_import(file_id: str, filename: str = "") -> str:
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        response = requests.get(url, timeout=30)
        raw = response.content

        is_xlsx = filename.lower().endswith((".xlsx", ".xls"))
        if is_xlsx:
            bank = detect_bank(filename, "") or "dnb"
            transactions = parse_dnb_xlsx(raw)
        else:
            content = raw.decode("utf-8-sig")
            bank = detect_bank(filename, content)
            if bank == "revolut":
                transactions = parse_revolut_csv(content)
            elif bank == "dnb":
                transactions = parse_dnb_csv(content)
            else:
                t_dnb = parse_dnb_csv(content)
                t_rev = parse_revolut_csv(content)
                transactions = t_dnb if len(t_dnb) >= len(t_rev) else t_rev
                bank = "dnb" if transactions is t_dnb else "revolut"

        if not transactions:
            return (
                f"⚠️ Could not parse the file as <b>{bank.upper()}</b> export.\n"
                f"Make sure it's an unmodified DNB or Revolut export."
            )

        rows = categorize_and_import(transactions)
        if not rows:
            return "⚠️ Failed to categorize transactions."

        finance = read_file("02 Areas/Finance.md") or ""
        if "## 📒 Expense Log" in finance:
            updated = finance.rstrip() + "\n" + rows + "\n"
        else:
            updated = (
                finance.rstrip()
                + f"\n\n## 📒 Expense Log\n| Date | Description | Category | Amount (NOK) |\n|------|-------------|----------|--------------|\n"
                + rows + "\n"
            )

        write_file("02 Areas/Finance.md", update_budget_actuals(updated), f"Import {len(transactions)} {bank} transactions")

        total = sum(t["amount"] for t in transactions)
        bank_label = "🏦 DNB" if bank == "dnb" else "💳 Revolut"
        return (
            f"✅ <b>{bank_label}: {len(transactions)} transactions imported</b>\n\n"
            f"💰 Total: <b>{total:.0f} NOK</b>\n"
            f"🚫 Transfers to Revolut/incoming excluded automatically\n\n"
            f"Use /finance to see the full breakdown."
        )

    except Exception as e:
        logger.error(f"CSV/XLSX import error: {e}", exc_info=True)
        return f"⚠️ Import error: <code>{type(e).__name__}: {e}</code>"


def handle_statement_import(file_id: str, filename: str) -> str:
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        response = requests.get(url, timeout=30)

        if filename.endswith(".pdf"):
            import pdfplumber
            with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        else:
            raw_text = response.content.decode("utf-8-sig", errors="replace")

        if not raw_text.strip():
            return "⚠️ Could not extract text from the file."

        result_raw = extract_transactions_from_text(raw_text)
        try:
            result_raw = result_raw.strip()
            if result_raw.startswith("```"):
                result_raw = result_raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            categorized = json.loads(result_raw)
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', result_raw, re.DOTALL)
            if match:
                categorized = json.loads(match.group())
            else:
                return "⚠️ Could not parse transactions from the file."

        if not categorized:
            return "⚠️ No expense transactions found in the file."

        rows = [
            f"| {t['date']} | {t['description']} | {t['category']} | {t['amount']:.0f} {t.get('currency', 'NOK')} |"
            for t in categorized
        ]

        finance = read_file("02 Areas/Finance.md") or ""
        if "## 📒 Expense Log" in finance:
            updated = finance.rstrip() + "\n" + "\n".join(rows) + "\n"
        else:
            updated = (
                finance.rstrip()
                + f"\n\n## 📒 Expense Log\n| Date | Description | Category | Amount |\n|------|-------------|----------|---------|\n"
                + "\n".join(rows) + "\n"
            )

        write_file("02 Areas/Finance.md", update_budget_actuals(updated), f"Import {len(categorized)} transactions from {filename}")

        total = sum(t["amount"] for t in categorized)
        return (
            f"✅ <b>Imported {len(categorized)} transactions</b> from <code>{filename}</code>\n\n"
            f"💰 Total spent: <b>{total:.0f} NOK</b>\n\n"
            f"Use /finance to see the full breakdown."
        )

    except Exception as e:
        logger.error(f"Statement import error: {e}", exc_info=True)
        return f"⚠️ Import error: <code>{type(e).__name__}: {e}</code>"


# ── cmd_finance ────────────────────────────────────────────────────────────────

def cmd_finance() -> str:
    from ai.client import call_ai
    finance = read_file("02 Areas/Finance.md") or ""
    now = datetime.now(LOCAL_TZ)
    month = now.strftime("%Y-%m")
    return call_ai(
        system="""You are a personal finance assistant. Respond ONLY in English.
CRITICAL formatting rules for Telegram:
- Use HTML only: <b>bold</b>, <i>italic</i>, <code>text</code>
- NEVER use markdown: no **, no __, no ##, no ---, no | tables |
- Use <code> blocks for all numeric/aligned data
- Use bullet points with • for lists""",
        user=f"""From the Expense Log table, find all entries for {now.strftime('%B %Y')} (dates starting with {month}).
Show spending grouped by category, then totals. Format like this example:

💰 <b>April 2026 Spending</b>

🛒 <b>Food</b>
• Rema 1000 — 36 NOK

<code>Category        Amount
─────────────────────
Food               36 NOK
─────────────────────
Total             215 NOK</code>

If no entries this month, say so clearly.

{finance}""",
        max_tokens=500
    )
