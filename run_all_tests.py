#!/usr/bin/env python3
"""Run frontend/backend tests and write detailed + executive reports."""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SCRIPTS = [("Frontend", ROOT / "tests" / "test_frontend.py"),
           ("Backend, database and security", ROOT / "tests" / "test_backend.py")]

def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    started = dt.datetime.now().astimezone()
    sections = []
    all_lines = []
    script_results = []
    for label, script in SCRIPTS:
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = result.stdout.strip() or "(no output)"
        sections.append(f"## {label}\n\nExit code: `{result.returncode}`\n\n```text\n{output}\n```")
        lines = [line for line in output.splitlines() if re.match(r"^(PASS|FAIL|SKIP):", line)]
        all_lines.extend(lines)
        script_results.append((label, result.returncode))
    ended = dt.datetime.now().astimezone()
    counts = {status: sum(line.startswith(status + ":") for line in all_lines) for status in ("PASS", "FAIL", "SKIP")}
    failed_scripts = [name for name, code in script_results if code != 0]
    status = "FAILED" if failed_scripts or counts["FAIL"] else "PASSED WITH SKIPS" if counts["SKIP"] else "PASSED"

    detailed = [
        "# Automated test report",
        f"\n- Started: {started.isoformat(timespec='seconds')}",
        f"- Finished: {ended.isoformat(timespec='seconds')}",
        f"- Overall: **{status}**",
        f"- Results: **{counts['PASS']} passed · {counts['FAIL']} failed · {counts['SKIP']} skipped**",
        "\nThis report records checks actually executed. Skipped checks are not counted as passes.",
        "\n## Check-by-check results\n",
        *[f"- {line}" for line in all_lines],
        "\n## Execution output\n",
        *sections,
        "\n## Scope and limitations\n",
        "- Frontend checks cover source wiring, production build when dependencies are installed, and browser smoke checks when a Playwright browser is available.",
        "- Backend checks cover database read-only enforcement, parameterized query behavior, customer ownership, local injection screening, staff/session control implementation, and refund idempotency on a temporary database copy.",
        "- Live OpenAI calls and live Realtime audio are not exercised. The local environment also lacks the OpenAI/Chroma runtime packages needed to start the full API lifespan.",
        "- The npm dependency installation timed out in this environment, so the Vite production build and browser smoke test were skipped; run `cd frontend && npm ci` and rerun the test runner.",
        "- Deployment infrastructure and multi-process/race/load behavior are not exercised by this offline test run.",
    ]
    summary = [
        "# Test summary",
        f"\n**{status}** — {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped.",
        "\n## What was checked",
        "- Frontend login/demo controls, staff action wiring, chat refresh and voice integration; Vite build/browser smoke where available.",
        "- Backend SQLite read-only protection, parameterized SQL, cross-customer isolation, injection screening, RBAC/session controls and refund idempotency.",
        "\n## Findings",
        *([f"- Failed: {line[6:]}" for line in all_lines if line.startswith("FAIL:")] or ["- No failing checks in the executed test set."]),
        *([f"- Skipped: {line[6:]}" for line in all_lines if line.startswith("SKIP:")]),
        "\nLive API-provider/voice calls and real deployment/load testing are outside this local automated run. The current environment could not install npm dependencies and does not have the OpenAI/Chroma packages needed for full API startup.",
    ]
    (REPORTS / "detailed_test_report.md").write_text("\n".join(detailed) + "\n", encoding="utf-8")
    (REPORTS / "summary_test_report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"OVERALL: {status}")
    print(f"COUNTS: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    print("REPORT: reports/detailed_test_report.md")
    print("REPORT: reports/summary_test_report.md")
    return 1 if failed_scripts or counts["FAIL"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
