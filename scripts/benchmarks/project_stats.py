#!/usr/bin/env python3
"""Measured facts about the build, from git and the test suite. Writes src/cutover/web/benchmarks/project.json."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "src" / "cutover" / "web" / "benchmarks" / "project.json"
BASE = "f21463e"  # last commit before the Cutover rebrand


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def lines(pattern: str) -> int:
    total = 0
    for name in git("ls-files", pattern).splitlines():
        path = ROOT / name
        if path.is_file():
            total += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    return total


def main() -> None:
    stamps = [datetime.fromisoformat(s) for s in git("log", f"{BASE}..HEAD", "--format=%aI").splitlines()]
    shortstat = git("diff", "--shortstat", BASE, "HEAD")
    numbers = [int(n) for n in re.findall(r"(\d+) (?:files? changed|insertion|deletion)", shortstat)]
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT,
                               capture_output=True, text=True).stdout
    tests = int(m.group(1)) if (m := re.search(r"(\d+) tests? collected", collected)) else 0
    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "since": BASE, "commits": len(stamps),
        "first_commit": min(stamps).strftime("%Y-%m-%d %H:%M"), "last_commit": max(stamps).strftime("%Y-%m-%d %H:%M"),
        "span_hours": round((max(stamps) - min(stamps)).total_seconds() / 3600, 1),
        "files_changed": numbers[0] if numbers else 0, "insertions": numbers[1] if len(numbers) > 1 else 0,
        "deletions": numbers[2] if len(numbers) > 2 else 0,
        "tests": tests,
        "loc": {"sdk_and_app_python": lines("src/cutover/**/*.py") + lines("src/cutover/*.py"),
                "tests_python": lines("tests/*.py"), "templates_css_js": lines("src/cutover/web/templates/*")
                + lines("src/cutover/web/static/*.css") + lines("src/cutover/web/static/*.js")},
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
