"""Command line entry point for Cutover."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from cutover.core.agent import AgentContext
from cutover.plugins.onboarding import OnboardingAgent


def _package_version() -> str:
    try:
        return version("cutover-ai")
    except PackageNotFoundError:
        return "0.0.0+local"


def _onboard(answers_path: Path) -> int:
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    agent = OnboardingAgent()
    result = asyncio.run(agent.execute(AgentContext(run_id="cli"), answers))
    payload = dict(result.payload)
    if "intake" in payload:
        intake = payload["intake"]
        payload["intake"] = {
            "project_name": intake.project_name,
            "readiness": intake.readiness.value,
            "targets": [target.platform for target in intake.targets],
        }
    json.dump({"status": result.status, **payload}, sys.stdout, indent=2, default=list)
    sys.stdout.write("\n")
    return 0 if result.status == "ready" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cutover", description="Governed data migration factory.")
    parser.add_argument("--version", action="version", version=f"cutover {_package_version()}")
    commands = parser.add_subparsers(dest="command", required=True)
    onboard = commands.add_parser("onboard", help="Evaluate onboarding answers and report readiness.")
    onboard.add_argument("--answers", type=Path, required=True, help="JSON file with intake answers.")
    serve = commands.add_parser("serve", help="Run the Cutover web application.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data-dir", type=Path, default=None, help="Where the database and uploads live.")
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        from cutover.web import create_app

        uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port)
        return 0
    if args.command == "onboard":
        return _onboard(args.answers)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
