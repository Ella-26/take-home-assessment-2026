"""Section B: Which sector raised the most money in Q3 2026 (Jul-Sep)?

Reads rounds.csv (never modified), cleans it, converts amounts to USD and
prints sector totals for two scenarios:
  - Primary: every Q3 deal taken at face value.
  - Backup:  the same, minus rounds flagged as unusually large for their stage.
Writes rounds_clean.csv and cleaning_log.csv next to the input file.

Usage: python3 clean_rounds.py [path/to/rounds.csv]
"""
import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

RATES_TO_USD = {"USD": 1.0, "SGD": 0.77, "INR": 0.012}  # rates given in the brief
Q3_START, Q3_END = date(2026, 7, 1), date(2026, 9, 30)
# ISO first; slash dates are read as DD/MM/YYYY (Singapore convention).
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")
DUPLICATE_WINDOW_DAYS = 7
# Rounds above these sizes stay in the primary total but are left out of the backup.
FLAG_ABOVE_USD = {"Pre-seed": 5_000_000, "Seed": 20_000_000}
COMPANY_SUFFIX = re.compile(
    r"\s*\b(pte\.?\s*ltd|pvt\.?\s*ltd|sdn\.?\s*bhd|ltd|inc|llc|corp)\.?$", re.IGNORECASE
)


def parse_date(text):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date(), fmt
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {text!r}")


def company_key(name):
    """'Kirana Fleet Pte Ltd' and 'Kirana Fleet' -> 'kirana fleet'."""
    key = name.strip().lower()
    while True:
        stripped = COMPANY_SUFFIX.sub("", key).strip(" ,.")
        if stripped == key:
            return key
        key = stripped


def usd(value):
    return f"US${value / 1e6:,.2f}M"


def sector_totals(deals):
    totals = defaultdict(float)
    for d in deals:
        totals[d["sector"]] += d["amount_usd"]
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", nargs="?", default="rounds.csv")
    src = Path(parser.parse_args().csv_path).resolve()
    clean_path = src.with_name("rounds_clean.csv")
    log_path = src.with_name("cleaning_log.csv")
    assert src not in (clean_path, log_path), "Refusing to overwrite the input file"

    with src.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Canonical sector spelling = the most common spelling of each sector, ignoring case.
    spellings = defaultdict(Counter)
    for row in rows:
        spellings[row["sector"].strip().lower()][row["sector"].strip()] += 1
    canonical_sector = {k: c.most_common(1)[0][0] for k, c in spellings.items()}

    kept, log = [], []

    def note(line, row, action, detail):
        log.append({"line": line, "company": row["company"], "action": action, "detail": detail})

    for line, row in enumerate(rows, start=2):  # line 1 is the header
        when, fmt = parse_date(row["date"])
        if fmt != DATE_FORMATS[0]:
            note(line, row, "date reformatted", f"{row['date']} -> {when.isoformat()}")
        if not Q3_START <= when <= Q3_END:
            note(line, row, "excluded", f"{when.isoformat()} is outside Q3 2026")
            continue

        sector = canonical_sector[row["sector"].strip().lower()]
        if sector != row["sector"]:
            note(line, row, "sector renamed", f"{row['sector']} -> {sector}")

        currency = row["currency"].strip().upper()
        if currency not in RATES_TO_USD:
            raise ValueError(f"Line {line}: no rate for currency {currency!r}")
        amount = float(row["amount"])
        amount_usd = amount * RATES_TO_USD[currency]
        if currency != "USD":
            note(line, row, "converted", f"{amount:,.0f} {currency} -> {usd(amount_usd)}")

        deal = {
            "line": line, "date": when, "company": row["company"].strip(),
            "key": company_key(row["company"]), "sector": sector,
            "round": row["round"].strip(), "amount": amount, "currency": currency,
            "amount_usd": amount_usd, "source": row["source"].strip(),
        }

        original = next(
            (k for k in kept
             if k["key"] == deal["key"] and k["round"] == deal["round"]
             and k["amount"] == amount and k["currency"] == currency
             and abs((k["date"] - when).days) <= DUPLICATE_WINDOW_DAYS),
            None,
        )
        if original:
            note(line, row, "dropped duplicate",
                 f"same deal as line {original['line']} ({original['company']}, {original['source']})")
            continue

        limit = FLAG_ABOVE_USD.get(deal["round"])
        deal["flagged"] = bool(limit and amount_usd > limit)
        if deal["flagged"]:
            note(line, row, "flagged (kept)",
                 f"{usd(amount_usd)} is above {usd(limit)} for a {deal['round']} round")
        kept.append(deal)

    columns = ["line", "date", "company", "sector", "round", "amount", "currency",
               "amount_usd", "source", "flagged"]
    with clean_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for d in kept:
            writer.writerow({**d, "date": d["date"].isoformat(), "amount": f"{d['amount']:.0f}",
                             "amount_usd": f"{d['amount_usd']:.2f}"})
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["line", "company", "action", "detail"])
        writer.writeheader()
        writer.writerows(sorted(log, key=lambda e: e["line"]))

    print("Cleaning log:")
    for e in sorted(log, key=lambda e: e["line"]):
        print(f"  line {e['line']:>2}  {e['company']:<22} {e['action']:<18} {e['detail']}")

    flagged = [d for d in kept if d["flagged"]]
    scenarios = [("PRIMARY: all Q3 deals at face value", kept)]
    if flagged:
        names = ", ".join(d["company"] for d in flagged)
        scenarios.append((f"BACKUP: excluding flagged rounds ({names})",
                          [d for d in kept if not d["flagged"]]))
    for title, deals in scenarios:
        totals = sector_totals(deals)
        print(f"\n{title}  [{len(deals)} deals]")
        for sector, total in totals:
            print(f"  {sector:<12} {usd(total):>12}")
        print(f"  -> Top sector: {totals[0][0]}, {usd(totals[0][1])}")

    print(f"\nWrote {clean_path.name} and {log_path.name}; {src.name} was only read.")


if __name__ == "__main__":
    main()
