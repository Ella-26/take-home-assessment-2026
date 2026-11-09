"""Section A test runner: sends every test input to the DeepSeek API
RUNS_PER_INPUT times (independent calls, no shared history) and saves
the raw outputs. Standard library only - no pip install needed.

Usage:
    python3 run_section_a.py              # run all tests
    python3 run_section_a.py --only test4 # run selected tests (comma-separated)
    python3 run_section_a.py --dry-run    # show the filled prompt, no API call
"""
import argparse
import json
import os
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ======================= CONFIG =======================
# Paste your key here, OR leave it empty and set the env var DEEPSEEK_API_KEY.
# Do not submit/zip this file with your key in it.
API_KEY = ""  # Add your own key locally, or set DEEPSEEK_API_KEY.

MODEL = "deepseek-flash"   # current DeepSeek model ID (Nov 2026); "deepseek-v4-pro" also works
THINKING = False           # deepseek-flash thinks by default; off = faster/cheaper extraction
TEMPERATURE = None         # None = API default; ignored when THINKING is True
JSON_MODE = False          # False = the prompt alone must produce JSON (closer to how graders run it)
RUNS_PER_INPUT = 3
API_URL = "https://api.deepseek.com/chat/completions"
# ======================================================

HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompt"
INPUT_DIR = HERE / "test_inputs"
OUTPUT_ROOT = HERE / "outputs"
PLACEHOLDER = "[passage omitted]"

ROUNDS = {"Pre-seed", "Seed", "Series A", "Series B", "Series C+", "Unknown"}
COMPANY_KEYS = {"name", "hq_country", "sector", "round", "amount_usd",
                "lead_investors", "evidence"}


