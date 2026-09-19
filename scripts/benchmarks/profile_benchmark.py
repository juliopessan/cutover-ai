#!/usr/bin/env python3
"""Reproducible benchmark of the dataset profiler on the Cloudera dbt example seeds.

Measures (1) profiler time in-process, (2) upload-to-profile-page time against a real
server on localhost, (3) SHA-256 agreement with an independent hash, and (4) whether injected
defects are detected and clean files stay free of alerts. Writes src/cutover/web/benchmarks/profile.json,
which the landing page reads. Run from the repository root: `make benchmark`.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "cloudera_covid"
OUTPUT = ROOT / "src" / "cutover" / "web" / "benchmarks" / "profile.json"
RUNS_PROFILE = 20
RUNS_E2E = 5

sys.path.insert(0, str(ROOT / "src"))
from cutover.web.profiling import profile_csv  # noqa: E402


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct * (len(ordered) - 1)))]


def build_defective_copy(source: Path, target: Path) -> set[str]:
    """Inject six known defects into the cases file. Returns the alert kinds expected."""
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header, body = rows[0], rows[1:]
    header = [("geo id" if h == "geo_id" else h) for h in header] + ["Cases", "notes"]
    cases_index = rows[0].index("cases")
    out = [[*r, r[cases_index], ""] for r in body]
    out[1][rows[0].index("deaths")] = "n/a"  # mixed types
    out.append(list(out[0]))  # duplicate row
    out.append(["02/01/2022", "02"])  # malformed row
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(out)
    return {"column_names", "duplicate_columns", "mixed_types", "mostly_empty", "duplicate_rows", "malformed_rows"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(client: httpx.Client) -> None:
    for _ in range(50):
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not become ready")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def main() -> None:
    files = sorted(FIXTURES.glob("*.csv"))
    results: dict[str, dict] = {}
    for path in files:
        times = []
        for _ in range(RUNS_PROFILE):
            start = time.perf_counter()
            profile = profile_csv(path)
            times.append((time.perf_counter() - start) * 1000)
        data = path.read_bytes()
        results[path.name] = {
            "file": path.name,
            "bytes": len(data),
            "rows": profile.rows,
            "columns": len(profile.columns),
            "alerts": len(profile.flags),
            "sha256_matches_independent": profile.sha256 == hashlib.sha256(data).hexdigest(),
            "profile_ms_median": round(statistics.median(times), 2),
            "profile_ms_p95": round(percentile(times, 0.95), 2),
            "rows_per_second": round(profile.rows / (statistics.median(times) / 1000)),
        }

    port = free_port()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "CUTOVER_DATA_DIR": tmp}
        server = subprocess.Popen(
            [sys.executable, "-m", "cutover.cli", "serve", "--port", str(port), "--data-dir", tmp],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", follow_redirects=False, timeout=60) as client:
                wait_ready(client)
                client.post("/signup", data={"email": "bench@example.com", "password": "benchmark-password-1"})
                hash_on_page = 0
                for path in files:
                    times = []
                    for _ in range(RUNS_E2E):
                        start = time.perf_counter()
                        response = client.post("/app/datasets", files={"file": (path.name, path.read_bytes())},
                                               data={"target": "databricks"})
                        page = client.get(response.headers["location"]).text
                        times.append((time.perf_counter() - start) * 1000)
                    results[path.name]["upload_to_page_ms_median"] = round(statistics.median(times), 1)
                    if hashlib.sha256(path.read_bytes()).hexdigest() in page:
                        hash_on_page += 1
        finally:
            server.terminate()
            server.wait(timeout=10)

    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "cases_with_defects.csv"
        expected = build_defective_copy(FIXTURES / "raw_covid__cases.csv", broken)
        found = {f.kind for f in profile_csv(broken).flags}

    datasets = list(results.values())
    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "environment": {
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "cpus": os.cpu_count(),
        },
        "method": {"profile_runs_per_file": RUNS_PROFILE, "upload_runs_per_file": RUNS_E2E,
                   "server": "real uvicorn process on localhost, fresh SQLite"},
        "datasets": datasets,
        "totals": {
            "files": len(datasets),
            "rows": sum(d["rows"] for d in datasets),
            "bytes": sum(d["bytes"] for d in datasets),
            "sha256_confirmed_on_page": f"{hash_on_page}/{len(datasets)}",
            "false_alarms_on_clean_files": sum(d["alerts"] for d in datasets),
        },
        "detection": {
            "defects_injected": len(expected),
            "defects_detected": len(expected & found),
            "missed": sorted(expected - found),
            "unexpected_alerts": sorted(found - expected),
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"] | report["detection"], indent=2))
    for d in datasets:
        print(f"{d['file']:28} {d['rows']:>6} rows  profile {d['profile_ms_median']:>7} ms  upload+page {d['upload_to_page_ms_median']:>7} ms")
    assert re.fullmatch(r"\d+/\d+", report["totals"]["sha256_confirmed_on_page"])


if __name__ == "__main__":
    main()