def ssl_context():
    try:
        import certifi  # optional; helps on python.org builds of Python on macOS
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def call_api(api_key, system_msg, user_msg):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "thinking": {"type": "enabled" if THINKING else "disabled"},
    }
    if TEMPERATURE is not None:
        body["temperature"] = TEMPERATURE
    if JSON_MODE:
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key},
        method="POST",
    )
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120, context=ssl_context()) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            last_err = "HTTP %s: %s" % (e.code, msg)
            if e.code not in (429, 500, 502, 503, 504):
                break  # bad key / bad request: retrying won't help
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = "Network error: %s" % e
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                last_err += ("  -> run 'pip3 install certifi' or the "
                             "'Install Certificates.command' in your Python folder")
                break
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last_err)


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def check(raw, article):
    """Quick schema check. Returns (parsed_or_None, list_of_issues, one-line brief)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, ["not valid JSON (%s)" % e.msg], "INVALID JSON"
    issues = []
    if not isinstance(data, dict) or set(data) != {"companies"}:
        issues.append("top level must be exactly {'companies': [...]}")
    companies = data.get("companies") if isinstance(data, dict) else None
    if not isinstance(companies, list):
        return data, issues + ["'companies' is not a list"], "BAD SHAPE"
    briefs = []
    for i, c in enumerate(companies):
        tag = "companies[%d]" % i
        if not isinstance(c, dict):
            issues.append(tag + " is not an object")
            continue
        if set(c) != COMPANY_KEYS:
            issues.append("%s keys differ: missing %s, extra %s" % (
                tag, sorted(COMPANY_KEYS - set(c)), sorted(set(c) - COMPANY_KEYS)))
        if c.get("round") not in ROUNDS:
            issues.append("%s round not allowed: %r" % (tag, c.get("round")))
        amt = c.get("amount_usd")
        if amt is not None and (isinstance(amt, bool) or not isinstance(amt, (int, float))):
            issues.append("%s amount_usd not a number/null: %r" % (tag, amt))
        for k in ("hq_country", "sector"):
            if c.get(k) is not None and not isinstance(c.get(k), str):
                issues.append("%s %s not string/null" % (tag, k))
        leads = c.get("lead_investors")
        if not isinstance(leads, list) or not all(isinstance(x, str) for x in leads):
            issues.append(tag + " lead_investors not a list of strings")
        ev = c.get("evidence")
        if not isinstance(ev, str) or not ev.strip():
            issues.append(tag + " evidence missing")
        elif norm(ev) not in norm(article):
            issues.append(tag + " evidence is not a verbatim quote from the article")
        briefs.append("%s | %s | %s | %s | %s | %s" % (
            c.get("name"), c.get("hq_country"), c.get("sector"),
            c.get("round"), amt, leads))
    return data, issues, ("; ".join(briefs) if briefs else "(empty list)")


def canonical(data, drop_evidence=False):
    if not isinstance(data, dict) or not isinstance(data.get("companies"), list):
        return None
    comps = []
    for c in data["companies"]:
        if isinstance(c, dict):
            c = dict(c)
            if drop_evidence:
                c.pop("evidence", None)
        comps.append(c)
    return json.dumps(comps, sort_keys=True, ensure_ascii=False)


def load_inputs(only):
    tests = []
    for f in sorted(INPUT_DIR.glob("*.txt")):
        if only and f.stem not in only:
            continue
        text = f.read_text(encoding="utf-8").strip()
        if not text:
            print("SKIP %s: file is empty (write your own test input in it)" % f.name)
        elif PLACEHOLDER in text:
            print("SKIP %s: still contains %s - replace it first" % (f.name, PLACEHOLDER))
        else:
            tests.append((f.stem, text))
    return tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print prompts, no API calls")
    ap.add_argument("--only", default="", help="comma-separated test names, e.g. test3,test4")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    system_msg = (PROMPT_DIR / "system.txt").read_text(encoding="utf-8").strip()
    template = (PROMPT_DIR / "user_template.txt").read_text(encoding="utf-8").strip()
    if "{article}" not in template:
        sys.exit("user_template.txt must contain {article}")

    tests = load_inputs(only)
    if not tests:
        sys.exit("No test inputs to run.")

    if args.dry_run:
        for name, text in tests:
            print("\n===== %s =====\n[SYSTEM]\n%s\n\n[USER]\n%s"
                  % (name, system_msg, template.replace("{article}", text)))
        return

    api_key = API_KEY.strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        sys.exit("No API key: paste it into API_KEY at the top of this file, "
                 "or run: export DEEPSEEK_API_KEY=sk-...")

    out_dir = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    shutil.copytree(PROMPT_DIR, out_dir / "prompt_used")  # record which prompt version made these outputs
    settings = {"model": MODEL, "thinking": THINKING, "temperature": TEMPERATURE,
                "json_mode": JSON_MODE, "runs_per_input": RUNS_PER_INPUT,
                "started": datetime.now().isoformat(timespec="seconds")}

    md = ["# Section A raw outputs", "",
          "Settings: `%s`" % json.dumps(settings), ""]
    jsonl = open(out_dir / "api_responses.jsonl", "w", encoding="utf-8")

    for name, text in tests:
        user_msg = template.replace("{article}", text)  # replace, not .format: articles may contain braces
        md += ["## %s" % name, "", "Input:", "", "```text", text, "```", ""]
        runs = []
        for n in range(1, RUNS_PER_INPUT + 1):
            print("%s run %d ... " % (name, n), end="", flush=True)
            try:
                resp = call_api(api_key, system_msg, user_msg)
                msg = resp["choices"][0]["message"]
                raw = msg.get("content") or ""
                err = None
            except Exception as e:  # keep going so one failure doesn't lose the other runs
                resp, msg, raw, err = None, {}, "", str(e)

            fname = "%s_run%d.txt" % (name, n)
            (out_dir / fname).write_text(raw if err is None else "ERROR: " + err, encoding="utf-8")
            jsonl.write(json.dumps({"test": name, "run": n, "settings": settings,
                                    "error": err, "response": resp}, ensure_ascii=False) + "\n")

            if err:
                print("ERROR: " + err)
                md += ["### Run %d - ERROR" % n, "", "```text", err, "```", ""]
                runs.append(None)
                continue
            data, issues, brief = check(raw, text)
            runs.append(data)
            print("OK" if not issues else "%d issue(s)" % len(issues), "|", brief)
            for i in issues:
                print("    - " + i)
            md += ["### Run %d" % n, "", "```json", raw, "```", ""]
            if msg.get("reasoning_content"):
                md += ["<details><summary>reasoning</summary>", "",
                       msg["reasoning_content"], "", "</details>", ""]
            md += ["Check: " + ("passed" if not issues else "; ".join(issues)), ""]

        full = {canonical(r) for r in runs}
        no_ev = {canonical(r, drop_evidence=True) for r in runs}
        verdict = ("all %d runs identical" % len(runs) if len(full) == 1 and None not in full
                   else "same fields, evidence wording differs" if len(no_ev) == 1 and None not in no_ev
                   else "runs DIFFER in extracted values")
        print("  consistency: " + verdict)
        md += ["**Consistency (%s): %s**" % (name, verdict), ""]

    jsonl.close()
    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\nSaved to: %s" % out_dir)
    print("  - <test>_run<n>.txt : raw model output, exactly as returned")
    print("  - summary.md        : inputs + all raw outputs + checks, for your write-up")
    print("  - api_responses.jsonl, prompt_used/ : full API responses and the prompt version used")


if __name__ == "__main__":
    main()
